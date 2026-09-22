"""CallStore 규약 — 두 구현에 같은 테스트를 돌린다.

**왜 이 파일이 있는가.** 저장소가 둘이 되면 조용히 갈라진다. 이 프로젝트는
이미 그 방식으로 당한 적이 있다 — `_ExplodingOutcomeStore`가 새 인자를 안
받아서, 테스트는 통과하는데 검증하려던 경로에 도달하지 못한 채로 있었다.
저장소는 그보다 훨씬 큰 대역이다. 갈라지면 "테스트는 다 통과하는데 서버에서만
점수가 틀린" 상황이 된다.

**약점을 숨기지 않는다.** Postgres 쪽은 `DATABASE_URL`이 없으면 건너뛴다.
건너뛰는 테스트는 아무것도 지키지 않는다 — Docker가 꺼져 있으면 두 구현이
갈라져도 조용히 통과한다. 커밋 전 한 번은 `DATABASE_URL`을 준 채로 돌려야
한다. CI가 생기면 거기서 강제하는 것이 맞고, 지금 없는 것을 있는 척하지 않는다.
"""

from __future__ import annotations

import os

import pytest

from app.api.store import ACTIVE_STATUSES, InMemoryCallStore

ELDER = 12
PHONES = {ELDER: "070-1111-2222", 99: "070-9999-9999"}

DATABASE_URL = os.getenv("DATABASE_URL")


# ------------------------------------------------------------ 두 구현 붙이기


def _memory_store(**kwargs):
    return InMemoryCallStore(phones=PHONES, **kwargs)


def _postgres_store(**kwargs):
    from app.api.db import connect
    from app.api.postgres_store import PostgresCallStore

    pool = connect(DATABASE_URL)
    store = PostgresCallStore(pool=pool, phones=PHONES, **kwargs)
    store.reset_for_tests()
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DATABASE_URL,
                reason="DATABASE_URL이 없다 — Postgres 규약 테스트를 건너뛴다. "
                "두 구현이 갈라져도 이 실행은 잡지 못한다.",
            ),
        ),
    ]
)
def make_store(request):
    """구현을 고르는 팩토리. 시계나 만료 시간을 바꿔야 하는 테스트가 있어
    저장소 자체가 아니라 만드는 함수를 돌려준다."""
    return _memory_store if request.param == "memory" else _postgres_store


@pytest.fixture
def store(make_store):
    return make_store()


# ------------------------------------------------------------ 기본


def test_an_unknown_elder_has_no_phone(store):
    assert store.find_elder(4242) is None


def test_a_known_elder_has_a_phone(store):
    assert store.find_elder(ELDER) == "070-1111-2222"


def test_a_created_call_starts_scheduled(store):
    call = store.create(elder_id=ELDER, trigger_type="requested")

    assert call.elder_id == ELDER
    assert call.trigger_type == "requested"
    assert call.status == "scheduled"
    assert call.provider_call_sid is None
    assert call.audio_key is None


def test_get_returns_what_was_created(store):
    call = store.create(elder_id=ELDER, trigger_type="scheduled")

    assert store.get(call.call_id) == call


def test_get_raises_for_an_unknown_call(store):
    with pytest.raises(KeyError):
        store.get(999_999)


def test_call_ids_do_not_repeat(store):
    ids = {store.create(ELDER, "requested").call_id for _ in range(3)}

    assert len(ids) == 3


# ------------------------------------------------------------ 활성 통화


def test_an_elder_without_a_call_has_nothing_active(store):
    assert store.find_active(ELDER) is None


def test_a_new_call_is_active(store):
    call = store.create(ELDER, "requested")

    assert store.find_active(ELDER).call_id == call.call_id


def test_a_finished_call_is_not_active(store):
    call = store.create(ELDER, "requested")
    store.mark_no_answer(call.call_id)

    assert store.find_active(ELDER) is None


