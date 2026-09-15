# 안심케어 — 시스템 설계도

- **팀명:** 공명
- **작성일:** 2026-09-15
- **기준:** `2026-09-15-pstn-call-design.md` (전화망 단일 채널)

> 한 장에 다 넣으면 읽을 수 없으므로 관점별로 나눕니다. 1장이 전체, 2장이 시간 흐름, 3장이 이 프로젝트의 간판(결정론), 4~6장이 데이터·코드·인프라입니다.

---

## 1. 전체 구성

```mermaid
flowchart TB
    elder(("어르신"))
    guardian(("보호자"))
    phone(("어르신<br>전화기"))

    subgraph APP["늘봄 앱 · Flutter"]
        A1["어르신 화면<br>AI 친구 버튼"]
        A2["보호자 화면<br>위험 추이 · 통화 기록"]
    end

    subgraph SRV["우리 서버 · EC2"]
        SCH["스케줄러<br>매일 09:00"]
        T["트리거 API<br>POST /v1/calls/request"]
        V["VoiceML 웹훅<br>POST /v1/voiceml"]
        WS["스트림 서버<br>WSS /v1/stream"]
        CS["CallSession<br>타임라인 · mark · 녹음"]
        AN["분석 파이프라인<br>VAD · 지표 · 위험도"]
    end

    subgraph EXT["외부 서비스"]
        CO["ClawOps<br>070 번호 · PSTN"]
        CL["CLOVA<br>Speech · Studio · Voice"]
        FCM["FCM"]
    end

    DB[("PostgreSQL")]
    S3[("S3<br>녹음 30일 후 삭제")]

    elder --> A1
    guardian --> A2
    A1 -->|"전화 요청"| T
    SCH -->|"정기 발신"| T
    T -->|"POST /calls"| CO
    CO -->|"발신"| phone
    phone -->|"어르신이 받음"| CO
    CO -->|"CallId"| V
    V -->|"Connect Stream XML"| CO
    CO -->|"어르신 음성 μ-law 20ms"| WS
    WS -->|"AI 음성 μ-law"| CO
    WS --> CS
    CS -->|"발화 오디오"| CL
    CL -->|"응답 음성"| CS
    CS -->|"wav"| AN
    CS --> S3
    AN --> DB
    AN -->|"위험 감지"| FCM
    FCM --> A2
    A2 --> DB
```

**핵심은 `ClawOps → 스트림 서버` 화살표가 어르신 음성 하나뿐이라는 것입니다.** AI 음성은 우리가 보냅니다. 이 비대칭이 곧 화자 분리이고, Asterisk를 걷어낸 근거입니다.

---

## 2. 통화 한 통 — 시간 순서

```mermaid
sequenceDiagram
    autonumber
    participant APP as 늘봄 앱
    participant API as 트리거 API
    participant CO as ClawOps
    participant PH as 어르신 전화기
    participant WS as 스트림 서버
    participant CL as CLOVA

    APP->>API: POST /v1/calls/request
    API->>API: 진행 중 통화 확인
    Note over API: 있으면 409 + 기존 call_id<br>두 번 누른 것은 오류가 아니다
    API->>API: 1회용 토큰 발급
    API->>CO: POST /calls (To, From 070, Url)
    API-->>APP: 202 call_id
    Note over APP: "곧 전화가 갑니다"

    CO->>PH: 발신
    PH-->>CO: 어르신이 받음
    CO->>API: POST /v1/voiceml (CallId)
    API-->>CO: Connect Stream + token

    CO->>WS: WSS 접속
    WS->>WS: 토큰 대조
    CO->>WS: start (customParameters.token)

    loop 통화 중
        CO->>WS: media (μ-law, timestamp)
        WS->>WS: 갭이면 침묵 채움
        WS->>WS: StreamingVad 발화 종료 감지
        WS->>CL: 발화 오디오
        CL-->>WS: 응답 음성
        WS->>CO: mark begin
        WS->>CO: media (AI 음성)
        WS->>CO: mark end
        CO-->>WS: mark begin (재생 시작)
        CO-->>WS: mark end (재생 종료)
    end

    CO->>WS: stop
    WS->>WS: 누적분을 wav로 저장
    CO->>API: POST /v1/stream-ended
    API-->>CO: Say + Hangup
```

