# 전화망 통화 — 설계 문서

- **팀명:** 공명
- **작성일:** 2026-09-15
- **범위:** 어르신 전화번호로 AI가 전화를 걸어 대화하는 경로 전체
- **상태:** 설계 확정, 구현 착수 전

> 이 문서는 `2026-09-13-app-call-design.md`(앱 채널)를 **대체**합니다. 그 문서의 전제 — 어르신이 앱 마이크에 대고 말한다 — 가 틀렸습니다. 앱 버튼은 **전화를 걸어 달라는 신호**이고, 대화는 전화망에서 일어납니다.
>
> 상위 설계 `2026-09-07-ansimcare-design.md`의 3.0(두 채널) / 3.1-a(앱 채널)도 이 문서로 대체됩니다. **채널은 하나입니다.**

---

## 1. 무엇이 바뀌었나 — ClawOps 답변이 Asterisk를 지웠다

2026-09-15 ClawOps 회신에서 나온 사실입니다.

| 물은 것 | 답 | 우리에게 주는 결과 |
|---|---|---|
| 녹음이 화자별로 분리되나 | **아니오.** 섞인 모노 WAV 8kHz | 녹음은 보관용으로만 |
| 전사문에 화자 라벨이 있나 | 있으나 `speaker_0`/`speaker_1` **익명**, 역할 대응 보장 없음 | ClawOps 전사문을 쓰지 않는다 |
| **통화 중 오디오를 외부로 받을 수 있나** | **`<Connect><Stream>`. `track`은 `inbound` 하나 — 상대방(어르신) 트랙만 온다. 우리가 보낸 오디오가 통화에 재생된다** | **이게 화자 분리다** |

우리가 Asterisk를 도입하려던 **유일한 이유**가 화자 분리였습니다. 위험 점수 100점 중 60점(발화 비율 35 + 응답 지연 25)이 "어르신이 언제 말했는가"와 "AI가 언제 말했는가"를 따로 아는 데 걸려 있기 때문입니다.

`<Stream track="inbound">`이 그걸 그대로 줍니다.

```
받는 트랙   = 어르신 음성만         → 발화 비율 · 침묵 비율 · 발화 턴 수
보내는 오디오 = 우리가 만든 AI 음성  → AI 발화 구간을 우리가 안다 → 응답 지연
어르신 트랙만 STT                   → 전사문에 화자 문제가 없다 → 부정 표현 빈도
```

**결론: Asterisk 불필요. SIP 직접연결 애드온(₩99,000/월) 불필요.** 스트림 안쪽은 전부 우리 서버이므로 CLOVA도 그대로 씁니다.

### 지워지는 것

- Asterisk · chan_pjsip · ARI · MixMonitor · AudioSocket
- SIP 트렁크 · SBC · NAT 설정 · SRTP
- `docs/telephony-implementation.md` 4판의 "ClawOps + Asterisk" 결정

---

## 2. 통화 한 통

```
① 트리거     앱 버튼(requested) 또는 스케줄러 09:00(scheduled)
                  │
② 발신       POST /calls  { To, From: 070…, Url: https://우리/voiceml }
                  │
③ 어르신이 받음 → ClawOps가 ②의 Url로 POST (CallId, From, To, CallStatus…)
                  │
④ 우리가 VoiceML 응답
      <Response>
        <Connect action="https://우리/stream-ended">
          <Stream url="wss://우리/v1/stream">
            <Parameter name="token" value="<1회용 난수>"/>
          </Stream>
        </Connect>
      </Response>
                  │
⑤ ClawOps가 wss://우리/v1/stream 에 접속
      connected → start → media × N ⇄ media/mark → stop
                  │
⑥ 스트림 종료 → ④의 action으로 POST (StreamEvent, StreamCloseCode…)
                  │
⑦ 통화 후: 어르신 트랙 wav → 배치 VAD → MetricsCalculator → DB
```

②~④가 **트리거**, ⑤가 **대화**, ⑥~⑦이 **분석**입니다. 셋은 서로 다른 시점에 일어나고 실패 양상도 다릅니다.

---

## 3. 핵심 결정 — 시계를 하나로 쓴다

이 설계에서 가장 중요한 판단입니다. 지표 60점이 여기 걸려 있습니다.

### 3.1 문제: "우리가 보냈으니 안다"는 틀리다

1장에서 *"AI 발화 시각은 우리가 안다"*고 했는데, 정확히는 **틀립니다.**

> *"Outbound audio accepts flexible timing — the platform normalizes transmission to 20ms intervals."*

