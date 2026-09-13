# 늘봄 — 독거노인 AI 안부 전화

> AI가 매일 정해진 시각에 독거 어르신께 **전화를 걸어** 안부를 묻고, 통화에서 **정서 위험 신호를 정량 측정**해 보호자에게 알립니다.

**팀 공명** · 캡스톤 + 창업경진대회 · 4명 / 4주

---

## 무엇이 다른가 — 위험 점수를 AI가 지어내지 않습니다

감정 점수를 LLM이 산출하면 같은 대화에 오늘 62점, 내일 71점이 나옵니다. **추이 그래프가 노이즈가 되고, 보호자는 몇 번 겪은 뒤 알림을 무시하게 됩니다.**

그래서 점수는 **음성에서 직접 잰 지표의 가중합**으로 계산하고, LLM은 그 숫자를 사람 말로 옮기는 역할만 합니다.

```
통화 오디오
     ↓
서버: VAD로 발화/침묵 구간 확정 → 지표 계산   (결정론적)
      STT 전사 → 부정 표현 사전 매칭          (결정론적)
      → risk_score, risk_level 확정
     ↓ (전사문 + 이미 확정된 지표만 전달)
LLM: 통화 요약 + 보호자용 설명 문장            (숫자 산출에 관여하지 않음)
```

| 지표 | 계산 | 출처 |
|---|---|---|
| 발화 비율 | 어르신 발화 시간 / 통화 시간 | VAD |
| 평균 응답 지연 | AI 발화 종료 → 어르신 발화 시작 | VAD |
| 침묵 비율 | 무음 구간 합 / 통화 시간 | VAD |
| 발화 턴 수 | 어르신 발화 구간 개수 | VAD |
| 부정 표현 빈도 | 사전 매칭 (아프다/힘들다/외롭다…) | 전사문 |
| 미응답 이력 | 최근 7회 중 미응답 횟수 | 통화 기록 |

**절대값보다 변화가 중요합니다.** 원래 말수가 적은 분과 갑자기 말수가 준 분은 다릅니다. 판정은 **개인 기준선 대비 변화**로 합니다.

```python
def test_score_is_identical_across_repeated_runs():
    scores = {assess_risk(metrics, ...).risk_score for _ in range(100)}
    assert len(scores) == 1
```

같은 입력 100회 → **점수 편차 0.** 이 테스트가 위 주장을 코드로 증명합니다.

---

## 어르신에게 닿는 길은 둘입니다

| | **전화망** | **앱** |
|---|---|---|
| 누가 시작 | AI가 건다 (매일 09시) | 어르신이 누른다 (아무 때나) |
| 어르신이 할 일 | 전화를 받는다 | 앱에서 "AI 친구"를 누른다 |
| 오디오 | G.711 μ-law 8kHz | 16kHz PCM |
| 경로 | ClawOps 070 + Asterisk | WebSocket → 서버 |

**앱만 두면** 말수가 줄어든 어르신은 앱을 누르지도 않아 *가장 위험한 분이 가장 적게 기록됩니다.* **전화망만 두면** 어르신이 외로울 때 먼저 손 내밀 방법이 없습니다.

두 채널은 분석 파이프라인에서 하나로 합류합니다 — VAD 아래로는 채널과 무관합니다.

---

## 구조

```
.
├─ app/
│  ├─ analysis/         VAD 분절 · 결정론적 위험도 계산 (순수 함수)
│  └─ media/            통화 중 오디오 처리 (구현 중)
├─ tests/               34개 통과
├─ db/                  schema.sql (7개 테이블, 컨테이너 검증) · erd.md
├─ client/              Flutter 앱 늘봄 — 어르신용 / 보호자용
├─ docs/
│  ├─ superpowers/specs/  설계 문서
│  ├─ superpowers/plans/  구현 계획
│  └─ telephony-*.md      전화 경로 조사·확정 기록
└─ archive/             중단한 이전 주제 2개 (테스트 통과 상태로 보존)
```

