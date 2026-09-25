"""조립 지점이 환경에서 응답기를 만드는 규칙 (app/main.py).

키가 없어도 서버는 떠야 하고, 반쯤 설정된 상태로는 절대 대화를 시작하면
안 된다 — 그게 가장 나쁜 상태다.
"""

import logging

import pytest

from app.main import (
    CLOVA_ENV_KEYS,
    PROSODY_ENV_KEYS,
    responder_from_env,
    transcriber_from_env,
)
from app.media.clova_long_speech import ClovaLongSpeech
from app.media.conversation import ConversationResponder
from app.media.responder import CannedResponder

# CLOVA 갈래가 온전히 갖춰진 상태. 기본 벤더가 prosody라 여기서는 벤더를
# 명시해야 한다 — 안 그러면 이 파일의 CLOVA 테스트들이 전부 prosody 갈래를
# 검사하게 되고, 이름과 검사 대상이 어긋난 채로 통과한다.
FULL = {
    "TTS_VENDOR": "clova",
    "CLOVA_SPEECH_INVOKE_URL": "https://spch.test/external/v1/1/a",
    "CLOVA_SPEECH_SECRET": "s-secret",
    "CLOVA_STUDIO_BASE_URL": "https://studio.test",
    "CLOVA_STUDIO_API_KEY": "studio-key",
    "CLOVA_VOICE_CLIENT_ID": "voice-id",
    "CLOVA_VOICE_CLIENT_SECRET": "voice-secret",
}


# 테스트끼리 환경이 새지 않게 관련 변수를 전부 지우고 시작한다.
_ALL = CLOVA_ENV_KEYS + PROSODY_ENV_KEYS + (
    "TTS_VENDOR", "CLOVA_VOICE_SPEAKER", "CLOVA_VOICE_SPEED",
    "CLOVA_STUDIO_MODEL", "POLLY_VOICE_ID",
    "PROSODY_EMOTION", "PROSODY_SPEED",
)


def set_env(monkeypatch, values):
    for name in _ALL:
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


# ------------------------------------------------------- TTS 벤더 선택

POLLY_ENV = {
    "CLOVA_SPEECH_INVOKE_URL": "https://spch.test/external/v1/1/a",
    "CLOVA_SPEECH_SECRET": "s-secret",
    "CLOVA_STUDIO_BASE_URL": "https://studio.test",
    "CLOVA_STUDIO_API_KEY": "studio-key",
    "TTS_VENDOR": "polly",
}


def test_polly_needs_no_clova_voice_keys(monkeypatch):
    """개발 기간에는 CLOVA Voice를 켜지 않는다 — 월 정액이 시작된다.

    그 두 키가 없다고 대화를 막으면 개발 내내 비프만 듣게 된다.
    """
    from app.media.polly_voice import PollyVoice

    set_env(monkeypatch, POLLY_ENV)

    responder = responder_from_env()

    assert isinstance(responder, ConversationResponder)
    assert isinstance(responder.voice, PollyVoice)


PROSODY_ENV = {
    "CLOVA_SPEECH_INVOKE_URL": "https://spch.test/external/v1/1/a",
    "CLOVA_SPEECH_SECRET": "s-secret",
    "CLOVA_STUDIO_BASE_URL": "https://studio.test",
    "CLOVA_STUDIO_API_KEY": "studio-key",
    "PROSODY_API_KEY": "prosody-key",
    "PROSODY_VOICE_NAME": "시아",
}


def test_the_default_vendor_is_prosody(monkeypatch):
    """2026-09-25에 Polly 권한이 거부되면서 프레소디로 정했다.

    기본값을 명시적으로 고정해 둔다 — 아무도 TTS_VENDOR를 안 적은 서버가
    어느 목소리로 말하는지가 곧 점수의 전제다.
    """
    from app.media.prosody_voice import ProsodyVoice

    set_env(monkeypatch, PROSODY_ENV)

    assert isinstance(responder_from_env().voice, ProsodyVoice)


def test_prosody_needs_no_clova_voice_keys(monkeypatch):
    """CLOVA Voice는 채우는 순간 월 정액이 시작된다. 그 두 키가 없다고
    대화를 막으면 프레소디로 옮긴 의미가 없다."""
    set_env(monkeypatch, PROSODY_ENV)

    assert isinstance(responder_from_env(), ConversationResponder)


@pytest.mark.parametrize("missing", sorted(PROSODY_ENV_KEYS))
def test_prosody_falls_back_when_either_of_its_keys_is_missing(monkeypatch, missing):
    """목소리 이름도 키만큼 필수다.

    화자가 114명이라 기본값을 박아 둘 수가 없다 — 어느 목소리가 어르신께
    맞는지는 들어 봐야 알고, 기본값이 있으면 아무도 안 듣는다.
    """
    set_env(monkeypatch, {k: v for k, v in PROSODY_ENV.items() if k != missing})

    assert isinstance(responder_from_env(), CannedResponder)


def test_the_missing_prosody_keys_are_named_in_the_log(monkeypatch, caplog):
    set_env(monkeypatch, {k: v for k, v in PROSODY_ENV.items()
                          if not k.startswith("PROSODY")})

    with caplog.at_level(logging.WARNING, logger="app.main"):
        responder_from_env()

    message = " ".join(record.getMessage() for record in caplog.records)
    assert "PROSODY_API_KEY" in message
    assert "PROSODY_VOICE_NAME" in message