**`mark`가 두 번 오가는 것이 이 그림의 요점입니다.** 우리가 보낸 시각이 아니라 **되돌아온 시각**이 AI 발화 구간이고, 그 시각은 직전 `media.timestamp`에서 읽습니다. 벽시계를 쓰면 재현성이 깨집니다.

---

## 3. 분석 파이프라인 — LLM은 숫자를 만들지 않는다

이 프로젝트의 간판입니다. 감정 점수를 LLM이 산출하면 같은 대화에 오늘 62점 내일 71점이 나오고, **추이 그래프가 노이즈가 되어 보호자는 알림을 무시하게 됩니다.**

```mermaid
flowchart TB
    WAV["통화 녹음 wav<br>어르신 트랙 8kHz"]
    AIT["AI 발화 구간<br>mark에서"]

    subgraph DET["결정론 구역 — 같은 입력이면 같은 숫자"]
        VAD["segment_audio<br>발화 · 침묵 구간 확정"]
        ECHO["clip_ai_playback<br>에코 제거"]
        STT["CLOVA Speech<br>어르신 트랙만 전사"]
        NEG["부정 표현 사전 매칭<br>아프 · 힘들 · 외로"]
        MET["calculate_metrics<br>발화비율 · 지연 · 침묵 · 턴수"]
        RISK["assess_risk<br>개인 기준선 대비 변화"]
    end

    subgraph GEN["생성 구역 — 숫자에 관여하지 않음"]
        LLM["CLOVA Studio<br>HyperCLOVA X"]
    end

    OUT["risk_score · risk_level<br>+ 보호자용 설명 문장"]

    WAV --> VAD
    VAD --> ECHO
    AIT --> ECHO
    WAV --> STT
    STT --> NEG
    ECHO --> MET
    AIT --> MET
    NEG --> MET
    MET --> RISK
    RISK --> OUT
    RISK -->|"확정된 숫자 + 전사문"| LLM
    LLM -->|"요약 문장만"| OUT
```

```python
def test_score_is_identical_across_repeated_runs():
    scores = {assess_risk(metrics, ...).risk_score for _ in range(100)}
    assert len(scores) == 1
```

**같은 입력 100회 → 점수 편차 0.** 이 테스트가 위 그림의 경계를 코드로 증명합니다.

### 지표와 출처

| 지표 | 가중치 | 출처 | 화자 분리가 필요한가 |
|---|---|---|---|
| 발화 비율 | 35 | VAD | **필요** — 어르신 트랙만 |
| 평균 응답 지연 | 25 | VAD + mark | **필요** — AI 종료 시각 |
| 부정 표현 빈도 | 20 | 전사문 | 필요 — 어르신 발화만 |
| 미응답 이력 | 20 | 통화 기록 | 불필요 |
| 침묵 비율 · 발화 턴 수 | 보조 | VAD | 필요 |

**100점 중 60점이 화자 분리 위에 서 있습니다.** ClawOps 스트림이 이걸 주기 때문에 Asterisk가 필요 없어졌습니다.

---

## 4. 데이터 모델

