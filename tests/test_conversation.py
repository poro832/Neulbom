"""자율 대화 조립 — STT · LLM · TTS를 한 턴으로 엮는다.

셋 다 규약으로만 받으므로 어느 사업자를 쓰든 이 파일은 안 바뀐다. 계정도
키도 없이 대화의 규칙 전체가 검증된다.
"""

import logging

import numpy as np
import pytest

from app.media.conversation import (
    GREETING,
    NO_REPEAT_FALLBACK,
    RETRY_PROMPTS,
    ConversationResponder,
    Turn,
)

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


def test_an_empty_transcript_does_not_reach_the_model_and_is_not_asked_about_right_away():
    """전사가 비면 어르신이 무슨 말을 했는지 모른다.

    그 상태로 모델을 부르면 모델이 맥락 없이 아무 말이나 지어낸다. 그렇다고 곧바로 "잘 못 들었어요"를 하면
    시끄러운 곳에서는 AI가 어르신 말 위에 얹힌다(2026-10-20 현장 피드백) — 되묻기는 최대한 하지 않는다.
    """
    stt = FakeStt("")
    responder, _, chat, voice = make(stt=stt)

    assert responder.respond(AUDIO, 8000) == b""

    assert chat.seen == []
    assert voice.spoken == []


def test_it_asks_again_only_after_several_failures_in_a_row_and_in_one_sentence():
    responder, _, _, voice = make(stt=FakeStt("", "", ""))

    said = [responder.respond(AUDIO, 8000) for _ in range(3)]

    assert said[0] == b"" and said[1] == b""
    assert voice.spoken == [RETRY_PROMPTS[0]]
    for prompt in RETRY_PROMPTS:
        assert prompt.count(".") == 0  # 한 문장 — 문장 사이 무음이 없다
    assert "가까이" in RETRY_PROMPTS[1]


def test_after_asking_it_counts_again_from_zero_and_stops_after_the_last_line():
    """되물은 뒤에도 못 알아들으면 다시 세 번을 기다렸다가 다음 안내를 한다. 안내를 다 했으면 더는 말하지 않는다."""
    responder, _, _, voice = make(stt=FakeStt(*[""] * 12))

    for _ in range(12):
        responder.respond(AUDIO, 8000)

    assert voice.spoken == list(RETRY_PROMPTS)


def test_a_successful_turn_resets_the_failure_count():
    responder, _, _, voice = make(stt=FakeStt("", "", "안녕하세요", "", "", ""))

    for _ in range(6):
        responder.respond(AUDIO, 8000)

    # 실패 2번 -> 성공(연속이 끊긴다) -> 실패 3번 -> 이제야 첫 안내
    assert [text for text in voice.spoken if text in RETRY_PROMPTS] == [RETRY_PROMPTS[0]]


# --------------------------------------------------------- 전화를 받으며 하는 "여보세요?"


def test_hello_when_picking_up_gets_no_reply_from_the_model():
    """첫 인사 대본이 이미 나가고 있다. "여보세요?"에 모델이 따로 답하면 인사가 두 번 나가고 질문이 겹친다."""
    responder, _, chat, voice = make(stt=FakeStt("여보세요?"))
    responder.history.append(Turn("ai", GREETING))

    audio = responder.respond(AUDIO, 8000)

    assert audio == b""
    assert chat.seen == []
    assert voice.spoken == []
    assert responder.history == [Turn("ai", GREETING)]  # 인사는 한 번만 기록된다


def test_a_third_hello_goes_to_the_normal_conversation():
    responder, _, chat, voice = make(stt=FakeStt("여보세요", "여보세요", "여보세요"), chat=FakeChat("네, 들려요"))
    responder.history.append(Turn("ai", GREETING))

    for _ in range(3):
        responder.respond(AUDIO, 8000)

    assert len(chat.seen) == 1  # 세 번째에야 모델이 답한다


def test_other_words_are_answered_normally_even_if_they_contain_hello():
    responder, _, chat, _ = make(stt=FakeStt("여보세요 네 잘 지내요"), chat=FakeChat("다행이에요"))
    responder.history.append(Turn("ai", GREETING))

    responder.respond(AUDIO, 8000)

    assert len(chat.seen) == 1


def test_hello_after_the_conversation_began_is_not_special():
    """대화가 이미 시작된 뒤의 "여보세요"(전화가 끊긴 줄 알고 부르는 것 등)는 모델이 받는다."""
    responder, _, chat, _ = make(stt=FakeStt("여보세요"), chat=FakeChat("네, 듣고 있어요"))
    responder.history.extend([Turn("ai", GREETING), Turn("elder", "잘 지내요"), Turn("ai", "다행이에요")])

    responder.respond(AUDIO, 8000)

    assert len(chat.seen) == 1


def test_hello_is_not_special_if_the_greeting_never_played():
    responder, _, chat, _ = make(stt=FakeStt("여보세요"), chat=FakeChat("안녕하세요"))

    responder.respond(AUDIO, 8000)

    assert len(chat.seen) == 1


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