우리는 2초짜리 응답을 20ms 안에 다 밀어 넣을 수 있습니다. 플랫폼이 그걸 버퍼에 담아 2초에 걸쳐 재생합니다. **보낸 시각과 들린 시각이 다릅니다.** 여기서 응답 지연을 재면 늘 짧게 나오고, 그 오차는 응답이 길수록 커집니다.

### 3.2 해답: `mark`로 재생 완료를 받고, `media.timestamp`를 시계로 쓴다

`mark` 이벤트는 *"앞서 보낸 오디오의 재생이 끝났다"*는 확인입니다. AI 음성 앞뒤로 mark를 하나씩 걸면 **재생 구간이 잡힙니다.**

```
우리 → ClawOps : mark "turn3-begin"
우리 → ClawOps : media × N          (AI 음성)
우리 → ClawOps : mark "turn3-end"

ClawOps → 우리 : mark "turn3-begin"   ← 재생 시작
ClawOps → 우리 : mark "turn3-end"     ← 재생 종료
```

남은 문제는 **그 mark가 몇 시 몇 분인가**입니다. mark 이벤트에는 타임스탬프가 없습니다. 벽시계(`time.monotonic()`)를 쓰면 네트워크 지연이 섞여 들어가 **재현성이 깨집니다** — 같은 통화를 다시 분석해도 같은 점수가 나와야 한다는 게 이 프로젝트의 간판입니다.

그래서 이렇게 합니다.

> **mark가 도착한 시각 = 그 직전에 받은 inbound `media.timestamp`**

inbound media는 20ms마다 꼬박꼬박 오고 `timestamp`(스트림 시작 후 ms)를 달고 옵니다. 이게 **어르신 트랙과 AI 트랙이 공유하는 유일한 시계**입니다. 해상도는 20ms — 우리가 재려는 응답 지연(초 단위)에 비해 충분합니다.

| 값 | 어디서 |
|---|---|
| 어르신 발화 구간 | 통화 후 wav에 배치 `segment_audio` |
| AI 발화 구간 | mark 쌍 → 직전 `media.timestamp` |
| 통화 길이 | 마지막 `media.timestamp` |

**셋 다 같은 시계 위에 있고, 셋 다 저장된 값에서 나옵니다.** 다시 돌려도 같은 값이 나옵니다.

> ⚠️ `duration_ms`는 두 개입니다. **스트림 길이**(지표 계산용, 위 시계)와 **통화 길이**(ClawOps 과금·기록용)는 다릅니다. 어르신이 받고 나서 Connect가 붙기까지 틈이 있습니다. 지표에는 **스트림 길이**를 씁니다.

### 3.3 유실 패킷에 침묵을 채운다

받은 media payload를 그냥 이어 붙이면 안 됩니다. 몇 프레임이 빠지면 **오디오가 그만큼 짧아지고, 그 뒤의 모든 발화 구간이 앞으로 당겨집니다.** 조용히 틀립니다.

```python
gap_ms = timestamp - expected_next_timestamp
if gap_ms > 0:
    buffer.extend(silence(gap_ms))   # 타임스탬프가 진실이다
```

`timestamp`를 기준으로 wav를 만들면 파일의 샘플 위치가 곧 스트림 시각이 됩니다. 배치 VAD 결과를 그대로 mark와 비교할 수 있습니다.

### 3.4 에코 — 어르신 트랙에 섞여 든 AI 음성

`track="inbound"`가 어르신 쪽이라도, 어르신 수화기에서 AI 음성이 새어 돌아올 수 있습니다(스피커폰이면 특히). 배치 VAD가 그걸 어르신 발화로 세면 **발화 비율 35점이 부풀려집니다.**

우리는 AI 재생 구간 `[mark_begin, mark_end]`를 알고 있으므로 **어르신 발화 구간에서 그 구간을 잘라냅니다.**

```
어르신 구간   ────────▓▓▓▓────────
AI 재생 구간          ▓▓▓▓▓▓
남는 것       ────────      ──────
```

| 잘라낸 비율 | 판정 |
|---|---|
| 작다 | 정상. 에코가 조금 섞였을 뿐 |
| 크다 | `degraded` 표시 — 에코가 심하거나 어르신이 AI 말을 끊고 들어왔다 |

**이 방식은 barge-in을 에코와 구별하지 못합니다.** 4주 범위에서는 지표를 부풀리는 쪽(에코)이 비우는 쪽보다 위험하므로 자르는 쪽을 택합니다. `degraded` 플래그로 정직하게 표시하는 것은 이전 두 주제에서 가져온 관례입니다(`docs/retrospective-previous-topics.md`).

