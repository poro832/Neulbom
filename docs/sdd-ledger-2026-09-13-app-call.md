# SDD ledger — plan: docs/superpowers/plans/2026-09-13-app-call-skeleton.md

Spec: docs/superpowers/specs/2026-09-13-app-call-design.md (읽음)
Branch: feat/app-call-skeleton (base 781923c)
Remote: https://github.com/poro832/Nulbom.git

## Setup
- git 저장소가 없어 컨트롤러가 초기화했다 (Task 0 Step 1~3에 해당). .gitignore가
  client/build/의 APK를 막는 것을 dry-run으로 확인한 뒤 187개 파일을 커밋했다.
- Ruling: main이 아닌 feat/app-call-skeleton에서 작업한다 — 스킬이 main 직접 작업을
  금지한다. 틀렸을 때 비용: 없음(브랜치는 언제든 병합·삭제 가능).
- Ruling: Task 0의 Step 1~3(git init/커밋/리모트)은 컨트롤러가 수행했다 — 커밋이
  가능해야 이후 모든 태스크가 돌기 때문. Task 0 dispatch는 Step 4~7(의존성)만 담당한다.
  틀렸을 때 비용: 없음(동일 결과, 순서만 앞당김).

## Pre-flight scan

| 검사 | 결과 |
|---|---|
| Task 1 produces `adaptive_threshold` → Task 2 consumes | 일치 |
| Task 2 produces `StreamingVad` / `SpeechEnded` / `frame_length` → Task 4 consumes | 일치 |
| Task 3 produces `Responder.respond(audio, sample_rate) -> bytes` → Task 4 가짜 구현 | 시그니처 4곳 전부 동일 |
| Task 4 produces `CallSession(call_id, sample_rate, responder, frame_ms=20)` → Task 5 호출 | 인자 순서 일치 (9곳) |
| Task 2가 import하는 `DEFAULT_FRAME_MS` / `DEFAULT_MIN_SPEECH_MS` | vad_segmenter.py에 실존 |
| 각 태스크 자체 정합 (테스트 ↔ 코드 ↔ 파일 목록) | Task 3에서 결함 1건 발견 (아래) |
| Global Constraints 상호 모순 | 없음 |

- 발견: File Structure 표에 `tests/test_responder.py`가 누락. Task 3은 이 파일을 만든다.
  Ruling: 표에 추가했다 — 표가 곧 파일 목록이라 빠지면 실행자가 "계획에 없는 파일"로
  판단할 수 있다. 틀렸을 때 비용: 없음(문서만 수정).

## Tasks
- Task 0: complete (commits 5e46561..f2c8623, review clean) — 34 passed
- Task 1: complete (commits f2c8623..02f8a5b, review clean) — 순수 이름 변경, 34 passed
- Task 2: Ruling: "스트림 종료 시 열린 턴 미방출"(Important) — 결함 아님으로 판정.
  StreamingVad의 계약은 "통화 중 언제 답할지"이고 스트림이 끝나면 답할 상대가 없다.
  마지막 발화는 CallSession이 누적한 wav에 남아 통화 후 배치 VAD가 지표로 집계하므로
  유실이 아니다. 지금 flush()를 넣으면 호출자 없는 API가 된다.
  틀렸을 때 비용: barge-in/ClovaResponder 단계에서 우아한 종료가 필요해지면 flush()를
  추가해야 한다. 호출자 1곳(CallSession.finish) 수정으로 끝나는 크기.
- Task 2: minor (deferred): _close_turn의 assert는 -O에서 제거된다. 제어 흐름상 이미
  보장되는 중복 방어라 무해하나, 라이브러리 코드의 불변식에는 부적절한 도구.
- Task 2: minor (deferred): push()가 프레임 길이를 검증하지 않는다. 유일한 호출자인
  CallSession이 정확히 잘라 주므로 현재는 도달 불가.
- Task 2: complete (commits 02f8a5b..5dd31f9, review clean, 2 minor deferred) — 42 passed
- Task 3: complete (commits 5dd31f9..699bea8, review clean) — 46 passed
- Task 4: complete (commits 699bea8..d1345c6, review clean) — 53 passed.
  리뷰가 확인한 것: 137바이트 청크가 640 프레임의 비약수라 경계 넘김을 실제로 검증함(공허하지 않음),
  턴 슬라이스가 프레임 경계에 정확히 떨어짐(off-by-one 없음), Responder 예외가 call_id와 함께 로깅됨.
- Task 5: Ruling: minor("'"end"' in text" 부분 문자열 검사)를 수정 루프에 포함했다 —
  프로토콜에 stop_playback을 이미 예약해 뒀으므로 제어 메시지 어휘가 늘어날 것이 예정돼 있다.
  취약성이 가정이 아니라 일정이고, Important 수정과 같은 디스패치에 묶여 추가 비용이 없다.
  틀렸을 때 비용: 없음(엄격히 더 견고해짐, 회귀 테스트 1개 추가).
- Task 5: fix round 1/5 (2 addressed, 0 open — recordings/ gitignore 누락, end 부분문자열
  오탐; commits 43760ed..8b654e9)
- Task 5: complete (commits d1345c6..8b654e9, review clean) — 57 passed

## Final review rulings
- Ruling: ws_server.py:70 무방비 json.loads(Important) — 지금 고친다. 인증 없이 도달 가능한
  크래시이고 3줄이다. 같은 브랜치가 _is_end는 방어해 놓고 형제 호출을 방치한 불일치이기도 하다.
  틀렸을 때 비용: 없음.
- Ruling: respond()를 async로 바꾸는 건(Important) 이 브랜치에서 하지 않는다 — CallSession까지
  async로 번지면 "소켓 없이 동기로 테스트된다"는 설계상 이점이 사라지는데, 아직 그 모양을 검증할
  async 소비자가 없다. ClovaResponder와 함께 하면 실제 호출자로 모양이 증명된다. 스펙에 선결
  조건으로 못박았다.
  틀렸을 때 비용: 나중 변경 범위가 Protocol + CallSession + ws_server + 테스트 7개. 지금 하면
  더 쌌다는 리뷰어 지적은 타당하다. 다만 검증 없는 async 배관보다 낫다고 판단했다.
- Ruling: 전사문 경로 재현성 누수(Important) — 이 브랜치에선 CannedResponder가 전사문을
  만들지 않아 현존 결함이 아니다. 스펙 §2를 고쳐 ClovaResponder의 선결 조건으로 기록했다.
  틀렸을 때 비용: ClovaResponder 착수 시 배치 재전사를 설계에 넣어야 한다.
- Ruling: 마지막 턴 미방출에 대한 내 앞선 판단을 리뷰어 지적대로 수정한다 — "wav로 지표에
  도달하므로 유실 아님"은 음향 지표에만 참이고 전사문에는 거짓이다. respond()가 호출되지
  않으므로 그 턴의 전사문은 생기지 않는다. ClovaResponder 선결 조건으로 격상.
- Ruling: async 미적용, O(n²) pending 슬라이스, finally의 동기 wav 쓰기, 마이크 스트림에
  섞인 AI 음성(설계 이슈) — 전부 다음 단계로. 골격 병합을 막지 않는다.
- Final fix wave: 4 addressed, 0 open (commits 8b654e9..4482e57). 재리뷰가 Finding 3 산술을
  검증: 11025Hz에서 옛 공식이 프레임 3에서 1샘플(2바이트) 어긋나던 것을 제거. 16kHz에선 비트 동일.
- Final review clean — 61 passed.