```mermaid
erDiagram
    guardians ||--o{ elders : "돌본다"
    guardians ||--o{ alerts : "받는다"
    elders ||--o{ calls : "통화한다"
    elders ||--o{ alerts : "대상"
    calls ||--o{ call_transcripts : "발화"
    calls ||--|| call_metrics : "지표"
    calls ||--|| call_reports : "요약"
    calls ||--o{ alerts : "근거"

    guardians {
        bigint guardian_id PK
        text email UK
        text password_hash
    }
    elders {
        bigint elder_id PK
        bigint guardian_id FK
        text phone_number
        time call_time "정기 발신 시각"
        timestamptz consent_at "동의 없으면 발신 안 함"
        real baseline_speech_ratio "개인 기준선"
        int baseline_avg_response_delay_ms
    }
    calls {
        bigint call_id PK
        bigint elder_id FK
        text trigger_type "scheduled 또는 requested"
        text status "scheduled ringing answered completed no_answer failed"
        text provider_call_sid UK
        text audio_key "S3. 30일 뒤 삭제"
        int duration_ms
        text error_code
    }
    call_transcripts {
        bigint call_id PK
        int turn_index PK
        text speaker "ai 또는 elder"
        text text
        int start_ms
        int end_ms
    }
    call_metrics {
        bigint call_id PK
        real speech_ratio
        real silence_ratio
        int turn_count
        int negative_word_count
        int avg_response_delay_ms
        int risk_score
        text risk_level
        boolean degraded "정확도 낮음"
        text calculator_version
    }
    call_reports {
        bigint call_id PK
        text summary "LLM이 쓴 설명"
        text model_id
    }
    alerts {
        bigint alert_id PK
        text alert_type
        text severity
        timestamptz sent_at
    }
```

**설계에서 지킨 것 셋**

- `call_metrics.calculator_version` — 계산식이 바뀌면 과거 점수와 비교하면 안 된다는 것을 **데이터가 스스로 말하게** 한다
- `call_metrics.degraded` — 분석 품질이 낮을 때 실패로 처리하지 않고 정직하게 표시한다
- `elders.consent_at` — 동의 없이는 발신하지 않는다 (설계 3.6). 인덱스도 `WHERE consent_at IS NOT NULL`

> `calls.trigger_type`은 계획 Task 2에서 적용됩니다. 현재 스키마에는 아직 `channel`이 있습니다.

---

## 5. 코드 모듈 의존

```mermaid
flowchart BT
    subgraph ANALYSIS["app/analysis — 순수 함수. 외부 의존 없음"]
        SEG["segments.py<br>VadSegment"]
        VADM["vad_segmenter.py<br>segment_audio · adaptive_threshold"]
        ECHOM["echo.py<br>clip_ai_playback"]
        METM["metrics_calculator.py<br>calculate_metrics"]
        CAM["call_analysis.py<br>analyze_call"]
    end

    subgraph MEDIA["app/media — 통화 중"]
        ULAW["ulaw.py"]
        SVAD["streaming_vad.py"]
        RESP["responder.py<br>Responder 규약"]
        SESS["session.py<br>CallSession"]
        STREAM["stream_server.py<br>ClawOps 어댑터"]
    end

    subgraph EDGE["app/telephony · app/api — 바깥과 닿는 곳"]
        VML["voiceml.py"]
        TEL["client.py<br>Telephony 규약"]
        CALLS["calls.py<br>트리거 API"]
        STORE["store.py<br>CallStore 규약"]
    end

    VADM --> SEG
    ECHOM --> SEG
    METM --> SEG
    CAM --> VADM
    CAM --> ECHOM
    CAM --> METM
    SVAD --> VADM
    SESS --> SVAD
    SESS --> RESP
    SESS --> SEG
    STREAM --> SESS
    STREAM --> ULAW
    CALLS --> TEL
    CALLS --> VML
    CALLS --> STORE
    CALLS --> STREAM
```

**화살표가 위로만 갑니다.** 아래층(`analysis`)은 위층을 모릅니다. 그래서 분석 코어는 클라우드도 네트워크도 없이 로컬에서 전부 테스트됩니다.

**`CallSession`이 `stream_server`를 모른다**는 점이 중요합니다. 앱 WebSocket용으로 만든 코드가 전화망에서 그대로 재사용됐습니다 — 프레임 출처만 바뀌었습니다.

### 규약으로 분리한 것

