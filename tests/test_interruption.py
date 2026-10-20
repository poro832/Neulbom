"""어르신이 AI의 말을 끊고 대답하면, 모델이 \"끼어들어 답하셨음\"을 알고 대본에 맞춰 이어 간다."""

from __future__ import annotations

import struct

import numpy as np

from app.media.clova_chat import INTERRUPTED_NOTE, ClovaChat
from app.media.conversation import ConversationResponder, Turn
from app.media.session import CallSession

SAMPLE_RATE = 16000
FRAME_BYTES = 640  # 20ms


def pcm16(*spans):
    values: list[int] = []
    for kind, duration_ms in spans:
        count = int(SAMPLE_RATE * duration_ms / 1000)
        if kind == "speech":
            values.extend(9000 if i % 2 == 0 else -9000 for i in range(count))
        else:
            values.extend(0 for _ in range(count))
    return struct.pack(f"<{len(values)}h", *values)


class Feeder:
    """통화 시계를 이어 가며 오디오를 밀어 넣는다(drain은 매번 0에서 시작해서 못 쓴다)."""

    def __init__(self, session):
        self.session = session
        self.timestamp_ms = 0

    def feed(self, data):
        for start in range(0, len(data), FRAME_BYTES):
            chunk = data[start : start + FRAME_BYTES]
            self.session.push_audio(chunk, timestamp_ms=self.timestamp_ms)
            self.timestamp_ms += len(chunk) * 1000 // (SAMPLE_RATE * 2)


class RecordingResponder:
    """끼어들었는지를 받는 응답기."""

    def __init__(self):
        self.interrupted: list[bool] = []

    def respond(self, audio, sample_rate, interrupted=False):
        self.interrupted.append(interrupted)
        return b"\x10\x00"


class PlainResponder:
    """끼어들었는지 모르는 응답기(고정 응답 등). 예전 모양 그대로 불려야 한다."""

    def __init__(self):
        self.calls = 0

    def respond(self, audio, sample_rate):
        self.calls += 1
        return b"\x10\x00"


def run_two_turns(responder, *, mark_end_before_second: bool, second_after_ms: int = 0):
    """첫 발화 → AI 응답 시작(begin 표식) → (필요하면 끝 표식) → 두 번째 발화."""
    session = CallSession("c1", SAMPLE_RATE, responder)
    feeder = Feeder(session)
    feeder.feed(pcm16(("speech", 500), ("silence", 1000)))  # 첫 발화, 응답이 나간다
    session.on_mark("turn1-begin")  # 플랫폼이 AI 말을 재생하기 시작했다
    if mark_end_before_second:
        feeder.feed(pcm16(("silence", 1500)))  # AI가 말하는 동안 어르신은 조용하다
        session.on_mark("turn1-end")
    if second_after_ms:
        feeder.feed(pcm16(("silence", second_after_ms)))
    feeder.feed(pcm16(("speech", 800), ("silence", 1000)))  # 두 번째 발화
    return session


def test_speaking_while_the_ai_is_still_playing_is_an_interruption():
    responder = RecordingResponder()

    run_two_turns(responder, mark_end_before_second=False)

    assert responder.interrupted == [False, True]


def test_answering_after_the_ai_finished_is_not_an_interruption():
    responder = RecordingResponder()

    run_two_turns(responder, mark_end_before_second=True, second_after_ms=500)

    assert responder.interrupted == [False, False]


def test_starting_right_as_the_ai_ends_is_not_an_interruption():
    """AI가 끝나기 직전(300ms 안)에 대답을 시작한 것은 끼어든 것이 아니다."""
    responder = RecordingResponder()
    session = CallSession("c1", SAMPLE_RATE, responder)
    feeder = Feeder(session)
    feeder.feed(pcm16(("speech", 500), ("silence", 1000)))
    session.on_mark("turn1-begin")
    feeder.feed(pcm16(("silence", 1000)))
    # 두 번째 발화가 시작된 뒤, AI가 끝나기까지 200ms만 겹친다
    feeder.feed(pcm16(("speech", 200)))
    session.on_mark("turn1-end")
    feeder.feed(pcm16(("speech", 600), ("silence", 1000)))

    assert responder.interrupted == [False, False]


def test_a_responder_that_does_not_know_about_interruptions_is_called_as_before():
    responder = PlainResponder()

    run_two_turns(responder, mark_end_before_second=False)

    assert responder.calls == 2


# ---------------------------------------------------------------- 대화 기록과 모델


class FakeStt:
    def transcribe(self, audio, sample_rate):
        return "응, 먹었어"


class FakeChat:
    def __init__(self):
        self.seen = []

    def reply(self, history):
        self.seen.append(list(history))
        return "다행이에요, 낮잠은 주무셨어요?"


class FakeVoice:
    def synthesize(self, text, sample_rate):
        return text.encode()


def test_the_conversation_remembers_the_full_script_and_marks_the_interrupted_turn():
    chat = FakeChat()
    responder = ConversationResponder(stt=FakeStt(), chat=chat, voice=FakeVoice())
    responder.history.append(Turn("ai", "어르신, 오늘 아침 약은 드셨어요?"))

    responder.respond(np.zeros(160, dtype=np.float32), SAMPLE_RATE, interrupted=True)

    elder = chat.seen[0][-1]
    assert elder == Turn("elder", "응, 먹었어", True)
    # AI의 대본은 끝까지 들었든 아니든 전체가 그대로 남는다
    assert chat.seen[0][0] == Turn("ai", "어르신, 오늘 아침 약은 드셨어요?")
    assert responder.history[-1] == Turn("ai", "다행이에요, 낮잠은 주무셨어요?")


def test_a_normal_turn_is_not_marked():
    chat = FakeChat()
    responder = ConversationResponder(stt=FakeStt(), chat=chat, voice=FakeVoice())

    responder.respond(np.zeros(160, dtype=np.float32), SAMPLE_RATE)

    assert chat.seen[0][-1].interrupted is False


def test_the_model_is_told_about_the_interruption_but_the_stored_text_is_untouched():
    chat = ClovaChat(api_key="KEY", base_url="https://example.test", transport=lambda *a, **k: b"")
    history = [
        Turn("ai", "어르신, 오늘 아침 약은 드셨어요?"),
        Turn("elder", "응, 먹었어", True),
        Turn("ai", "다행이에요."),
        Turn("elder", "그래요"),
    ]

    messages = chat._messages(history)

    assert messages[2] == {"role": "user", "content": f"{INTERRUPTED_NOTE} 응, 먹었어"}
    assert messages[4] == {"role": "user", "content": "그래요"}
    assert history[1].text == "응, 먹었어"  # 저장되는 말은 그대로다
    assert messages[1]["content"] == "어르신, 오늘 아침 약은 드셨어요?"


def test_the_prompt_explains_what_the_interruption_note_means():
    from app.media.clova_chat import DEFAULT_SYSTEM_PROMPT as P

    assert INTERRUPTED_NOTE in P
    assert "같은 질문을 다시 하지 말고" in P
