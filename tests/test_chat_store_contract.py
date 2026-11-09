"""ChatStore 규약 — 구현마다 같은 테스트를 돌린다."""

from __future__ import annotations

import pytest

from app.chat.store import InMemoryChatStore
from tests.pg_helpers import DATABASE_URL

NOW = 1_800_000_000.0
IDLE = 1800.0


def _memory():
    return InMemoryChatStore()


def _postgres():
    from app.chat.postgres_store import PostgresChatStore
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)
    return PostgresChatStore(pool=pool)


@pytest.fixture(
    params=[
        "memory",
        pytest.param("postgres", marks=pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다")),
    ]
)
def store(request):
    return _memory() if request.param == "memory" else _postgres()


def say(store, session, role, text, now, urgent=None):
    return store.add_message(session, role, text, now, urgent)


def test_a_conversation_continues_while_it_is_recent_and_starts_anew_after_a_pause(store):
    first = store.session_for(12, NOW, IDLE)
    say(store, first, "elder", "안녕", NOW)

    assert store.session_for(12, NOW + 600, IDLE) == first
    assert store.session_for(12, NOW + IDLE + 60, IDLE) != first


def test_sessions_belong_to_one_elder(store):
    assert store.session_for(12, NOW, IDLE) != store.session_for(13, NOW, IDLE)


def test_history_is_the_last_messages_oldest_first(store):
    session = store.session_for(12, NOW, IDLE)
    for i in range(5):
        say(store, session, "elder" if i % 2 == 0 else "ai", f"말{i}", NOW + i)

    assert [m.text for m in store.history(session, 3)] == ["말2", "말3", "말4"]
    assert [m.role for m in store.history(session, 3)] == ["elder", "ai", "elder"]


def test_it_counts_only_what_the_elder_sent_since_the_given_time(store):
    session = store.session_for(12, NOW, IDLE)
    say(store, session, "elder", "하나", NOW)
    say(store, session, "ai", "답", NOW + 1)
    say(store, session, "elder", "둘", NOW + 100)
    other = store.session_for(13, NOW, IDLE)
    say(store, other, "elder", "남의 말", NOW + 2)

    assert store.elder_messages_since(12, NOW) == 2
    assert store.elder_messages_since(12, NOW + 50) == 1
    assert store.elder_messages_since(13, NOW) == 1


def test_it_remembers_whether_an_urgent_alert_already_went_out(store):
    session = store.session_for(12, NOW, IDLE)
    first = say(store, session, "elder", "가슴이 아파요", NOW, urgent="medical")
    assert store.alerted_since(12, NOW - 10, "medical") is False

    store.mark_alerted(first, NOW + 5)

    assert store.alerted_since(12, NOW - 10, "medical") is True
    assert store.alerted_since(12, NOW + 6, "medical") is False
    assert store.alerted_since(13, NOW - 10, "medical") is False
    # 다른 분류는 따로 센다 — 가슴 통증을 알렸다고 자살 표현까지 알린 것이 되지 않는다.
    assert store.alerted_since(12, NOW - 10, "self_harm") is False


def test_only_finished_unsummarized_sessions_with_an_elder_message_are_summarized(store):
    done = store.session_for(12, NOW, IDLE)
    say(store, done, "elder", "오늘 날씨 어때?", NOW)
    say(store, done, "ai", "맑아요", NOW + 1)
    live = store.session_for(12, NOW + 5000, IDLE)  # 새 덩이
    say(store, live, "elder", "지금 말하는 중", NOW + 5000)
    only_ai = store.session_for(13, NOW, IDLE)
    say(store, only_ai, "ai", "먼저 인사", NOW)

    ready = store.sessions_to_summarize(12, NOW + 5000 - 60, 5)
    assert ready == [done]  # live는 아직 끝나지 않았다
    assert store.sessions_to_summarize(13, NOW + 9999, 5) == []  # 어르신 말이 없다
    assert store.transcript(done) == [("elder", "오늘 날씨 어때?"), ("ai", "맑아요")]


def test_a_failed_summary_is_not_retried_and_only_real_summaries_are_listed(store):
    a = store.session_for(12, NOW, IDLE)
    say(store, a, "elder", "하나", NOW)
    b = store.session_for(12, NOW + 5000, IDLE)
    say(store, b, "elder", "둘", NOW + 5000)

    store.save_summary(a, "어르신이 인사를 하셨어요.", "m", NOW + 9000)
    store.save_summary(b, None, "m", NOW + 9000)  # 요약할 수 없었다

    assert store.sessions_to_summarize(12, NOW + 99999, 5) == []
    listed = store.summaries(12, 10)
    assert [s.session_id for s in listed] == [a]
    assert listed[0].summary == "어르신이 인사를 하셨어요."
    assert store.summaries(13, 10) == []


def test_summaries_are_newest_first_and_limited(store):
    ids = []
    for i in range(3):
        session = store.session_for(12, NOW + i * 5000, IDLE)
        say(store, session, "elder", f"말{i}", NOW + i * 5000)
        store.save_summary(session, f"요약{i}", "m", NOW + 99999)
        ids.append(session)

    assert [s.session_id for s in store.summaries(12, 2)] == [ids[2], ids[1]]


def test_purging_removes_old_messages_but_keeps_summaries(store):
    old = store.session_for(12, NOW, IDLE)
    say(store, old, "elder", "오래된 말", NOW)
    store.save_summary(old, "요약", "m", NOW + 1)
    recent = store.session_for(12, NOW + 40 * 86400, IDLE)
    say(store, recent, "elder", "최근 말", NOW + 40 * 86400)

    removed = store.purge_messages_before(NOW + 30 * 86400)

    assert removed == 1
    assert store.history(old, 10) == []
    assert [m.text for m in store.history(recent, 10)] == ["최근 말"]
    assert [s.summary for s in store.summaries(12, 10)] == ["요약"]


def test_removing_an_elder_removes_their_conversations_and_summaries(store):
    session = store.session_for(12, NOW, IDLE)
    say(store, session, "elder", "안녕", NOW)
    store.save_summary(session, "요약", "m", NOW + 1)
    other = store.session_for(13, NOW, IDLE)
    say(store, other, "elder", "남의 말", NOW)

    assert store.remove_for_elder(12) == 1
    assert store.summaries(12, 10) == []
    assert store.elder_messages_since(13, NOW) == 1