| 규약 | 진짜 구현 | 가짜 구현 | 왜 |
|---|---|---|---|
| `Responder` | `ClovaResponder` | `CannedResponder` | NCP 신청 전에 통화 경로 완성 |
| `Telephony` | `ClawOpsTelephony` | `FakeTelephony` | ClawOps 계정 전에 트리거 API 완성 |
| `CallStore` | PostgreSQL | `InMemoryCallStore` | DB 연결 전에 API 완성 |
| `CallRegistry` | PostgreSQL | `InMemoryCallRegistry` | 〃 |

**외부 의존을 전부 뒤로 미룰 수 있게 만든 것**이 이 프로젝트의 진행 방식입니다.

---

## 6. 인프라

```mermaid
flowchart LR
    subgraph NET["인터넷"]
        CO["ClawOps"]
        CL["CLOVA · NCP"]
        FCM["FCM"]
    end

    subgraph AWS["AWS · ap-northeast-2"]
        subgraph EC2["EC2 t3.small"]
            UV["uvicorn<br>트리거 API + 스트림 서버"]
        end
        RDS[("PostgreSQL 16")]
        S3[("S3 버킷<br>라이프사이클 30일 삭제")]
    end

    CO -->|"HTTPS 웹훅"| UV
    CO -->|"WSS 미디어"| UV
    UV -->|"HTTPS"| CL
    UV --> RDS
    UV --> S3
    UV --> FCM
```

| 항목 | 선택 | 월 비용 |
|---|---|---|
| 전화망 | ClawOps **Individual** (100분 포함) | ₩19,000 |
| 서버 | EC2 (미디어 서버 겸 API) | 약 ₩18,000 |
| STT/TTS/LLM | CLOVA Speech · Voice · Studio | 사용량 — NCP 신청 후 |
| **합** | | **약 ₩37,000 + CLOVA** |

**쓰지 않는 것** — ClawOps SIP 애드온(₩99,000), ClawOps 전사(₩10/분), ClawOps AI 에이전트(₩30~140/분), AWS Chime SDK SIP, Asterisk

> Individual은 **초과 과금이 아니라 그냥 멈춥니다.** 시연 달에는 Business(₩99,000 / 1,000분)로 올립니다.

---

## 7. 보안과 개인정보

```mermaid
flowchart TB
    R1["1. 1회용 토큰<br>Parameter로 심고 start에서 대조"]
    R2["2. callId 대조<br>우리가 만든 통화인가"]
    R3["3. IP 허용목록<br>ClawOps 발신 대역"]
    WS["스트림 서버<br>공개 WSS 엔드포인트"]

    R1 --> WS
    R2 --> WS
    R3 --> WS
```

ClawOps는 스트림 소켓에 서명을 걸지 않습니다. 그래서 **3중으로 막습니다.** 토큰은 1회용이며, 재사용되면 같은 통화에 두 스트림이 붙습니다.

| 대상 | 정책 |
|---|---|
| 통화 원본 오디오 | S3 라이프사이클로 **30일 후 삭제**. 저장소에는 절대 안 들어감 (`.gitignore`) |
| 전사문 · 지표 | 보존 — 추이 분석의 근거 |
| 발신 | `elders.consent_at`이 없으면 **발신하지 않음** |
| 비밀 | `google-services.json`, `.env` 커밋 금지 |

---

## 8. 지금 어디까지 왔나

| | 상태 |
|---|---|
| 설계 · 전화 경로 조사 | 완료 (5판 — ClawOps Stream) |
| DB 스키마 | 완료 — 컨테이너 검증. `trigger_type` 변경 대기 |
| `VadSegmenter` · `MetricsCalculator` | 완료 — 8kHz 결함 수정, 재현성 테스트 통과 |
| `StreamingVad` · `CallSession` | 완료 — 전화망용 수정 대기 |
| 앱 (늘봄) | 완료 — 대기 화면 재작성 대기 |
| **전화망 통화** | **계획 완료, 구현 대기** (11개 태스크) |
| `ClovaResponder` | 선결 조건 2건 기록됨 |
| 스케줄러 · S3 · 알림 | 예정 |
