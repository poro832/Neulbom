"""테스트 전역 환경 설정.

`build_server`는 `transcriber=None`이면 `transcriber_from_env()`로 내려가고
(`app/main.py`), 이 파일이 없으면 어떤 테스트도 `BATCH_TRANSCRIPTION`이나
`CLOVA_SPEECH_*`를 고정하지 않는다. 시연 2주 전부터 그 값을 켜 둔 셸에서
(설계 7장이 그렇게 지시한다) `pytest tests/`를 돌리면, `transcriber=None`으로
만든 서버가 조용히 실제 `ClovaLongSpeech`를 조립한다 — 테스트 음성이 진짜
CLOVA 엔드포인트로 진짜 키와 함께 나가 과금되고, 직렬 큐가 요청당 최대 600초를
잡는다. `tests/test_server_wiring.py`에서 실제로 이렇게 재현됐다.

`tests/test_main_wiring.py`의 관례("테스트끼리 환경이 새지 않게 관련 변수를
전부 지우고 시작한다")를 따른다. `transcriber_from_env`가 실제로 읽는 값은
이 셋뿐이다(app/main.py) — `BATCH_TRANSCRIPTION`이 꺼져 있으면 함수가 그
자리에서 None을 반환하고 CLOVA 키는 아예 보지 않으므로, 이 셋만 지워도
"진짜 요청이 나간다"는 위험은 완전히 없어진다. 그래서 CLOVA_STUDIO_*나
CLOVA_VOICE_*까지 넓히지 않았다 — 그것들은 responder_from_env() 쪽 값이고,
이 저장소의 조립 테스트는 responder_factory를 항상 명시적으로 주입해
responder_from_env()를 부르지 않는다.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_ambient_batch_transcription(monkeypatch):
    monkeypatch.delenv("BATCH_TRANSCRIPTION", raising=False)
    monkeypatch.delenv("CLOVA_SPEECH_INVOKE_URL", raising=False)
    monkeypatch.delenv("CLOVA_SPEECH_SECRET", raising=False)
    # 켜 둔 셸에서 pytest를 돌리면 테스트 녹음이 진짜 버킷에 올라간다.
    # BATCH_TRANSCRIPTION과 같은 종류의 구멍이다.
    monkeypatch.delenv("RECORDINGS_BUCKET", raising=False)
