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
    "CLOVA_STUDIO_MODEL", "POLLY_VOICE_ID", "CLOVA_SPEECH_SHORT_SECRET",
    "PROSODY_EMOTION", "PROSODY_SPEED",
    # AWS_REGION이 비면 boto3가 ~/.aws/config를 뒤진다. 그래서 이 파일의
    # polly 테스트가 **개발자 PC에 AWS CLI가 설정돼 있느냐**에 따라 통과하고
    # 실패했다 — 로컬 520 통과, EC2 2 실패로 드러났다. 지우고 나서
    # POLLY_ENV가 명시적으로 넣는다.
    "AWS_REGION", "AWS_DEFAULT_REGION",
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
    # 값 자체는 아무 리전이어도 된다. 중요한 건 **어디서 오느냐**다 —
    # 여기서 주지 않으면 테스트가 실행 환경의 AWS 설정을 읽는다.
    "AWS_REGION": "ap-northeast-2",
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
# 점수의 만점을 80에서 100으로 바꾸는 유일한 함수다. 조용히 꺼진 채로 돌면
# 부정 표현 축은 계속 죽어 있고, 그달 모든 점수가 만점 80으로 나오는데
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
    """만점이 80에서 100으로 바뀌는 유일한 순간이다. 로그가 없으면 나중에
    "왜 이달 점수가 전부 낮지?"를 풀 방법이 없다(설계 7장).
    """
    monkeypatch.setenv("BATCH_TRANSCRIPTION", "on")
    for name, val in LONG_SPEECH_KEYS.items():
        monkeypatch.setenv(name, val)

    with caplog.at_level(logging.INFO, logger="app.main"):
        result = transcriber_from_env()

    assert isinstance(result, ClovaLongSpeech)
    message = " ".join(record.getMessage() for record in caplog.records)
    assert "80" in message and "100" in message


def test_short_recognition_uses_its_own_secret_when_given(monkeypatch):
    """단문 인식은 장문과 다른 NCP 도메인이라 시크릿이 따로다."""
    set_env(monkeypatch, {**FULL, "CLOVA_SPEECH_SHORT_SECRET": "short-secret"})

    responder = responder_from_env()

    assert responder.stt._secret_key == "short-secret"


def test_short_recognition_falls_back_to_the_main_secret(monkeypatch):
    set_env(monkeypatch, FULL)

    assert responder_from_env().stt._secret_key == "s-secret"


# ------------------------------------------------ 켜질 때 점검 (전화 없이 확인한다)


PROSODY_FULL = {
    "CLOVA_SPEECH_INVOKE_URL": "https://spch.test/external/v1/1/a",
    "CLOVA_SPEECH_SECRET": "s-secret",
    "CLOVA_STUDIO_BASE_URL": "https://studio.test",
    "CLOVA_STUDIO_API_KEY": "studio-key",
    "PROSODY_API_KEY": "p-key",
    "PROSODY_VOICE_NAME": "은린",
}


def test_startup_says_when_everything_for_the_conversation_is_there(monkeypatch, caplog):
    import logging

    from app.main import log_startup_readiness

    set_env(monkeypatch, {**PROSODY_FULL, "CLOVA_SPEECH_SHORT_SECRET": "short"})

    with caplog.at_level(logging.INFO, logger="app.main"):
        log_startup_readiness()

    assert "AI 대화가 켜진다" in caplog.text
    assert "은린" in caplog.text
    assert "빠진 값" not in caplog.text


def test_startup_names_every_missing_value(monkeypatch, caplog):
    """전화가 연결돼야 경고가 찍히던 것을, 켜질 때 알려 준다."""
    import logging

    from app.main import log_startup_readiness

    set_env(monkeypatch, {"PROSODY_API_KEY": "p-key"})

    with caplog.at_level(logging.WARNING, logger="app.main"):
        log_startup_readiness()

    assert "AI 대화가 꺼진 채" in caplog.text
    assert "PROSODY_VOICE_NAME" in caplog.text
    assert "CLOVA_STUDIO_API_KEY" in caplog.text


