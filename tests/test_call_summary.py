import pytest

from app.media.call_summary import CallSummarizer, summarizer_from_env


class FakeChat:
    def __init__(self, answer="점심을 드셨고 무릎이 조금 아프다고 하셨어요."):
        self.answer = answer
        self.seen = None

    def reply(self, history):
        self.seen = list(history)
        return self.answer


def test_summarizes_dialogue_as_one_message():
    chat = FakeChat()
    out = CallSummarizer(chat, "HCX-DASH-002").summarize(
        [("ai", "식사하셨어요?"), ("elder", "네 점심 먹었어요")]
    )
    assert out == "점심을 드셨고 무릎이 조금 아프다고 하셨어요."
    assert len(chat.seen) == 1 and chat.seen[0].speaker == "elder"
    assert "AI: 식사하셨어요?" in chat.seen[0].text
    assert "어르신: 네 점심 먹었어요" in chat.seen[0].text


def test_no_elder_speech_means_no_summary_and_no_model_call():
    chat = FakeChat()
    assert CallSummarizer(chat, "m").summarize([("ai", "안녕하세요")]) is None
    assert chat.seen is None


def test_forbidden_word_is_rejected():
    for word in ("우울", "치매", "진단", "증세"):
        chat = FakeChat(f"{word}이 의심돼요.")
        assert CallSummarizer(chat, "m").summarize([("elder", "네")]) is None


def test_empty_answer_is_none():
    assert CallSummarizer(FakeChat("  "), "m").summarize([("elder", "네")]) is None


def test_model_errors_propagate():
    class Boom:
        def reply(self, history):
            raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        CallSummarizer(Boom(), "m").summarize([("elder", "네")])


def test_summarizer_from_env_needs_credentials(monkeypatch):
    monkeypatch.delenv("CLOVA_STUDIO_API_KEY", raising=False)
    assert summarizer_from_env() is None


def test_summarizer_from_env_builds_with_credentials(monkeypatch):
    monkeypatch.setenv("CLOVA_STUDIO_API_KEY", "k")
    monkeypatch.setenv("CLOVA_STUDIO_BASE_URL", "https://example.invalid")
    s = summarizer_from_env()
    assert s is not None and s.model_id