def test_a_turn_logs_how_much_audio_went_in_and_how_much_text_came_back(caplog):
    """되묻기가 나왔을 때 원인을 가르는 숫자다. 내용은 남기지 않는다."""
    import logging

    import numpy as np

    from app.media.conversation import ConversationResponder

    class Stt:
        def transcribe(self, audio, sample_rate):
            return "아침은 먹었어요"

    class Chat:
        def reply(self, history):
            return "다행이에요."

    class Voice:
        def synthesize(self, text, sample_rate):
            return b"\x00\x00"

    responder = ConversationResponder(stt=Stt(), chat=Chat(), voice=Voice())

    with caplog.at_level(logging.INFO, logger="app.media.conversation"):
        responder.respond(np.zeros(16000, dtype=np.float32), 8000)

    assert "오디오=2.0초 글자=8" in caplog.text
    assert "아침은 먹었어요" not in caplog.text


def test_a_too_short_sound_is_skipped_without_asking_again():
    """숨소리에 "죄송해요, 잘 못 들었어요"라고 되묻지 않는다."""
    import numpy as np

    from app.media.conversation import ConversationResponder, TooShortSound

    class Stt:
        def transcribe(self, audio, sample_rate):
            raise TooShortSound("STT007")

    class Chat:
        def reply(self, history):
            raise AssertionError("짧은 소리에 답을 만들면 안 된다")

    class Voice:
        spoken = []

        def synthesize(self, text, sample_rate):
            Voice.spoken.append(text)
            return b"\x00\x00"

    responder = ConversationResponder(stt=Stt(), chat=Chat(), voice=Voice())

    assert responder.respond(np.zeros(800, dtype=np.float32), 8000) == b""
    assert Voice.spoken == []


def test_too_short_sounds_do_not_use_up_the_retries():
    """짧은 소리를 몇 번 넘겼다고 진짜 못 알아들은 턴의 되묻기가 막히면 안 된다."""
    import numpy as np

    from app.media.conversation import ConversationResponder, TooShortSound

    outcomes = [TooShortSound("x"), TooShortSound("x"), TooShortSound("x"), "", "", ""]

    class Stt:
        def transcribe(self, audio, sample_rate):
            item = outcomes.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    class Chat:
        def reply(self, history):
            return "네."

    class Voice:
        def synthesize(self, text, sample_rate):
            return b"\x01\x00"

    responder = ConversationResponder(stt=Stt(), chat=Chat(), voice=Voice())
    audio = np.zeros(800, dtype=np.float32)

    for _ in range(3):
        assert responder.respond(audio, 8000) == b""
    # 진짜로 못 알아들은 턴이 연속으로 쌓이면 되묻는다(앞의 짧은 소리는 세지 않는다).
    assert responder.respond(audio, 8000) == b""
    assert responder.respond(audio, 8000) == b""
    assert responder.respond(audio, 8000) == b"\x01\x00"


# ------------------------------------------------------------ 먼저 건네는 인사


def test_the_greeting_is_spoken_without_waiting_for_the_elder():
    """"여보세요"는 짧아서 인식이 약하다. 인사를 어르신의 첫마디에 걸지 않는다."""
    responder, stt, _, voice = make(greeting="안녕하세요, 늘봄이에요.")

    audio = responder.greet(8000)

    assert voice.spoken == ["안녕하세요, 늘봄이에요."]
    assert audio == "안녕하세요, 늘봄이에요.".encode()
    assert stt.calls == 0


def test_the_model_knows_it_already_greeted():
    """인사를 기록에 넣지 않으면 모델이 첫 대답에서 또 인사한다."""
    responder, _, chat, _ = make(greeting="안녕하세요.", chat=FakeChat("네, 좋네요"))

    responder.greet(8000)
    responder.respond(AUDIO, 8000)

    assert chat.seen[0][0].speaker == "ai"
    assert chat.seen[0][0].text == "안녕하세요."


def test_a_greeting_that_could_not_be_spoken_is_not_remembered():
    responder, _, chat, _ = make(greeting="안녕하세요.", voice=FakeVoice(fail=True))

    assert responder.greet(8000) == b""
    responder.respond(AUDIO, 8000)

    assert all(turn.speaker != "ai" for turn in chat.seen[0])


def test_there_is_a_default_greeting_that_asks_an_open_question():
    responder, _, _, voice = make()

    responder.greet(8000)

    assert voice.spoken and "늘봄" in voice.spoken[0]


# ------------------------------------------------------------ 단계별 시간


class _Ticker:
    """호출할 때마다 정해 둔 만큼 흐르는 시계."""

    def __init__(self, *steps):
        self.now = 0.0
        self.steps = list(steps)

    def __call__(self):
        if self.steps:
            self.now += self.steps.pop(0)
        return self.now