### 기술 스택

| 영역 | 채택 | 근거 |
|---|---|---|
| 전화망 | ClawOps(070 번호·트렁크) + Asterisk(통화 제어·미디어) | 국내 070으로 걸면서 RTP를 직접 받음 |
| 앱 채널 | WebSocket PCM 16kHz | SIP·통화료 불필요, 음질이 더 좋음 |
| STT / TTS / LLM | CLOVA Speech / Voice / Studio (HyperCLOVA X) | 한국어 특화. 계정·과금 일원화 |
| 백엔드 | Python · FastAPI · numpy | 분석 코어는 외부 의존 없는 순수 함수 |
| DB | PostgreSQL 16 | 벡터 검색 불필요 |
| 앱 | Flutter 3.35 | 어르신용 / 보호자용을 역할로 분기 |

---

## 실행

```bash
# 백엔드 분석 코어
python -m pytest

# 앱 (fixture 모드가 기본 — 서버 없이 화면 개발 가능)
cd client && flutter run

# 서버를 붙일 때
flutter run --dart-define=USE_FIXTURES=false \
            --dart-define=API_BASE_URL=https://api.example.com
```

### DB 스키마 검증

```bash
docker run -d --name pg -e POSTGRES_PASSWORD=pw pgvector/pgvector:pg16
docker cp db/schema.sql pg:/schema.sql
docker exec pg psql -U postgres -v ON_ERROR_STOP=1 -f /schema.sql
```

---

## 현재 상태

| | |
|---|---|
| 설계 · 전화 경로 조사 | 완료 |
| DB 스키마 | 완료 — 컨테이너 검증 (테이블 7 · CHECK 65) |
| `VadSegmenter` | 완료 — 8kHz 전화 음질에서 결함 발견·수정 |
| `MetricsCalculator` | 완료 — 재현성 테스트 통과 |
| 앱 프론트 (늘봄) | 완료 — 역할 분기, fixture 모드 |
| **앱 채널 통화** | **구현 중** |
| `Transcriber` · `ReportWriter` · `AlertDispatcher` | 예정 |
| 인프라 프로비저닝 | 예정 |

### 개발 중 알아두면 좋은 것

**한글 입력은 에뮬레이터에서 깨집니다 — 앱 문제가 아닙니다.** Pixel_8a AVD는 `안녕` → `ㅇㅏㄴㄴㅕㅇ`, BlueStacks는 `안녕하세요` → `안녀녕녕하핫하셍세`로 나옵니다. 두 환경 모두 **구글 기본 앱·네이티브 입력 폼에서 똑같이 깨지는 것을 확인**했습니다. 한글 입력 검증은 실기기에서 하세요.

---

## 문서

| 문서 | 내용 |
|---|---|
| `docs/superpowers/specs/2026-09-07-ansimcare-design.md` | 전체 설계 |
| `docs/superpowers/specs/2026-09-13-app-call-design.md` | 앱 채널 통화 설계 |
| `docs/superpowers/plans/` | 구현 계획 |
| `docs/telephony-implementation.md` | 전화 경로 — 4판까지의 조사와 확정 |
| `docs/progress-*.md` | 진행 기록 |
| `db/erd.md` | ERD + 제약·인덱스 근거 |
| `docs/retrospective-previous-topics.md` | 이전 두 주제에서 가져온 것과 교훈 |

---

## 개발 방식

- **계약(JSON)을 먼저 고정하고 fixture로 개발** — 프론트와 백엔드가 서로를 기다리지 않습니다
- **스키마는 실제 컨테이너에 적용해 검증** — 제약 위반 음성 테스트까지 돌립니다
- **순수 함수로 잘라서 TDD** — 분석 코어는 클라우드 없이 로컬에서 전부 테스트됩니다
- **LLM은 숫자를 만들지 않습니다** — 정량 지표는 결정론적으로 계산하고 LLM은 설명만 합니다
