-- 안심케어 — 독거노인 AI 안부 전화 · 데이터베이스 스키마
-- 팀 공명
-- PostgreSQL 16
-- 설계 근거: docs/superpowers/specs/2026-09-07-ansimcare-design.md

-- ============================================================
-- 1. 보호자
--
-- elders보다 먼저 정의한다. 원 기획안 DDL은 elders가 아직 만들어지지 않은
-- guardians를 참조해서 실행 자체가 실패했다(PostgreSQL은 전방 참조 불가).
-- ============================================================

CREATE TABLE guardians (
    guardian_id   BIGSERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    phone_number  TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 2. 어르신
-- ============================================================

CREATE TABLE elders (
    elder_id     BIGSERIAL PRIMARY KEY,
    guardian_id  BIGINT NOT NULL REFERENCES guardians(guardian_id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    phone_number TEXT NOT NULL UNIQUE,
    birth_date   DATE,
    call_time    TIME NOT NULL DEFAULT '09:00',

    -- 동의 (설계 3.6). NULL이면 발신 대상에서 제외한다.
    consent_at   TIMESTAMPTZ,

    -- 개인 기준선 (설계 3.2). 위험 판정은 절대값이 아니라 이 값 대비 변화로 한다.
    -- 최근 통화들의 이동 평균으로 갱신된다.
    baseline_speech_ratio          REAL CHECK (baseline_speech_ratio BETWEEN 0 AND 1),
    baseline_avg_response_delay_ms INT  CHECK (baseline_avg_response_delay_ms >= 0),
    baseline_updated_at            TIMESTAMPTZ,

    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX elders_guardian_idx ON elders (guardian_id);
-- 스케줄러가 "지금 걸 어르신"을 찾는 쿼리. 동의 안 한 분은 아예 인덱스에 없다.
CREATE INDEX elders_due_idx ON elders (call_time) WHERE consent_at IS NOT NULL;

-- ============================================================
-- 3. 통화
-- ============================================================

CREATE TABLE calls (
    call_id           BIGSERIAL PRIMARY KEY,
    elder_id          BIGINT NOT NULL REFERENCES elders(elder_id) ON DELETE CASCADE,
    call_type         TEXT NOT NULL DEFAULT 'outbound'
                      CHECK (call_type IN ('outbound', 'inbound')),
    -- 채널은 전화망 하나뿐이다. 이제 구분해야 하는 것은 "누가 시작했나"다.
    -- 요청 통화의 미응답은 "버튼을 누르고 전화기를 못 찾았다"일 뿐이라
    -- 위험 신호로 세면 활발한 어르신이 오히려 감점된다(설계 6장).
    trigger_type      TEXT NOT NULL DEFAULT 'scheduled'
                      CHECK (trigger_type IN ('scheduled', 'requested')),
    -- 원 스키마는 미응답·발신실패를 표현할 수 없었다(ended_at NULL로만 추정).
    status            TEXT NOT NULL DEFAULT 'scheduled'
                      CHECK (status IN ('scheduled', 'ringing', 'answered',
                                        'completed', 'no_answer', 'failed')),
    provider_call_sid TEXT UNIQUE,          -- 전화망 사업자 측 식별자. 발신 전에는 NULL
    audio_key         TEXT,                 -- S3. 30일 뒤 삭제(설계 3.6)
    started_at        TIMESTAMPTZ,
    ended_at          TIMESTAMPTZ,
    duration_ms       INT CHECK (duration_ms >= 0),
    error_code        TEXT CHECK (error_code IN (
                          'NO_ANSWER', 'CALL_FAILED', 'INVALID_AUDIO', 'VAD_FAILED',
                          'STT_FAILED', 'LLM_ERROR', 'DB_ERROR', 'INTERNAL')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT calls_error_requires_failure
        CHECK (error_code IS NULL OR status IN ('failed', 'no_answer')),
    -- 통화가 끝났다면 분석할 오디오가 있어야 한다. 없으면 파이프라인이 조용히 멈춘다.
    CONSTRAINT calls_completed_requires_audio
        CHECK (status <> 'completed' OR audio_key IS NOT NULL)
);

CREATE INDEX calls_elder_idx ON calls (elder_id, started_at DESC);
-- 워커 재시작 시 미완료 통화 회수용
CREATE INDEX calls_pending_idx ON calls (created_at)
    WHERE status IN ('scheduled', 'ringing', 'answered');

-- ============================================================
-- 4. 전사
-- ============================================================

CREATE TABLE call_transcripts (
    call_id    BIGINT NOT NULL REFERENCES calls(call_id) ON DELETE CASCADE,
    turn_index INT  NOT NULL CHECK (turn_index >= 0),
    speaker    TEXT NOT NULL CHECK (speaker IN ('ai', 'elder')),
    text       TEXT NOT NULL,
    start_ms   INT  NOT NULL CHECK (start_ms >= 0),
    end_ms     INT  NOT NULL,
    PRIMARY KEY (call_id, turn_index),
    CONSTRAINT transcript_span_is_forward CHECK (end_ms >= start_ms)
);

-- ============================================================
-- 5. 결정론적 지표 — 서버가 계산한 숫자
--
-- LLM 요약(call_reports)과 테이블을 나누는 것이 설계 3.2의 구조적 표현이다.
-- 한 테이블에 섞으면 "이 숫자를 누가 만들었나"가 흐려진다.
-- ============================================================

CREATE TABLE call_metrics (
    call_id                 BIGINT PRIMARY KEY REFERENCES calls(call_id) ON DELETE CASCADE,
    speech_ratio            REAL CHECK (speech_ratio  BETWEEN 0 AND 1),
    silence_ratio           REAL CHECK (silence_ratio BETWEEN 0 AND 1),
    turn_count              INT  CHECK (turn_count          >= 0),
    negative_word_count     INT  CHECK (negative_word_count >= 0),
    -- 어르신이 한 번도 응답하지 않으면 NULL. 0으로 두면 평균이 왜곡된다.
    avg_response_delay_ms   INT  CHECK (avg_response_delay_ms >= 0),
    no_answer_recent_7      INT  CHECK (no_answer_recent_7 BETWEEN 0 AND 7),

    -- 판정에 쓰지 않는 원자료. 통화 녹음은 30일 뒤 삭제되므로(설계 3.6),
    -- 여기 남기지 않은 값은 그 뒤로 어디에서도 복구할 수 없다 — wav가 없으면
    -- 다시 계산할 방법이 없다. 비율만 남기면 분모를 바꾼 순간(2.0.0이 그랬다)
    -- 과거 데이터를 재해석할 수조차 없다.
    call_duration_ms        INT CHECK (call_duration_ms  >= 0),
    elder_speech_ms         INT CHECK (elder_speech_ms   >= 0),
    ai_speech_ms            INT CHECK (ai_speech_ms      >= 0),
    silence_ms              INT CHECK (silence_ms        >= 0),
    -- 스트림 유실을 메운 지어낸 침묵. 30% 문턱 아래여도 지표는 이미 그만큼
    -- 끌려가므로, degraded가 아니어도 남긴다.
    filled_gap_ms           INT CHECK (filled_gap_ms     >= 0),
    -- 턴별 응답 지연 원본. 평균이 나은지 중앙값이 나은지는 분포를 봐야
    -- 정할 수 있는데, 평균만 남기면 그 질문에 영영 답할 수 없다.
    response_delays_ms      INT[],

    -- 이 판정이 실제로 쓴 기준선. 기준선은 저장하지 않고 매번 과거에서 다시
    -- 계산하므로(설계 3.1), 당시 값이 없으면 판정을 재현할 수 없다.
    baseline_n              INT  CHECK (baseline_n >= 0),
    baseline_speech_ratio   REAL CHECK (baseline_speech_ratio BETWEEN 0 AND 1),
    baseline_avg_response_delay_ms INT CHECK (baseline_avg_response_delay_ms >= 0),

    -- VAD 실패 시 NULL. 임의 점수를 만들지 않는다(설계 8장).
    risk_score              INT  CHECK (risk_score BETWEEN 0 AND 100),
    risk_level              TEXT CHECK (risk_level IN ('normal', 'watch', 'alert')),

    baseline_speech_delta   REAL,
    baseline_delay_delta_ms INT,

    degraded                BOOLEAN NOT NULL DEFAULT false,
    -- 왜 근거가 부족한가: echo_clip(우리 알고리즘) / fabricated_silence(통신) /
    -- unmatched_marks(사업자). 고쳐야 할 곳이 전혀 다른데 bool 하나로는
    -- 구분이 안 되고, 보호자에게 "왜 계산하지 못했는지"도 말할 수 없다.
    degraded_reasons        TEXT[] NOT NULL DEFAULT '{}',
    -- 가중치를 바꾸면 이전 점수와 비교할 수 없다. 어느 버전이 낸 점수인지 남긴다.
    calculator_version      TEXT NOT NULL,
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT metrics_score_and_level_together
        CHECK ((risk_score IS NULL) = (risk_level IS NULL))
);

CREATE INDEX call_metrics_risk_idx ON call_metrics (risk_level, computed_at DESC);

-- ============================================================
-- 6. LLM 요약 — 설명만 담당한다
-- ============================================================

CREATE TABLE call_reports (
    call_id    BIGINT PRIMARY KEY REFERENCES calls(call_id) ON DELETE CASCADE,
    summary    TEXT NOT NULL,
    model_id   TEXT NOT NULL,        -- 'HCX-DASH-002'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE call_reports IS
    'LLM이 쓴 문장만 담는다. 숫자는 call_metrics에 있으며 LLM은 관여하지 않는다(설계 3.2).';

-- ============================================================
-- 7. 알림
-- ============================================================

CREATE TABLE alerts (
    alert_id    BIGSERIAL PRIMARY KEY,
    elder_id    BIGINT NOT NULL REFERENCES elders(elder_id) ON DELETE CASCADE,
    guardian_id BIGINT NOT NULL REFERENCES guardians(guardian_id) ON DELETE CASCADE,
    call_id     BIGINT REFERENCES calls(call_id) ON DELETE SET NULL,
    alert_type  TEXT NOT NULL
                CHECK (alert_type IN ('risk_rise', 'no_answer', 'emergency_keyword')),
    severity    TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    message     TEXT NOT NULL,
    sent_at     TIMESTAMPTZ,
    read_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX alerts_guardian_idx ON alerts (guardian_id, created_at DESC);
-- 발송 워커가 타는 인덱스
CREATE INDEX alerts_unsent_idx ON alerts (created_at) WHERE sent_at IS NULL;
