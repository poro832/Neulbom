"""AI 채팅 서비스 — 모델·알림은 가짜로 두고 규칙을 확인한다."""

import pytest

from app.chat.alerting import ALERT_TYPE, make_urgent_alerter
from app.chat.service import (
    DAILY_LIMIT,
    SESSION_IDLE_SECONDS,
    ChatLimitReached,
    ChatService,
    ChatUnavailable,
)
from app.chat.store import InMemoryChatStore
from app.chat.urgent import GUARDIAN_ALERT_MESSAGE
from app.media.call_summary import CallSummarizer
from app.media.conversation import Turn

NOW = 1_800_000_000.0


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class FakeModel:
    def __init__(self, answer="네, 알겠어요.", fail=False):
        self.answer = answer
        self.fail = fail
        self.seen: list[list[Turn]] = []

    def reply(self, history):
        self.seen.append(list(history))
        if self.fail:
            raise TimeoutError("느림")
        return self.answer


def make(model=None, summarizer=None, on_urgent="record", clock=None):
    clock = clock or Clock()
    alerts_sent: list[tuple[int, str]] = []
    handler = (lambda elder_id, category: alerts_sent.append((elder_id, category)) or True) if on_urgent == "record" else on_urgent
    service = ChatService(
        store=InMemoryChatStore(),
        model=model if model is not None else FakeModel(),
        summarizer=summarizer,
        on_urgent=handler,
        clock=clock,
    )
    return service, clock, alerts_sent


def test_an_ordinary_message_gets_the_models_answer_and_no_alert():
    service, _, alerts = make(FakeModel("산책하기 좋은 날이에요."))

    result = service.send(12, "오늘 날씨 어때요?")

    assert result.reply == "산책하기 좋은 날이에요." and result.urgent is None
    assert alerts == []


def test_the_model_sees_the_recent_conversation_in_order():
    model = FakeModel()
    service, clock, _ = make(model)

    service.send(12, "첫 말")
    clock.now += 60
    service.send(12, "둘째 말")

    assert [(t.speaker, t.text) for t in model.seen[1]] == [("elder", "첫 말"), ("ai", "네, 알겠어요."), ("elder", "둘째 말")]


def test_after_a_long_pause_the_model_starts_fresh():
    model = FakeModel()
    service, clock, _ = make(model)
    service.send(12, "아침 이야기")
    clock.now += SESSION_IDLE_SECONDS + 60

    service.send(12, "저녁 이야기")

    assert [t.text for t in model.seen[1]] == ["저녁 이야기"]


def test_an_urgent_message_alerts_once_a_day_and_always_carries_the_safety_notice():
    service, clock, alerts = make(FakeModel("많이 힘드시겠어요."))

    first = service.send(12, "가슴이 너무 아파요")
    clock.now += 120
    second = service.send(12, "여전히 가슴이 아파요")

    assert first.urgent == "medical" and "119" in first.reply and first.reply.startswith("많이 힘드시겠어요.")
    assert alerts == [(12, "medical")]  # 두 번째는 오늘 이미 알렸다
    assert "119" in second.reply  # 안내는 매번 붙는다

    clock.now += 86400 + 10
    service.send(12, "또 가슴이 아파요")
    assert len(alerts) == 2  # 하루가 지나면 다시 알린다


def test_the_urgent_alert_goes_out_even_when_the_model_is_down():
    service, _, alerts = make(FakeModel(fail=True))

    result = service.send(12, "숨이 안 쉬어져요")

    assert alerts == [(12, "medical")]
    assert "119" in result.reply and result.urgent == "medical"


def test_a_model_failure_on_an_ordinary_message_is_unavailable_not_a_fake_answer():
    service, _, _ = make(FakeModel(fail=True))
    with pytest.raises(ChatUnavailable):
        service.send(12, "안녕")

    empty, _, _ = make(FakeModel(answer="   "))
    with pytest.raises(ChatUnavailable):
        empty.send(12, "안녕")


def test_without_a_model_the_chat_is_closed():
    service = ChatService(store=InMemoryChatStore(), model=None)
    assert service.available is False
    with pytest.raises(ChatUnavailable):
        service.send(12, "안녕")


def test_a_failing_alerter_does_not_stop_the_answer_and_is_retried_next_time():
    calls = []

    def flaky(elder_id, category):
        calls.append(category)
        if len(calls) == 1:
            raise RuntimeError("푸시 서버 죽음")
        return True

    service, clock, _ = make(on_urgent=flaky)

    first = service.send(12, "가슴이 아파요")
    clock.now += 30
    service.send(12, "가슴이 아파요 정말")

    assert "119" in first.reply
    assert len(calls) == 2  # 첫 번째 실패는 '알렸다'로 남지 않아 다시 시도한다


