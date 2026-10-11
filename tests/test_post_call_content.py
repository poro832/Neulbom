import logging

from app.api.call_content import InMemoryCallContent
from app.main import _end_of_call
from app.post_call_content import ConversationRecorder


class FakeSummarizer:
    model_id = "HCX-DASH-002"

    def __init__(self, result="점심을 드셨어요.", error=None):
        self.result, self.error, self.calls = result, error, 0

    def summarize(self, turns):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def run_now(job):
    job()


TURNS = [("ai", "안녕하세요"), ("elder", "네")]


def test_saves_turns_and_summary():
    content = InMemoryCallContent()
    ConversationRecorder(content, FakeSummarizer(), spawn=run_now).record(1, TURNS)
    assert [(t.speaker, t.text) for t in content.turns(1)] == TURNS
    assert content.summaries([1]) == {1: "점심을 드셨어요."}


def test_no_turns_saves_nothing():
    content = InMemoryCallContent()
    s = FakeSummarizer()
    ConversationRecorder(content, s, spawn=run_now).record(1, [])
    assert content.turns(1) == [] and s.calls == 0


def test_ai_only_call_saves_turns_but_no_summary():
    content = InMemoryCallContent()
    s = FakeSummarizer()
    ConversationRecorder(content, s, spawn=run_now).record(1, [("ai", "안녕하세요")])
    assert len(content.turns(1)) == 1 and s.calls == 0 and content.summaries([1]) == {}


def test_summary_failure_keeps_turns_and_logs_no_content(caplog):
    content = InMemoryCallContent()
    rec = ConversationRecorder(content, FakeSummarizer(error=RuntimeError("down")), spawn=run_now)
    with caplog.at_level(logging.INFO):
        rec.record(1, TURNS)
    assert len(content.turns(1)) == 2 and content.summaries([1]) == {}
    assert "안녕하세요" not in caplog.text


def test_rejected_summary_is_not_saved():
    content = InMemoryCallContent()
    ConversationRecorder(content, FakeSummarizer(result=None), spawn=run_now).record(1, TURNS)
    assert content.summaries([1]) == {}


def test_store_failure_is_swallowed():
    class Broken(InMemoryCallContent):
        def save_turns(self, call_id, turns):
            raise RuntimeError("db down")

    ConversationRecorder(Broken(), FakeSummarizer(), spawn=run_now).record(1, TURNS)


def test_no_summarizer_still_saves_turns():
    content = InMemoryCallContent()
    ConversationRecorder(content, None, spawn=run_now).record(1, TURNS)
    assert len(content.turns(1)) == 2


def test_summary_runs_off_the_calling_thread_by_default():
    """기본 spawn은 스레드다 — 요약 때문에 통화 종료 처리가 늦어지면 안 된다."""
    import threading

    started = threading.Event()
    release = threading.Event()

    class Slow:
        model_id = "m"

        def summarize(self, turns):
            started.set()
            release.wait(5)
            return "느린 요약"

    content = InMemoryCallContent()
    ConversationRecorder(content, Slow()).record(1, TURNS)  # 기다리지 않고 돌아와야 한다
    assert started.wait(5)
    assert content.summaries([1]) == {}
    release.set()


class StubSession:
    call_id = "7"

    def __init__(self, turns):
        self._turns = turns

    def conversation_turns(self):
        return self._turns


class SpyLifecycle:
    def __init__(self):
        self.finished = []

    def stream_finished(self, call_id, audio_key):
        self.finished.append(call_id)


def test_end_of_call_records_the_conversation_and_still_finishes():
    content = InMemoryCallContent()
    lifecycle = SpyLifecycle()
    recorder = ConversationRecorder(content, None, spawn=run_now)

    _end_of_call(lifecycle, sink=lambda *a: None, recorder=recorder)(StubSession(TURNS), None)

    assert len(content.turns(7)) == 2
    assert lifecycle.finished == [7]


def test_end_of_call_finishes_even_if_recording_blows_up():
    class Boom:
        def record(self, call_id, turns):
            raise RuntimeError("boom")

    lifecycle = SpyLifecycle()
    _end_of_call(lifecycle, sink=lambda *a: None, recorder=Boom())(StubSession(TURNS), None)

    assert lifecycle.finished == [7]