def test_find_active_or_create_returns_the_existing_call(store):
    """같은 어르신에게 두 통이 동시에 걸리면 안 된다. 두 번째 요청은 새
    통화를 만드는 대신 진행 중인 것을 돌려받아야 한다 — 그래야 API가
    409로 답할 수 있다."""
    first, created_first = store.find_active_or_create(ELDER, "requested")
    second, created_second = store.find_active_or_create(ELDER, "requested")

    assert created_first is True
    assert created_second is False
    assert second.call_id == first.call_id


def test_find_active_or_create_makes_a_new_call_after_the_last_one_ended(store):
    first, _ = store.find_active_or_create(ELDER, "requested")
    store.mark_no_answer(first.call_id)

    second, created = store.find_active_or_create(ELDER, "requested")

    assert created is True
    assert second.call_id != first.call_id


def test_one_elders_call_does_not_block_another(store):
    store.find_active_or_create(ELDER, "requested")

    _, created = store.find_active_or_create(99, "requested")

    assert created is True


# ------------------------------------------------------------ 사업자 식별자


def test_a_call_can_be_found_by_the_carrier_id(store):
    """웹훅은 우리 call_id를 모른다. 사업자 식별자만 들고 온다."""
    call = store.create(ELDER, "requested")
    store.attach_sid(call.call_id, "SID-1")

    assert store.find_by_sid("SID-1").call_id == call.call_id


def test_an_unknown_carrier_id_finds_nothing(store):
    assert store.find_by_sid("SID-없음") is None


# ------------------------------------------------------------ 상태 전이


def test_answered_means_our_stream_attached(store):
    call = store.create(ELDER, "requested")
    store.mark_answered(call.call_id)

    assert store.get(call.call_id).status == "answered"


def test_completed_keeps_the_audio_key(store):
    """끝난 통화에는 분석할 오디오가 있어야 한다 — 스키마도 같은 규칙을
    제약으로 막는다. 없으면 분석 파이프라인이 조용히 멈춘다."""
    call = store.create(ELDER, "requested")
    store.mark_completed(call.call_id, "12-20260922-abcd.wav")

    saved = store.get(call.call_id)
    assert saved.status == "completed"
    assert saved.audio_key == "12-20260922-abcd.wav"


def test_no_answer_and_failed_are_distinct(store):
    a = store.create(ELDER, "requested")
    store.mark_no_answer(a.call_id)
    store.mark_completed(a.call_id, "x.wav")  # 끝난 통화는 다시 안 바뀐다

    b = store.create(99, "requested")
    store.mark_failed(b.call_id)

    assert store.get(a.call_id).status == "no_answer"
    assert store.get(b.call_id).status == "failed"


def test_a_finished_call_does_not_change_again(store):
    """늦게 온 웹훅이 방금 끝난 통화를 되돌리면 안 된다. 웹훅과 스트림
    종료는 순서가 보장되지 않는다."""
    call = store.create(ELDER, "requested")
    store.mark_completed(call.call_id, "x.wav")

    store.mark_no_answer(call.call_id)

    assert store.get(call.call_id).status == "completed"


# ------------------------------------------------------------ 예약 통화 이력


def _finished_scheduled(store, elder_id, status):
    call = store.create(elder_id, "scheduled")
    if status == "no_answer":
        store.mark_no_answer(call.call_id)
    else:
        store.mark_completed(call.call_id, f"{call.call_id}.wav")
    return call


def test_recent_scheduled_is_newest_first(store):
    ids = [_finished_scheduled(store, ELDER, "completed").call_id for _ in range(3)]

    got = [c.call_id for c in store.recent_scheduled(ELDER, 10)]

    assert got == list(reversed(ids))


def test_requested_calls_are_not_counted(store):
    """요청 통화의 미응답은 '버튼을 누르고 전화기를 못 찾았다'일 뿐이다.
    위험 신호로 세면 활발한 어르신이 오히려 감점된다."""
    requested = store.create(ELDER, "requested")
    store.mark_no_answer(requested.call_id)

    assert store.recent_scheduled(ELDER, 10) == []


