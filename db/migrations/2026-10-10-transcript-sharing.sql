-- 통화 요약·원문 공개 (설계: docs/plans/2026-10-09-transcript-sharing-design.md).
-- 기존 서버(RDS)에 한 번 실행한다. 새 설치는 db/schema.sql에 같은 내용이 있다.
-- 원격 DB에 쓰는 일이므로 실행 전에 내용을 확인하고 사용자가 psql로 직접 돌린다.

ALTER TABLE elders ADD COLUMN IF NOT EXISTS share_agreed_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS call_reports (
    call_id    BIGINT PRIMARY KEY REFERENCES calls(call_id) ON DELETE CASCADE,
    summary    TEXT NOT NULL,
    model_id   TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE call_turns (
    call_id    BIGINT NOT NULL REFERENCES calls(call_id) ON DELETE CASCADE,
    seq        INT NOT NULL,
    speaker    TEXT NOT NULL CHECK (speaker IN ('ai', 'elder')),
    text       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (call_id, seq)
);

CREATE TABLE transcript_views (
    view_id     BIGSERIAL PRIMARY KEY,
    call_id     BIGINT NOT NULL REFERENCES calls(call_id) ON DELETE CASCADE,
    guardian_id BIGINT NOT NULL REFERENCES guardians(guardian_id) ON DELETE CASCADE,
    viewed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