def test_startup_warns_when_the_short_recognition_secret_is_missing(monkeypatch, caplog):
    """단문은 장문과 다른 NCP 도메인이라 시크릿이 다르다(2026-10-06, 401)."""
    import logging

    from app.main import log_startup_readiness

    set_env(monkeypatch, PROSODY_FULL)

    with caplog.at_level(logging.WARNING, logger="app.main"):
        log_startup_readiness()

    assert "CLOVA_SPEECH_SHORT_SECRET" in caplog.text


def test_startup_rejects_an_unknown_vendor_loudly(monkeypatch, caplog):
    import logging

    from app.main import log_startup_readiness

    set_env(monkeypatch, {**PROSODY_FULL, "TTS_VENDOR": "prosodi"})

    with caplog.at_level(logging.WARNING, logger="app.main"):
        log_startup_readiness()

    assert "모르는 TTS 벤더" in caplog.text


def test_startup_reminds_that_batch_transcription_is_off(monkeypatch, caplog):
    import logging

    from app.main import log_startup_readiness

    set_env(monkeypatch, PROSODY_FULL)
    monkeypatch.delenv("BATCH_TRANSCRIPTION", raising=False)

    with caplog.at_level(logging.INFO, logger="app.main"):
        log_startup_readiness()

    assert "배치 전사가 꺼져 있다" in caplog.text


def test_startup_check_never_raises_or_builds_a_responder(monkeypatch):
    from app.main import log_startup_readiness

    set_env(monkeypatch, {})

    log_startup_readiness()  # 키가 하나도 없어도 서버는 떠야 한다


# ------------------------------------------------ 위험 판정 → 알림


def _sink_world():
    from app.api.alert_rules import AlertRules
    from app.api.alerts import InMemoryAlertStore
    from app.api.elder_directory import ElderAccess, InMemoryElderDirectory
    from app.api.store import InMemoryCallStore

    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    call, _ = store.find_active_or_create(12, "scheduled")
    alerts = InMemoryAlertStore()
    directory = InMemoryElderDirectory({12: ElderAccess(1, True, "어르신 12")})
    return store, call, alerts, AlertRules(alerts=alerts, elders=directory)


def _quiet_analysis():
    from app.analysis.call_analysis import CallAnalysis
    from app.analysis.metrics_calculator import CallMetrics

    # 기준선이 없을 때 말수 0, 응답 지연 9초, 부정 표현 5개면 35+25+20=80점 → alert 단계다.
    return CallAnalysis(
        metrics=CallMetrics(
            speech_ratio=0.0,
            silence_ratio=1.0,
            turn_count=1,
            negative_word_count=5,
            avg_response_delay_ms=9000,
        ),
        clipped_ms=0,
        filled_gap_ms=0,
        call_duration_ms=10_000,
    )


def test_a_risky_judgement_raises_an_alert_and_a_failing_alert_does_not_block_the_record():
    from app.api.outcome_store import InMemoryOutcomeStore
    from app.main import build_risk_sink

    store, call, alerts, rules = _sink_world()
    outcomes = InMemoryOutcomeStore()
    sink = build_risk_sink(store, outcomes, alert_rules=rules)

    sink(call.call_id, _quiet_analysis())

    assert outcomes.recent(12, 5)[0].call_id == call.call_id
    risen = [a for a in alerts.recent_for_guardian(1, 10) if a.alert_type == "risk_rise"]
    assert len(risen) == 1 and risen[0].call_id == call.call_id


def test_an_alert_rule_failure_leaves_the_judgement_recorded():
    from app.api.outcome_store import InMemoryOutcomeStore
    from app.main import build_risk_sink

    class BrokenRules:
        def on_risk(self, **kwargs):
            raise RuntimeError("알림 고장")

    store, call, _, _ = _sink_world()
    outcomes = InMemoryOutcomeStore()
    sink = build_risk_sink(store, outcomes, alert_rules=BrokenRules())

    sink(call.call_id, _quiet_analysis())

    assert [o.call_id for o in outcomes.recent(12, 5)] == [call.call_id]