### 3.5 스트리밍 VAD는 그대로 남는다

`2026-09-13` 문서 2장의 논증 — *"스트리밍 VAD는 턴만 잡고, 지표는 통화 후 배치로"* — 는 **전부 그대로 유효합니다.** 프레임 출처가 앱 소켓에서 ClawOps 스트림으로 바뀌었을 뿐입니다.

전사문 재현성 구멍(그 문서 2장 ⚠️)도 그대로 남아 있습니다. **지표에 쓰는 전사문은 통화 후 wav를 배치 구간으로 다시 전사한 것**이어야 합니다.

---

## 4. 컴포넌트

```
app/media/
├─ ulaw.py            μ-law ↔ float32             ← 신규. 순수
├─ streaming_vad.py   StreamingVad                ← 그대로
├─ responder.py       Responder + CannedResponder ← 그대로
├─ session.py         CallSession                 ← AI 발화 구간 기록 추가
├─ stream_server.py   ClawOps Stream 어댑터       ← ws_server.py 재작성
└─ telephony.py       Telephony 규약              ← 신규
```

| 컴포넌트 | 책임 | 독립 테스트 |
|---|---|---|
| `ulaw` | `decode(bytes) -> float32`, `encode(float32) -> bytes` | 왕복 오차 · 경계값 |
| `StreamingVad` | 프레임 → 발화 종료 | 합성 오디오 (기존 6개) |
| `CallSession` | VAD 구동 · 응답 요청 · **AI 구간 기록** · 타임라인 복원 | 가짜 Responder |
| `stream_server` | ClawOps JSON ↔ 세션 | 이벤트 시퀀스 재생 |
| `Telephony` | 발신 요청 | `FakeTelephony` |

**`CallSession`이 살아남습니다.** 전송 수단을 모르게 만들어 둔 판단이 여기서 값을 합니다 — 앱 소켓용으로 쓴 코드가 전화망에서 그대로 돕니다. 바뀌는 것은 두 가지뿐입니다.

- `push_audio(pcm, timestamp_ms)` — 시계를 밖에서 받는다 (3.3)
- `Outgoing`에 `MarkMessage(name)` 추가, `ai_turns` 누적 (3.2)

### 4.1 μ-law

표준 라이브러리 `audioop`은 **Python 3.13에서 제거**됐습니다. 256엔트리 LUT로 직접 짭니다 — 디코드는 표 한 번, 인코드는 표준 알고리즘입니다. 순수 함수라 테스트가 쉽고, 한 번 맞으면 다시 안 봅니다.

| | 앱 채널(폐기) | 전화망 |
|---|---|---|
| 코덱 | PCM16 LE | **G.711 μ-law** |
| 샘플레이트 | 16000 | **8000** |
| 20ms 프레임 | 640 B | **160 B** |

8kHz는 이미 겪은 문제입니다. `VadSegmenter`가 전화 음질에서 조용한 목소리를 놓치던 결함을 찾아 고쳤고(`_NOISE_PEAK_CAP`), `tests/test_vad_telephony.py`가 그걸 붙잡고 있습니다. **그 작업이 여기서 값을 합니다.**

### 4.2 Telephony 규약

```python
class Telephony(Protocol):
    def place_call(self, *, to: str, answer_url: str, token: str) -> str:
        """발신을 요청하고 사업자 측 통화 식별자를 돌려준다."""
```

`Responder`와 같은 패턴입니다. `FakeTelephony`로 트리거 API 전체를 ClawOps 계정 없이 테스트합니다 — **계정 신청이 끝나기 전에 구현을 끝낼 수 있습니다.**

---

## 5. 트리거 API

```
POST /v1/calls/request     { "elder_id": 12 }

202  { "call_id": 481, "status": "requested" }
409  { "call_id": 480, "status": "in_progress" }   ← 이미 통화 중
404                                                 ← 없는 어르신
```

**409에 진행 중인 `call_id`를 실어 보냅니다.** 어르신이 버튼을 두 번 누르는 것은 오류가 아니라 정상입니다 — 전화가 안 오는 것 같아서 다시 누른 겁니다. 앱은 409를 받으면 에러를 띄우는 게 아니라 **그 통화의 대기 화면으로 갑니다.**

앱 화면(`calling_screen.dart`)은 **"곧 전화가 갑니다"** 한 장입니다. 마이크 권한도, WebSocket도, 오디오 재생도 없습니다.

```
┌─────────────────┐
│                 │
│   곧 전화가     │
│   갑니다        │
│                 │
│   잠시만        │
│   기다려 주세요 │
│                 │
└─────────────────┘
```