def test_the_daily_limit_protects_the_bill():
    service, _, _ = make()
    for _ in range(DAILY_LIMIT):
        service.send(12, "응")
    with pytest.raises(ChatLimitReached):
        service.send(12, "응")
    service.send(13, "다른 어르신은 괜찮다")


def test_empty_messages_are_refused():
    service, _, _ = make()
    with pytest.raises(ValueError):
        service.send(12, "   ")


def test_summaries_are_made_only_for_finished_conversations_and_only_once():
    summarize_model = FakeModel("어르신이 날씨를 궁금해하셨어요.")
    summarizer = CallSummarizer(summarize_model, "bedrock-test")
    service, clock, _ = make(summarizer=summarizer)
    service.send(12, "오늘 날씨 어때요?")

    assert service.summaries(12) == []  # 아직 대화 중
    assert summarize_model.seen == []

    clock.now += SESSION_IDLE_SECONDS + 60
    listed = service.summaries(12)
    assert [s.summary for s in listed] == ["어르신이 날씨를 궁금해하셨어요."]
    service.summaries(12)
    assert len(summarize_model.seen) == 1  # 다시 열어도 다시 요약하지 않는다


def test_a_summary_with_a_forbidden_word_is_not_shown_and_not_retried():
    summarizer = CallSummarizer(FakeModel("우울해 보이세요."), "m")
    service, clock, _ = make(summarizer=summarizer)
    service.send(12, "심심해요")
    clock.now += SESSION_IDLE_SECONDS + 60

    assert service.summaries(12) == []
    assert service.summaries(12) == []


def test_a_summarizer_failure_is_retried_next_time():
    model = FakeModel(fail=True)
    service, clock, _ = make(summarizer=CallSummarizer(model, "m"))
    service.send(12, "심심해요")
    clock.now += SESSION_IDLE_SECONDS + 60

    assert service.summaries(12) == []
    model.fail = False
    model.answer = "어르신이 심심하다고 하셨어요."
    assert [s.summary for s in service.summaries(12)] == ["어르신이 심심하다고 하셨어요."]


def test_old_messages_are_purged_after_thirty_days():
    service, clock, _ = make()
    service.send(12, "옛날 말")
    session = service._store.session_for(12, clock.now, SESSION_IDLE_SECONDS)
    clock.now += 31 * 86400

    # 아무도 새 말을 보내지 않아도 지워진다 — 채팅을 그만둔 어르신의 원문도 30일에 지워야 한다.
    assert service.purge_expired() == 2  # 어르신의 말과 AI의 답
    assert service._store.history(session, 10) == []


def test_the_alerter_writes_one_alert_per_guardian_without_the_words_and_pushes_each():
    from app.api.alerts import InMemoryAlertStore

    class Access:
        guardian_ids = (1, 2)

    class Elders:
        def get(self, elder_id):
            return Access() if elder_id == 12 else None

    class Notifier:
        def __init__(self):
            self.sent = []

        def notify_chat_urgent(self, guardian_id, elder_id):
            self.sent.append((guardian_id, elder_id))

    alerts, notifier = InMemoryAlertStore(), Notifier()
    alert = make_urgent_alerter(elders=Elders(), alerts=alerts, notifier=notifier)

    alert(12, "medical")

    for guardian_id in (1, 2):
        (record,) = alerts.recent_for_guardian(guardian_id, 10)
        assert record.alert_type == ALERT_TYPE and record.severity == "critical"
        assert record.message == GUARDIAN_ALERT_MESSAGE and record.call_id is None
    assert notifier.sent == [(1, 12), (2, 12)]
    alert(999, "medical")  # 모르는 어르신은 조용히 넘어간다


def test_the_purger_thread_deletes_expired_text_without_any_chat_and_stops_cleanly():
    import time as _time

    service, clock, _ = make()
    service.send(12, "옛날 말")
    session = service._store.session_for(12, clock.now, SESSION_IDLE_SECONDS)
    clock.now += 31 * 86400

    service.start()
    deadline = _time.time() + 5
    while service._store.history(session, 10) and _time.time() < deadline:
        _time.sleep(0.02)
    service.stop()

    assert service._store.history(session, 10) == []
    assert service._thread is None


