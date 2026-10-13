import pytest

from app.media.medication_check import MedicationClassifier, classifier_from_env


class FakeChat:
    def __init__(self, answer="taken", error=None):
        self.answer, self.error, self.seen = answer, error, None

    def reply(self, history):
        self.seen = list(history)
        if self.error:
            raise self.error
        return self.answer


TURNS = [("ai", "오늘 약은 챙겨 드셨어요?"), ("elder", "네 아침에 먹었어요")]


def test_taken_not_taken_unknown_pass_through():
    for word in ("taken", "not_taken", "unknown"):
        assert MedicationClassifier(FakeChat(word), "m").classify(TURNS) == word


def test_answer_is_normalized_but_must_match_exactly():
    assert MedicationClassifier(FakeChat("  Taken.\n"), "m").classify(TURNS) == "taken"
    assert MedicationClassifier(FakeChat('"NOT_TAKEN"'), "m").classify(TURNS) == "not_taken"


@pytest.mark.parametrize("answer", ["", "   ", "네 드셨어요", "치매가 의심됩니다", "taken not_taken", "yes", "not taken"])
def test_anything_else_is_unknown(answer):
    assert MedicationClassifier(FakeChat(answer), "m").classify(TURNS) == "unknown"


def test_no_elder_speech_means_none_and_no_model_call():
    chat = FakeChat()
    assert MedicationClassifier(chat, "m").classify([("ai", "안녕하세요")]) is None
    assert MedicationClassifier(chat, "m").classify([("elder", "  ")]) is None
    assert chat.seen is None


def test_dialogue_is_sent_as_one_message():
    chat = FakeChat()
    MedicationClassifier(chat, "m").classify(TURNS)
    assert len(chat.seen) == 1 and chat.seen[0].speaker == "elder"
    assert "AI: 오늘 약은 챙겨 드셨어요?" in chat.seen[0].text
    assert "어르신: 네 아침에 먹었어요" in chat.seen[0].text


def test_model_errors_are_not_swallowed():
    with pytest.raises(RuntimeError):
        MedicationClassifier(FakeChat(error=RuntimeError("down")), "m").classify(TURNS)


def test_from_env_needs_both_credentials(monkeypatch):
    monkeypatch.delenv("CLOVA_STUDIO_API_KEY", raising=False)
    monkeypatch.delenv("CLOVA_STUDIO_BASE_URL", raising=False)
    assert classifier_from_env() is None
    monkeypatch.setenv("CLOVA_STUDIO_API_KEY", "k")
    monkeypatch.setenv("CLOVA_STUDIO_BASE_URL", "https://example.invalid")
    classifier = classifier_from_env()
    assert classifier is not None and classifier.model_id