스케줄러의 정기 통화도 **같은 내부 경로**를 씁니다. `trigger` 값만 다릅니다.

---

## 6. 스키마 변경

```sql
ALTER TABLE calls DROP CONSTRAINT calls_app_has_no_provider_sid;
ALTER TABLE calls DROP CONSTRAINT calls_app_cannot_be_no_answer;
ALTER TABLE calls DROP COLUMN channel;

-- 채널은 하나(전화망)뿐이다. 이제 구분해야 하는 것은 "누가 시작했나"다.
ALTER TABLE calls ADD COLUMN trigger TEXT NOT NULL DEFAULT 'scheduled'
    CHECK (trigger IN ('scheduled', 'requested'));
```

`channel`을 지우는 이유는 **값이 하나뿐인 컬럼이기 때문**입니다. 남겨 두면 다음 사람이 `'app'`이 무엇이었는지 찾다가 폐기된 설계 문서에 도달합니다.

`calls_app_cannot_be_no_answer`도 지웁니다. **어르신이 버튼을 누르고 전화를 안 받는 일은 실제로 일어납니다** — 이제 요청 통화도 진짜 전화망을 탑니다.

### 미응답 지표는 `scheduled`만 센다

```python
# 요청 통화의 미응답은 "버튼을 누르고 전화기를 못 찾았다"일 뿐이다.
# 위험 신호로 세면 오히려 활발한 어르신이 감점된다.
no_answer_history = count(trigger='scheduled' AND status='no_answer', last=7)
```

`call_transcripts.speaker`는 이미 `CHECK (speaker IN ('ai','elder'))`입니다. **3장의 시계가 이 두 값을 채울 근거를 줍니다** — 익명 라벨 대응 문제가 없습니다.

---

## 7. 인증

> *"Stream WebSocket itself has no X-Signature authentication applied by ClawOps."*

`wss://우리/v1/stream`은 **공개 엔드포인트**입니다. 아무나 접속해 가짜 통화를 만들 수 있습니다.

| 층 | 방법 |
|---|---|
| 1 | `<Parameter name="token" value="<1회용 난수>"/>` — 발신할 때 발급해 DB에 저장, `start` 이벤트에서 대조 |
| 2 | `start.callId`가 우리가 만든 통화의 `provider_call_sid`와 일치하는지 |
| 3 | ClawOps 발신 IP 허용목록 (`/docs/network`) |

토큰은 **1회용**입니다. 한 번 쓰면 무효화합니다 — 재사용되면 같은 통화에 두 스트림이 붙습니다.

`Url` 웹훅(③)도 공개입니다. 이쪽에 X-Signature가 있는지는 **미확인 항목**입니다.

---

## 8. 에러 처리

| 상황 | 처리 |
|---|---|
| 토큰 불일치 | 소켓 즉시 종료. 통화 기록 남기지 않음 |
| `media` 유실 | 침묵 삽입 (3.3). 통화는 계속 |
| `mark`가 안 돌아옴 | 그 턴의 AI 구간을 모름 → 그 턴만 응답 지연에서 제외, `degraded` |
| 어르신이 먼저 끊음 | `stop` 이벤트. **누적분을 wav로 저장** |
| 소켓이 그냥 끊김 | `action` 웹훅의 `StreamCloseCode`로 사후 확인. 누적분 저장 |
| `Responder` 예외 | 로그만. **통화 유지** — 응답 하나 실패했다고 끊으면 어르신은 영문을 모른다 |
| 미응답 | `status='no_answer'`. Stream이 아예 안 열림 |

마지막 둘이 상위 설계 8장(부분 성공 허용)과 같은 원칙입니다.

**`<Connect action=...>`을 반드시 넣습니다.** 없으면 스트림이 끊기는 순간 통화가 즉시 종료되고, 우리 서버 버그가 곧바로 어르신의 전화 끊김이 됩니다. `action`이 있으면 마무리 인사(`<Say>`)를 하고 끊을 수 있습니다.

---

## 9. 테스트

| 대상 | 무엇을 고정하나 |
|---|---|
| `ulaw` 왕복 | 인코드→디코드 오차가 μ-law 양자화 한계 안 |
| `ulaw` 경계 | 0, ±최대, 클리핑 |
| **타임스탬프 갭** | 프레임이 빠지면 침묵이 채워지고 **뒤 구간이 안 당겨진다** |
| **mark 시계** | mark 직전 media.timestamp가 AI 구간 경계가 된다 |
| **에코 클리핑** | AI 재생 구간과 겹친 어르신 발화가 잘린다 |
| **재현성** | 같은 이벤트 시퀀스 100회 → 지표 편차 0 |
| 이벤트 순서 | connected→start→media→stop 재생 |
| 토큰 불일치 | 소켓 거부 |
| `409` | 통화 중 재요청이 기존 call_id를 돌려준다 |