def test_an_alerter_that_reaches_nobody_is_not_remembered_so_the_next_message_tries_again():
    calls = []

    def nobody(elder_id, category):
        calls.append(category)
        return False  # 보호자가 없거나 모두 실패했다

    service, clock, _ = make(on_urgent=nobody)
    service.send(12, "가슴이 아파요")
    clock.now += 30
    service.send(12, "가슴이 아파요 정말")

    assert len(calls) == 2


def test_a_different_urgent_category_alerts_again_the_same_day():
    service, clock, alerts = make()

    service.send(12, "가슴이 아파요")
    clock.now += 60
    service.send(12, "더는 못 살겠어요. 죽고 싶어요")

    assert alerts == [(12, "medical"), (12, "self_harm")]


def test_an_urgent_message_still_alerts_and_gets_the_notice_after_the_daily_limit_without_calling_the_model():
    model = FakeModel()
    service, _, alerts = make(model)
    for _ in range(DAILY_LIMIT):
        service.send(12, "응")
    calls_before = len(model.seen)

    result = service.send(12, "가슴이 너무 아파요")

    assert alerts == [(12, "medical")]
    assert result.urgent == "medical" and "119" in result.reply
    assert len(model.seen) == calls_before  # 한도를 넘었으니 모델 요금은 늘지 않는다
    with pytest.raises(ChatLimitReached):
        service.send(12, "그냥 이야기")


def test_an_urgent_message_alerts_even_when_there_is_no_model():
    service = ChatService(store=InMemoryChatStore(), model=None, on_urgent=lambda e, c: True)

    result = service.send(12, "숨이 안 쉬어져요")
    assert result.urgent == "medical" and "119" in result.reply
    with pytest.raises(ChatUnavailable):
        service.send(12, "그냥 이야기")


def test_an_urgent_phrase_past_the_stored_length_is_still_found_and_the_stored_text_is_cut():
    service, _, alerts = make()
    long_text = "오늘은 " + "그냥 이런저런 이야기를 해요. " * 30 + "가슴이 아파요"
    assert len(long_text) > 300

    result = service.send(12, long_text)

    assert result.urgent == "medical" and alerts == [(12, "medical")]
    session = service._store.session_for(12, service._clock(), SESSION_IDLE_SECONDS)
    stored = service._store.history(session, 10)[0].text
    assert len(stored) == 300


def test_removing_an_elder_removes_their_chat_through_the_service():
    service, _, _ = make()
    service.send(12, "안녕")
    assert service.remove_for_elder(12) >= 1


def test_the_alerter_reports_false_when_nobody_could_be_alerted_and_true_when_only_the_push_fails():
    class Access:
        guardian_ids = (1, 2)

    class Elders:
        def get(self, elder_id):
            return Access()

    class BrokenAlerts:
        def raise_alert(self, **kwargs):
            raise RuntimeError("DB 끊김")

    class GoodAlerts:
        def __init__(self):
            self.rows = 0

        def raise_alert(self, **kwargs):
            self.rows += 1
            return True

    class BrokenNotifier:
        def notify_chat_urgent(self, guardian_id, elder_id):
            raise RuntimeError("푸시 서버 죽음")

    assert make_urgent_alerter(elders=Elders(), alerts=BrokenAlerts(), notifier=None)(12, "medical") is False
    good = GoodAlerts()
    assert make_urgent_alerter(elders=Elders(), alerts=good, notifier=BrokenNotifier())(12, "medical") is True
    assert good.rows == 2  # 푸시가 실패해도 두 보호자 모두 알림 기록은 남았다

    class NoGuardians:
        guardian_ids = ()

    class Empty:
        def get(self, elder_id):
            return NoGuardians()

    assert make_urgent_alerter(elders=Empty(), alerts=good, notifier=None)(12, "medical") is False


def test_urgent_messages_beyond_the_reserve_are_not_stored_but_still_get_the_notice_without_the_model():
    from app.chat.service import URGENT_RESERVE

    model = FakeModel()
    service, _, alerts = make(model)
    for _ in range(DAILY_LIMIT):
        service.send(12, "응")
    calls_before = len(model.seen)

    replies = [service.send(12, "가슴이 아파요") for _ in range(URGENT_RESERVE + 30)]

    assert all("119" in r.reply and r.urgent == "medical" for r in replies)
    assert len(model.seen) == calls_before  # 한도를 넘은 뒤에는 모델을 부르지 않는다
    assert alerts == [(12, "medical")]
    stored = service._store.elder_messages_since(12, 0)
    assert stored <= DAILY_LIMIT + URGENT_RESERVE  # 저장량에 상한이 있다


