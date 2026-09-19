"""자율 대화 조립 — STT · LLM · TTS를 한 턴으로 엮는다.

셋 다 규약으로만 받으므로 어느 사업자를 쓰든 이 파일은 안 바뀐다. 계정도
키도 없이 대화의 규칙 전체가 검증된다.
"""

import logging

import numpy as np

from app.media.conversation import ConversationResponder

AUDIO = np.zeros(160, dtype=np.float32)


class FakeStt:
    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = 0

    def transcribe(self, audio, sample_rate):
        self.calls += 1
        return self.texts.pop(0) if self.texts else ""


class FakeChat:
    def __init__(self, *replies, fail=False):
        self.replies = list(replies)
        self.seen = []
        self.fail = fail

    def reply(self, history):
        if self.fail:
            raise RuntimeError("모델 오류")
        self.seen.append(list(history))
        return self.replies.pop(0) if self.replies else "네."


class FakeVoice:
    def __init__(self, fail=False):
        self.spoken = []
        self.fail = fail

    def synthesize(self, text, sample_rate):
        if self.fail:
            raise RuntimeError("합성 오류")
        self.spoken.append(text)
        return text.encode()


def make(stt=None, chat=None, voice=None, **kwargs):
    stt = stt or FakeStt("안녕하세요")
    chat = chat or FakeChat("반갑습니다")
    voice = voice or FakeVoice()
    return ConversationResponder(stt=stt, chat=chat, voice=voice, **kwargs), stt, chat, voice


# ------------------------------------------------------------ 한 턴


def test_one_turn_goes_stt_then_chat_then_tts():
    responder, _, _, voice = make()

    audio = responder.respond(AUDIO, 8000)

    assert voice.spoken == ["반갑습니다"]
    assert audio == b"\xeb\xb0\x98\xea\xb0\x91\xec\x8a\xb5\xeb\x8b\x88\xeb\x8b\xa4"


def test_the_model_sees_what_was_said_before():
    """맥락 없이 답하면 대화가 아니라 독립된 문답의 나열이 된다."""
    stt = FakeStt("안녕하세요", "밥 먹었어요")
    chat = FakeChat("반갑습니다", "잘하셨네요")
    responder, _, _, _ = make(stt=stt, chat=chat)

    responder.respond(AUDIO, 8000)
    responder.respond(AUDIO, 8000)

    assert [(t.speaker, t.text) for t in chat.seen[1]] == [
        ("elder", "안녕하세요"),
        ("ai", "반갑습니다"),
        ("elder", "밥 먹었어요"),
    ]


# ------------------------------------------------- 못 알아들었을 때


def test_an_empty_transcript_does_not_reach_the_model():
    """전사가 비면 어르신이 무슨 말을 했는지 모른다.

    그 상태로 모델을 부르면 모델이 맥락 없이 아무 말이나 지어낸다 — 어르신은
    자기가 한 말과 상관없는 대답을 듣는다.
    """
    stt = FakeStt("")
    responder, _, chat, voice = make(stt=stt)

    responder.respond(AUDIO, 8000)

    assert chat.seen == []
    assert voice.spoken == ["죄송해요, 잘 못 들었어요. 다시 말씀해 주시겠어요?"]


def test_it_stops_asking_again_after_repeated_failures():
    """같은 되묻기를 반복하면 어르신은 대화가 고장났다고 느낀다.

    연속 실패가 이어지면 되묻기를 멈춘다 — 아무 말도 안 하는 편이 같은
    문장을 세 번 듣는 것보다 낫다.
    """
    responder, _, _, voice = make(stt=FakeStt("", "", ""))

    said = [responder.respond(AUDIO, 8000) for _ in range(3)]

    assert voice.spoken.count("죄송해요, 잘 못 들었어요. 다시 말씀해 주시겠어요?") == 2
    assert said[2] == b""


def test_a_successful_turn_resets_the_failure_count():
    responder, _, _, voice = make(stt=FakeStt("", "안녕하세요", "", ""))

    for _ in range(4):
        responder.respond(AUDIO, 8000)

    # 되묻기 1회 → 성공 → 다시 2회까지 되묻을 수 있다.
    assert voice.spoken.count("죄송해요, 잘 못 들었어요. 다시 말씀해 주시겠어요?") == 3


# --------------------------------------------------------- 실패 처리


def test_a_model_failure_does_not_kill_the_turn(caplog):
    """모델이 죽었다고 통화를 끊으면 어르신은 영문을 모른다."""
    responder, _, _, voice = make(chat=FakeChat(fail=True))

    with caplog.at_level(logging.ERROR, logger="app.media.conversation"):
        audio = responder.respond(AUDIO, 8000)

    assert audio == b""
    assert caplog.records


def test_a_voice_failure_does_not_kill_the_turn(caplog):
    responder, _, _, _ = make(voice=FakeVoice(fail=True))

    with caplog.at_level(logging.ERROR, logger="app.media.conversation"):
        assert responder.respond(AUDIO, 8000) == b""


def test_a_failed_turn_is_not_remembered_as_if_it_was_said():
    """들려주지 못한 말을 대화 기록에 넣으면, 모델은 어르신이 듣지 못한
    문장을 이어받아 다음 말을 만든다 — 대화가 어긋난다."""
    chat = FakeChat("첫 대답", "두 번째")
    responder, _, _, _ = make(stt=FakeStt("안녕", "또 안녕"), chat=chat, voice=FakeVoice(fail=True))

    responder.respond(AUDIO, 8000)
    responder.respond(AUDIO, 8000)

    assert [(t.speaker, t.text) for t in chat.seen[1]] == [
        ("elder", "안녕"),
        ("elder", "또 안녕"),
    ]


# --------------------------------------------------------- 전사문


def test_the_transcript_is_kept_for_the_report_not_for_the_score():
    """실시간 전사는 프레임이 어떻게 잘렸느냐에 따라 달라진다.

    점수에 쓰면 같은 통화가 다시 돌 때 다른 숫자가 나온다 — 결정론이 깨진다.
    그래서 점수용 전사는 통화가 끝난 뒤 녹음으로 다시 만든다(설계 3.2).
    여기 모이는 것은 보호자에게 보여줄 대화 기록이다.
    """
    responder, _, _, _ = make(stt=FakeStt("안녕하세요", "밥 먹었어요"))

    responder.respond(AUDIO, 8000)
    responder.respond(AUDIO, 8000)

    assert [(t.speaker, t.text) for t in responder.history] == [
        ("elder", "안녕하세요"),
        ("ai", "반갑습니다"),
        ("elder", "밥 먹었어요"),
        ("ai", "네."),
    ]