**타임스탬프 갭과 재현성이 무게중심입니다.** 둘 다 조용히 틀리는 종류의 버그고, 그게 이 프로젝트가 가장 싫어하는 것입니다.

기존 61개 중 `test_ws_server.py` 7개는 프로토콜이 바뀌므로 다시 씁니다. 나머지 54개는 손대지 않습니다.

---

## 10. 비용

**채택: ClawOps Individual (₩19,000 / 월 100분).**

| 항목 | 월 |
|---|---|
| **ClawOps Individual (100분 포함)** | **₩19,000** |
| EC2 (미디어 서버) | 약 ₩18,000 |
| CLOVA Speech / Voice / Studio | 사용량 — NCP 신청 후 확정 |
| **합** | **약 ₩37,000 + CLOVA** |

쓰지 않는 것:

| 항목 | 왜 안 쓰나 |
|---|---|
| SIP 직접연결 애드온 ₩99,000 | Asterisk를 안 쓴다 (1장) |
| 전사 ₩10/분 | 어르신 트랙을 우리가 전사한다 — 익명 화자 라벨이 쓸모없다 |
| AI 에이전트 ₩30–140/분 | 스트림 안쪽이 전부 우리 서버다 |
| AWS Chime SDK SIP | 한국 번호는 **수신·토익프리·사업자 증명** 조건. 우리는 **발신·070·개인 명의**다 |

### 왜 Business가 아닌가

**이 설계는 실통화가 거의 필요 없습니다.** `FakeTelephony`와 이벤트 시퀀스 재생으로 대부분이 검증됩니다.

| 검증 대상 | 실통화 |
|---|---|
| μ-law · 타임스탬프 갭 · mark 시계 · 에코 클리핑 · 지표 · 409 | ❌ |
| 스트림이 실제로 붙나 · 실제 전화 음질에서 VAD가 도나 · 시연 | ✅ |

```
스트림 연동 검증   짧은 통화 20회 × 1분  =  20분
음질·VAD 실측      2~3분 × 15회         =  40분
시연 리허설 + 본선  5분 × 8회            =  40분
                                        ─────
                                        약 100분
```

> ⚠️ **딱 경계입니다. 그리고 Individual은 초과 과금이 아니라 그냥 멈춥니다.**
>
> *"Individual has no overage fees; upgrade to Business if needed."*
>
> 돈 문제가 아니라 **시연 당일 발신이 막힐 위험**입니다. 잔여 분수를 주단위로 확인하고, 시연 달에는 Business(₩99,000 / 1,000분)로 올립니다.

### 단계

1. **지금** — 가입 없이. 실통화 없이 갈 수 있는 데까지
2. **연동 직전** — Trial(무료 10분)로 스트림이 붙고 μ-law가 문서대로 오는지만 확인. 3일 제한이 있으므로 준비된 뒤 시작
3. **개발·실측** — Individual
4. **시연 달** — 잔여 분수를 보고 Business

3일 무료체험은 SIP만 막혀 있고 Stream 제한은 명시돼 있지 않습니다 — **미확인 항목.**

---

## 11. 범위 밖 / 미확인

**다음 단계**

- `ClovaResponder` — 선결 조건 2건이 `2026-09-13` 문서에 기록돼 있음 (동기 `respond()`, 전사문 재현성)
- barge-in — `{"event":"clear"}`가 이미 있음. 에코 클리핑(3.4)과 충돌하므로 같이 설계해야 함
- 스케줄러 (매일 09:00)
- S3 업로드 + 30일 삭제 (설계 3.6)

**확인해야 할 것**

| 항목 | 왜 |
|---|---|
| `Url` 웹훅에 X-Signature가 있나 | 공개 엔드포인트 인증 |
| `<Parameter>` 값이 `start` 이벤트 어느 필드로 오나 | 토큰 대조 위치 |
| 무료체험에서 Stream을 쓸 수 있나 | 계정 없이 검증 가능한지 |
| **월 중간 Individual → Business 업그레이드가 즉시 반영되나** | **시연 전날 잔여 20분일 때 살 길이 있는지** |
| 동시 통화 기본 수 | 업그레이드 ₩100,000/월 필요 여부 |
| ClawOps 발신 IP 대역 | 허용목록 |