def test_a_new_urgent_category_past_the_reserve_is_still_alerted_and_stored_once():
    from app.chat.service import URGENT_RESERVE

    service, _, alerts = make()
    for _ in range(DAILY_LIMIT):
        service.send(12, "응")
    for _ in range(URGENT_RESERVE + 5):
        service.send(12, "가슴이 아파요")
    before = service._store.elder_messages_since(12, 0)

    result = service.send(12, "더는 못 살겠어요. 죽고 싶어요")

    assert result.urgent == "self_harm" and "109" in result.reply
    assert alerts == [(12, "medical"), (12, "self_harm")]
    assert service._store.elder_messages_since(12, 0) == before + 1  # 새 분류는 알림 표시를 위해 한 번 저장한다
    service.send(12, "죽고 싶어요 정말")
    assert service._store.elder_messages_since(12, 0) == before + 1  # 같은 분류는 더 저장하지 않는다


def test_the_summary_model_only_sees_a_bounded_recent_part_of_a_long_conversation():
    from app.chat.service import SUMMARY_MAX_CHARS, SUMMARY_MAX_TURNS

    seen = []

    class Recorder:
        model_id = "m"

        def summarize(self, turns):
            seen.append(list(turns))
            return "어르신이 이야기를 하셨어요."

    service, clock, _ = make(summarizer=Recorder())
    for i in range(150):
        service.send(12, f"{i}번째 이야기 " + "가" * 250)
    clock.now += SESSION_IDLE_SECONDS + 60

    service.summaries(12)

    (turns,) = seen
    assert len(turns) <= SUMMARY_MAX_TURNS
    assert sum(len(text) for _, text in turns) <= SUMMARY_MAX_CHARS
    assert "149번째" in turns[-1][1] or "149번째" in turns[-2][1]  # 최근 것이 남는다


def test_a_failing_alerter_cannot_keep_the_storage_growing_past_the_absolute_cap():
    from app.chat.service import URGENT_MARKER_ALLOWANCE, URGENT_RESERVE

    attempts = []

    def always_fails(elder_id, category):
        attempts.append(category)
        return False  # 보호자가 없거나 모두 실패한다 — '알렸다'로 표시되지 않는다

    model = FakeModel()
    service, _, _ = make(model, on_urgent=always_fails)
    for _ in range(DAILY_LIMIT):
        service.send(12, "응")
    calls_before = len(model.seen)

    replies = [service.send(12, "가슴이 아파요") for _ in range(URGENT_RESERVE + URGENT_MARKER_ALLOWANCE + 50)]

    assert all("119" in r.reply for r in replies)  # 안내는 계속 나간다
    assert service._store.elder_messages_since(12, 0) <= DAILY_LIMIT + URGENT_RESERVE + URGENT_MARKER_ALLOWANCE
    assert len(model.seen) == calls_before  # 한도를 넘었으니 모델은 부르지 않는다
    assert len(attempts) <= URGENT_RESERVE + URGENT_MARKER_ALLOWANCE  # 알림 시도도 무한하지 않다


def test_concurrent_requests_cannot_slip_past_the_daily_limit_or_the_absolute_cap():
    import threading
    import time as _time

    from app.chat.service import URGENT_MARKER_ALLOWANCE, URGENT_RESERVE

    class SlowStore(InMemoryChatStore):
        def elder_messages_since(self, elder_id, since):
            count = super().elder_messages_since(elder_id, since)
            _time.sleep(0.002)  # 읽기와 저장 사이를 넓혀 겹침을 드러낸다
            return count

    cap = DAILY_LIMIT + URGENT_RESERVE + URGENT_MARKER_ALLOWANCE
    model = FakeModel()
    service = ChatService(
        store=SlowStore(), model=model, on_urgent=lambda e, c: False, clock=Clock()  # 알림은 계속 실패한다
    )
    for _ in range(DAILY_LIMIT - 5):
        service.send(12, "응")

    start = threading.Barrier(60)
    errors = []

    def worker(urgent):
        start.wait()
        try:
            service.send(12, "가슴이 아파요" if urgent else "응")
        except (ChatLimitReached, ChatUnavailable):
            pass
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i % 2 == 0,)) for i in range(60)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    stored = service._store.elder_messages_since(12, 0)
    assert stored <= cap
    # 평범한 말은 한도(200) 안에서만 받는다 — 겹친 요청이 한도를 넘기지 못한다
    ordinary = [m for m in service._store.history(service._store.session_for(12, service._clock(), SESSION_IDLE_SECONDS), 1000) if m.role == "elder" and m.text == "응"]
    assert len(ordinary) <= DAILY_LIMIT