def test_the_prosody_voice_and_emotion_are_logged(monkeypatch, caplog):
    """목소리·감정·속도는 AI 발화 길이를 바꾸고, 그게 지표의 분모를 바꾼다."""
    set_env(monkeypatch, {**PROSODY_ENV, "PROSODY_EMOTION": "happy",
                          "PROSODY_SPEED": "0.9"})

    with caplog.at_level(logging.INFO, logger="app.main"):
        responder_from_env()

    message = " ".join(record.getMessage() for record in caplog.records)
    assert "시아" in message and "happy" in message and "0.9" in message


def test_a_bad_prosody_speed_does_not_stop_the_server(monkeypatch, caplog):
    """speed는 배율이라 소수다. 숫자가 아닌 값이 와도 서버는 떠야 한다."""
    set_env(monkeypatch, {**PROSODY_ENV, "PROSODY_SPEED": "천천히"})

    with caplog.at_level(logging.WARNING, logger="app.main"):
        assert isinstance(responder_from_env(), ConversationResponder)


def test_an_unknown_vendor_falls_back_instead_of_guessing(monkeypatch, caplog):
    """오타 하나로 엉뚱한 벤더에 요금이 나가면 안 된다."""
    set_env(monkeypatch, {**POLLY_ENV, "TTS_VENDOR": "pollly"})

    with caplog.at_level(logging.WARNING, logger="app.main"):
        assert isinstance(responder_from_env(), CannedResponder)

    assert any("pollly" in record.getMessage() for record in caplog.records)


def test_the_chosen_tts_vendor_is_logged(monkeypatch, caplog):
    """어느 목소리가 어느 통화를 만들었는지 없으면 점수를 비교할 수 없다."""
    set_env(monkeypatch, POLLY_ENV)

    with caplog.at_level(logging.INFO, logger="app.main"):
        responder_from_env()

    assert any("polly" in record.getMessage().lower() for record in caplog.records)


# --------------------------------------------- 배치 전사 켜고 끄기 (transcriber_from_env)
#
# 점수의 만점을 60에서 80으로 바꾸는 유일한 함수다. 조용히 꺼진 채로 돌면
# 부정 표현 축은 계속 죽어 있고, 그달 모든 점수가 만점 60으로 나오는데
# 데이터는 정확해 보여서 아무도 몇 주 동안 눈치채지 못한다(설계 11장).

LONG_SPEECH_KEYS = {
    "CLOVA_SPEECH_INVOKE_URL": "https://spch.test/external/v1/1/a",
    "CLOVA_SPEECH_SECRET": "s-secret",
}


@pytest.mark.parametrize("value", ["1", "true", "on", "TRUE", "On", " on ", " 1 "])
def test_batch_transcription_turns_on_with_common_truthy_spellings(monkeypatch, value):
    """대소문자·앞뒤 공백 표기가 다르다고 조용히 꺼진 채로 남으면 안 된다."""
    monkeypatch.setenv("BATCH_TRANSCRIPTION", value)
    for name, val in LONG_SPEECH_KEYS.items():
        monkeypatch.setenv(name, val)

    assert isinstance(transcriber_from_env(), ClovaLongSpeech)


@pytest.mark.parametrize("value", [None, "", "off", "yes", "0", "false", "enabled"])
def test_batch_transcription_stays_off_unless_explicitly_turned_on(monkeypatch, value):
    """누군가 systemd 유닛에 오타(yes, enabled)를 쓰면 조용히 꺼진 채로 돌아야
    한다 — "키가 있으면 켠다"처럼 추측하면 만점이 소리 없이 바뀐다(설계 7장).
    """
    if value is None:
        monkeypatch.delenv("BATCH_TRANSCRIPTION", raising=False)
    else:
        monkeypatch.setenv("BATCH_TRANSCRIPTION", value)
    for name, val in LONG_SPEECH_KEYS.items():
        monkeypatch.setenv(name, val)

    assert transcriber_from_env() is None


def test_batch_transcription_on_without_keys_returns_none_and_warns(monkeypatch, caplog):
    """켰는데 키가 없으면 조용히 꺼진 채로 돈다 — 부정 표현 축은 계속
    죽어 있고, 유일한 신호가 이 경고 로그다.
    """
    monkeypatch.setenv("BATCH_TRANSCRIPTION", "on")
    monkeypatch.delenv("CLOVA_SPEECH_INVOKE_URL", raising=False)
    monkeypatch.delenv("CLOVA_SPEECH_SECRET", raising=False)

    with caplog.at_level(logging.WARNING, logger="app.main"):
        result = transcriber_from_env()

    assert result is None
    message = " ".join(record.getMessage() for record in caplog.records)
    assert "BATCH_TRANSCRIPTION" in message


def test_batch_transcription_on_with_keys_returns_the_adapter_and_logs_the_score_change(
    monkeypatch, caplog
):
    """만점이 60에서 80으로 바뀌는 유일한 순간이다. 로그가 없으면 나중에
    "왜 이달 점수가 전부 낮지?"를 풀 방법이 없다(설계 7장).
    """
    monkeypatch.setenv("BATCH_TRANSCRIPTION", "on")
    for name, val in LONG_SPEECH_KEYS.items():
        monkeypatch.setenv(name, val)

    with caplog.at_level(logging.INFO, logger="app.main"):
        result = transcriber_from_env()

    assert isinstance(result, ClovaLongSpeech)
    message = " ".join(record.getMessage() for record in caplog.records)
    assert "60" in message and "80" in message