def test_unfinished_calls_are_not_counted(store):
    store.create(ELDER, "scheduled")

    assert store.recent_scheduled(ELDER, 10) == []


def test_another_elders_calls_are_not_counted(store):
    _finished_scheduled(store, 99, "no_answer")

    assert store.recent_scheduled(ELDER, 10) == []


def test_recent_scheduled_respects_the_limit(store):
    for _ in range(5):
        _finished_scheduled(store, ELDER, "completed")

    assert len(store.recent_scheduled(ELDER, 2)) == 2


def test_before_call_id_excludes_itself_and_later_calls(store):
    """전사가 늦게 끝나면 sink가 몇십 분 뒤에 돈다. 그사이 같은 어르신의
    다음 예약 통화가 먼저 no_answer로 끝날 수 있는데, 그 통화를 과거 통화의
    집계에 넣으면 과거 점수에 최대 20점이 붙는다. 아무 오류도 나지 않는다."""
    first = _finished_scheduled(store, ELDER, "completed")
    middle = _finished_scheduled(store, ELDER, "no_answer")
    _finished_scheduled(store, ELDER, "no_answer")

    got = [c.call_id for c in store.recent_scheduled(ELDER, 10, before_call_id=middle.call_id)]

    assert got == [first.call_id]


def test_the_limit_is_applied_after_the_cut(store):
    """잘라내기가 먼저고 창이 나중이다. 반대로 하면 최근 N통을 고른 뒤
    거기서 미래 통화를 빼게 되어 표본이 N보다 적어진다."""
    ids = [_finished_scheduled(store, ELDER, "completed").call_id for _ in range(5)]

    got = [c.call_id for c in store.recent_scheduled(ELDER, 2, before_call_id=ids[4])]

    assert got == [ids[3], ids[2]]


# ------------------------------------------------------------ 바닥 시간


def test_stale_expiry_uses_the_injected_clock(make_store):
    ticks = [0.0]
    store = make_store(clock=lambda: ticks[0], max_active_seconds=60.0)

    first, _ = store.find_active_or_create(ELDER, "scheduled")
    ticks[0] = 61.0

    second, created = store.find_active_or_create(ELDER, "scheduled")

    assert created is True, "바닥 시간이 지났으면 새 통화가 생겨야 한다"
    assert second.call_id != first.call_id
    assert store.get(first.call_id).status == "failed"


def test_an_expiry_listener_hears_folded_calls(make_store):
    """상태만 옮기고 끝내면 그 통화의 스트림 토큰이 계속 살아 있다.
    인증 없는 /v1/voiceml에서 꺼내진다 — 접은 기록을 리스너에게 넘겨
    lifecycle이 토큰까지 닫게 한다."""
    heard = []
    ticks = [0.0]
    store = make_store(clock=lambda: ticks[0], max_active_seconds=60.0)
    store.add_expiry_listener(heard.append)

    first, _ = store.find_active_or_create(ELDER, "scheduled")
    ticks[0] = 61.0
    store.find_active_or_create(ELDER, "scheduled")

    assert [c.call_id for c in heard] == [first.call_id]


def test_a_fresh_active_call_is_not_folded(make_store):
    ticks = [0.0]
    store = make_store(clock=lambda: ticks[0], max_active_seconds=60.0)

    first, _ = store.find_active_or_create(ELDER, "scheduled")
    ticks[0] = 59.0

    second, created = store.find_active_or_create(ELDER, "scheduled")

    assert created is False
    assert second.call_id == first.call_id


# ------------------------------------------------------------ 상태 목록


def test_active_statuses_are_the_ones_that_block_a_new_call(store):
    """ACTIVE_STATUSES가 이 저장소의 '잠김' 정의다. 값이 바뀌면 409 경로가
    통째로 달라지므로 여기 고정한다."""
    assert ACTIVE_STATUSES == frozenset({"scheduled", "ringing", "answered"})