def test_each_stage_of_a_turn_is_timed_in_the_log(caplog):
    """말이 끝나고 AI가 입을 열기까지 어디서 걸리는지 모르면 줄일 곳을 못 찾는다.
    인식, 생성, 합성을 따로 남긴다(내용은 남기지 않는다)."""
    ticker = _Ticker(0, 1.2, 0.9, 2.1)
    responder, _, _, _ = make(clock=ticker)

    with caplog.at_level(logging.INFO, logger="app.media.conversation"):
        responder.respond(AUDIO, 8000)

    message = " ".join(record.getMessage() for record in caplog.records)
    assert "인식=1200ms" in message
    assert "생성=900ms" in message
    assert "합성=2100ms" in message


def test_the_greeting_is_one_sentence_so_no_pause_opens_between_sentences():
    """문장 사이 무음에 어르신이 말을 시작하면 인사와 겹친다(시끄러운 현장 피드백, 2026-10-20)."""
    from app.media.clova_chat import _join_sentences
    from app.media.conversation import GREETING

    assert _join_sentences(GREETING) == GREETING  # 문장 경계가 하나도 없다
    assert GREETING.count(".") == 0
    assert GREETING.endswith("?")
    assert len(GREETING) <= 40


# ------------------------------------------------- 같은 질문은 두 번 하지 않는다 (2026-10-20 현장 피드백)


def history_with_question():
    return [Turn("ai", "안녕하세요 어르신, 늘봄에서 안부 전화 드렸는데 오늘 하루는 어떠세요?")]


def test_it_does_not_ask_the_same_question_again_and_remakes_the_reply():
    chat = FakeChat("네, 그러시군요. 오늘 하루는 어떠세요?", "그러셨군요, 점심은 드셨어요?")
    responder, _, _, voice = make(stt=FakeStt("그냥 그래요"), chat=chat)
    responder.history.extend(history_with_question())

    responder.respond(AUDIO, 8000)

    assert len(chat.seen) == 2  # 한 번 다시 만들었다
    assert voice.spoken[-1] == "그러셨군요, 점심은 드셨어요?"
    assert responder.history[-1] == Turn("ai", "그러셨군요, 점심은 드셨어요?")
    # 다시 만들 때만 모델에게 당부를 붙이고, 대화 기록에는 남기지 않는다
    assert chat.seen[1][-1].note
    assert not chat.seen[0][-1].note
    assert all(not turn.note for turn in responder.history)


def test_when_the_remake_repeats_too_it_only_acknowledges_without_a_question():
    chat = FakeChat("오늘 하루는 어떠세요?", "오늘 하루 어떠세요?")
    responder, _, _, voice = make(stt=FakeStt("그냥 그래요"), chat=chat)
    responder.history.extend(history_with_question())

    responder.respond(AUDIO, 8000)

    assert voice.spoken[-1] == NO_REPEAT_FALLBACK
    assert "?" not in NO_REPEAT_FALLBACK


@pytest.mark.parametrize(
    "said",
    ["다시 말해줘", "다시 한번 말씀해 주세요", "못 들었어요", "뭐라고요?", "잘 안 들려요", "한 번 더 해 주세요"],
)
def test_it_repeats_the_question_only_when_the_elder_asks_to(said):
    chat = FakeChat("오늘 하루는 어떠세요?")
    responder, _, _, voice = make(stt=FakeStt(said), chat=chat)
    responder.history.extend(history_with_question())

    responder.respond(AUDIO, 8000)

    assert len(chat.seen) == 1  # 다시 만들지 않는다
    assert voice.spoken[-1] == "오늘 하루는 어떠세요?"


def test_a_different_question_is_fine():
    chat = FakeChat("그러셨군요, 점심은 드셨어요?")
    responder, _, _, voice = make(stt=FakeStt("그냥 그래요"), chat=chat)
    responder.history.extend(history_with_question())

    responder.respond(AUDIO, 8000)

    assert len(chat.seen) == 1
    assert voice.spoken[-1] == "그러셨군요, 점심은 드셨어요?"


def test_a_slightly_reworded_question_counts_as_the_same_question():
    chat = FakeChat("그러세요, 오늘 하루는 어떠셨어요?", "그러세요, 몸은 좀 어떠세요?")
    responder, _, _, voice = make(stt=FakeStt("그냥 그래요"), chat=chat)
    responder.history.extend(history_with_question())

    responder.respond(AUDIO, 8000)

    assert voice.spoken[-1] == "그러세요, 몸은 좀 어떠세요?"


def test_a_reply_without_any_question_is_never_flagged():
    chat = FakeChat("네, 알겠어요")
    responder, _, _, _ = make(stt=FakeStt("그냥 그래요"), chat=chat)
    responder.history.extend(history_with_question())

    responder.respond(AUDIO, 8000)

    assert len(chat.seen) == 1


def test_hello_when_picking_up_never_replays_the_greeting_question():
    """인사의 질문도 질문이다. 어르신이 다시 말해 달라고 하시지 않았으니 두 번 하지 않는다."""
    responder, _, chat, voice = make(stt=FakeStt("여보세요", "여보세요?"))
    responder.history.append(Turn("ai", GREETING))

    first = responder.respond(AUDIO, 8000)
    second = responder.respond(AUDIO, 8000)

    assert first == b"" and second == b""
    assert voice.spoken == []
    assert chat.seen == []
