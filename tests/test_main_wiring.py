"""조립 지점이 환경에서 응답기를 만드는 규칙 (app/main.py).

키가 없어도 서버는 떠야 하고, 반쯤 설정된 상태로는 절대 대화를 시작하면
안 된다 — 그게 가장 나쁜 상태다.
"""

import logging

import pytest

from app.main import CLOVA_ENV_KEYS, responder_from_env
from app.media.conversation import ConversationResponder
from app.media.responder import CannedResponder

FULL = {
    "CLOVA_SPEECH_INVOKE_URL": "https://spch.test/external/v1/1/a",
    "CLOVA_SPEECH_SECRET": "s-secret",
    "CLOVA_STUDIO_BASE_URL": "https://studio.test",
    "CLOVA_STUDIO_API_KEY": "studio-key",
    "CLOVA_VOICE_CLIENT_ID": "voice-id",
    "CLOVA_VOICE_CLIENT_SECRET": "voice-secret",
}


def set_env(monkeypatch, values):
    for name in CLOVA_ENV_KEYS:
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_all_six_keys_give_a_real_conversation(monkeypatch):
    set_env(monkeypatch, FULL)

    assert isinstance(responder_from_env(), ConversationResponder)


def test_no_keys_falls_back_to_the_canned_responder(monkeypatch):
    """계정이 없어도 서버는 떠야 한다. 전화 경로 자체는 고정 응답으로 검증된다."""
    set_env(monkeypatch, {})

    assert isinstance(responder_from_env(), CannedResponder)


@pytest.mark.parametrize("missing", sorted(CLOVA_ENV_KEYS))
def test_any_missing_key_falls_back_entirely(monkeypatch, missing):
    """반쯤 설정된 상태가 가장 나쁘다.

    STT만 있고 TTS가 없으면 어르신이 말을 걸고, 우리는 알아듣고 답까지
    만들어 놓고, 아무 소리도 내지 않는다. 어르신은 전화가 끊긴 줄 안다.
    셋이 다 있거나 하나도 안 쓰거나 둘 중 하나여야 한다.
    """
    partial = {k: v for k, v in FULL.items() if k != missing}
    set_env(monkeypatch, partial)

    assert isinstance(responder_from_env(), CannedResponder)


def test_the_missing_keys_are_named_in_the_log(monkeypatch, caplog):
    """무엇이 빠졌는지 안 적으면, 왜 AI가 말을 안 하는지 찾느라 하루를 쓴다."""
    set_env(monkeypatch, {k: v for k, v in FULL.items() if "VOICE" not in k})

    with caplog.at_level(logging.WARNING, logger="app.main"):
        responder_from_env()

    message = " ".join(record.getMessage() for record in caplog.records)
    assert "CLOVA_VOICE_CLIENT_ID" in message
    assert "CLOVA_VOICE_CLIENT_SECRET" in message


def test_the_chosen_voice_and_model_are_logged(monkeypatch, caplog):
    """speaker·speed·모델은 AI 발화 길이를 바꾸고, 그게 지표의 분모를 바꾼다.

    어느 설정이 어느 통화를 만들었는지 로그에 없으면 나중에 점수를 비교할
    때 무엇이 달라졌는지 알 수 없다.
    """
    set_env(monkeypatch, {**FULL, "CLOVA_VOICE_SPEAKER": "napple", "CLOVA_VOICE_SPEED": "2"})

    with caplog.at_level(logging.INFO, logger="app.main"):
        responder_from_env()

    message = " ".join(record.getMessage() for record in caplog.records)
    assert "napple" in message and "HCX-DASH-002" in message


def test_a_bad_speed_value_does_not_stop_the_server(monkeypatch, caplog):
    """숫자가 아닌 값이 들어와도 서버는 떠야 한다 — 기본값으로 간다."""
    set_env(monkeypatch, {**FULL, "CLOVA_VOICE_SPEED": "빠르게"})

    with caplog.at_level(logging.WARNING, logger="app.main"):
        assert isinstance(responder_from_env(), ConversationResponder)
