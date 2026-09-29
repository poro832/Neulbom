"""매일 아침 발신 스케줄러.

**미응답 20점이 여기에 달려 있습니다.** 예약 통화를 만드는 곳이 여기뿐이라,
이게 없으면 "안 받았다"가 발생할 수 없고 그 축은 영원히 0입니다.

시계를 쓰는 유일한 부분이기도 합니다. 이 프로젝트는 "시계가 점수에 닿으면
안 된다"를 지켜 왔는데, 그 규칙은 **점수 계산**에 대한 것입니다. 언제 전화를
걸지 정하는 데 시계를 쓰는 건 당연하고, 대신 그 시각이 점수 계산으로
흘러가지 않게 경계를 지킵니다.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest

from app.scheduler import (
    DEFAULT_GRACE_SECONDS,
    KST,
    RosterEntry,
    Scheduler,
    due_elders,
)

GRACE = timedelta(seconds=DEFAULT_GRACE_SECONDS)


def at(hour: int, minute: int = 0, *, day: int = 15) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=KST)


def entry(elder_id=1, call_time=time(9, 0), last=None) -> RosterEntry:
    return RosterEntry(elder_id=elder_id, call_time=call_time, last_scheduled_at=last)


# ------------------------------------------------------------ 언제 거는가


def test_exactly_at_the_call_time_is_due():
    assert due_elders([entry()], at(9, 0), grace=GRACE) == [1]


def test_before_the_call_time_is_not_due():
    """1분 전은 아직 아니다. 어르신 생활 리듬에 맞춘 시각이라 앞당기지 않는다."""
    assert due_elders([entry()], at(8, 59), grace=GRACE) == []


def test_inside_the_grace_window_is_still_due():
    """서버가 잠깐 꺼졌다 켜져도 그날 통화를 건진다."""
    assert due_elders([entry()], at(9, 29), grace=GRACE) == [1]


def test_past_the_grace_window_is_skipped():
    """아침 9시 안부 전화가 11시에 오면 그건 다른 제품이다.

    어르신 생활 리듬에 맞춰 거는 게 이 서비스의 전제인데, 늦은 전화는 그
    전제를 깬다. 5분 늦은 걸 버리는 것도 아까워서 유예를 뒀을 뿐이다.
    """
    assert due_elders([entry()], at(9, 31), grace=GRACE) == []


def test_the_grace_edge_is_inclusive():
    assert due_elders([entry()], at(9, 30), grace=GRACE) == [1]


# ------------------------------------------------------------ 하루 한 번


def test_an_elder_called_today_is_not_called_again():
    """재시작해도 '오늘 이미 걸었다'가 남아야 한다 — 어르신께 하루 두 번
    전화가 가는 건 버그가 아니라 실제 불편이다."""
    called = at(9, 0)

    assert due_elders([entry(last=called)], at(9, 10), grace=GRACE) == []


def test_yesterdays_call_does_not_block_today():
    assert due_elders([entry(last=at(9, 0, day=14))], at(9, 0), grace=GRACE) == [1]


def test_the_day_boundary_is_korean_time():
    """UTC로 날짜를 세면 한국 자정 직후 통화가 '어제'로 잡혀 하루 두 번
    걸리는 날이 생긴다."""
    # 한국시간 9/15 00:30 = UTC 9/14 15:30. 같은 한국 날짜이므로 막혀야 한다.
    called = datetime(2026, 9, 14, 15, 30, tzinfo=timezone.utc)

    assert due_elders([entry(call_time=time(0, 0), last=called)],
                      at(0, 40), grace=GRACE) == []


# ------------------------------------------------------------ 여러 어르신


def test_only_the_elders_whose_time_has_come():
    entries = [
        entry(1, time(9, 0)),
        entry(2, time(10, 0)),
        entry(3, time(9, 30)),
    ]

    assert due_elders(entries, at(9, 30), grace=GRACE) == [1, 3]


def test_an_empty_roster_is_not_an_error():
    assert due_elders([], at(9, 0), grace=GRACE) == []


# ------------------------------------------------------------ 루프


class FakeRoster:
    def __init__(self, entries):
        self._entries = entries
        self.reads = 0

    def entries(self):
        self.reads += 1
        return list(self._entries)


def test_a_tick_places_a_call_for_each_due_elder():
    placed = []
    scheduler = Scheduler(
        roster=FakeRoster([entry(1), entry(2, time(9, 0))]),
        place=placed.append,
        clock=lambda: at(9, 0),
    )

    assert scheduler.tick() == 2
    assert placed == [1, 2]


def test_one_elder_failing_does_not_stop_the_rest():
    """한 어르신 발신이 실패해도 나머지는 걸어야 한다. 아침에 한 번 도는
    루프라, 여기서 멈추면 뒤에 있는 어르신들은 그날 통화가 통째로 없어진다."""
    placed = []

    def place(elder_id):
        if elder_id == 1:
            raise RuntimeError("발신 실패")
        placed.append(elder_id)

    scheduler = Scheduler(
        roster=FakeRoster([entry(1), entry(2, time(9, 0)), entry(3, time(9, 0))]),
        place=place,
        clock=lambda: at(9, 0),
    )

    assert scheduler.tick() == 2
    assert placed == [2, 3]


def test_a_broken_roster_does_not_kill_the_loop(caplog):
    """DB가 잠깐 끊겨도 스케줄러 스레드는 살아 있어야 한다. 죽으면 그날
    남은 어르신 전부가 조용히 통화 없이 지나간다."""

    class Broken:
        def entries(self):
            raise RuntimeError("DB 연결 끊김")

    scheduler = Scheduler(roster=Broken(), place=lambda _: None, clock=lambda: at(9, 0))

    with caplog.at_level("ERROR", logger="app.scheduler"):
        assert scheduler.tick() == 0

    assert "명부를 읽지 못했다" in caplog.text


def test_start_and_stop_are_idempotent():
    scheduler = Scheduler(
        roster=FakeRoster([]), place=lambda _: None,
        clock=lambda: at(9, 0), tick_seconds=0.01,
    )

    scheduler.start()
    scheduler.start()
    scheduler.stop()
    scheduler.stop()


def test_the_loop_actually_ticks():
    placed = []
    roster = FakeRoster([entry(1)])
    scheduler = Scheduler(
        roster=roster, place=placed.append,
        clock=lambda: at(9, 0), tick_seconds=0.01,
    )

    scheduler.start()
    try:
        deadline = __import__("time").monotonic() + 2.0
        while not placed and __import__("time").monotonic() < deadline:
            __import__("time").sleep(0.01)
    finally:
        scheduler.stop()

    assert placed == [1]


# ------------------------------------------------------------ 조립부 배선


def test_the_server_runs_without_a_roster(tmp_path, caplog):
    """명부가 없으면 스케줄러를 안 켠다. 대신 조용히 넘어가지 않는다 —
    미응답 20점이 왜 0인지 나중에 찾을 수 있어야 한다."""
    import logging

    from tests.test_server_wiring import make_server

    with caplog.at_level(logging.INFO, logger="app.main"):
        make_server(tmp_path)

    assert "스케줄러를 켜지 않는다" in caplog.text


def test_a_scheduled_call_goes_out_through_the_real_path(tmp_path):
    """스케줄러가 부르면 **트리거 API와 같은 경로**로 전화가 나가야 한다.

    발신 뒤처리(토큰 발급 실패 시 복구)가 까다로워서 스케줄러가 따로
    구현하면 언젠가 갈라진다. 그래서 같은 dialer를 쓰는지 여기서 고정한다.
    """
    from fastapi.testclient import TestClient

    from app.api.store import InMemoryCallStore
    from app.main import build_server
    from app.telephony.client import FakeTelephony
    from tests.test_server_wiring import _Beep

    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    telephony = FakeTelephony()
    # build_server가 만드는 스케줄러는 진짜 시계를 쓴다. 그래서 명부가
    # "지금이 발신 시각"을 돌려주게 한다 — tick()이 entries()를 부른 직후
    # 같은 순간의 시계를 읽으므로 자정 근처에서도 흔들리지 않는다.
    class NowRoster:
        def entries(self):
            now = datetime.now(KST)
            return [RosterEntry(elder_id=12, call_time=now.time(),
                                last_scheduled_at=None)]

    roster = NowRoster()

    app = build_server(
        store=store,
        telephony=telephony,
        public_base_url="https://api.example.com",
        stream_base_url="wss://api.example.com",
        responder_factory=_Beep,
        recordings_dir=tmp_path,
        roster=roster,
    )

    with TestClient(app):
        deadline = __import__("time").monotonic() + 3.0
        while not telephony.placed and __import__("time").monotonic() < deadline:
            __import__("time").sleep(0.01)

    assert len(telephony.placed) == 1
    call = store.find_active(12) or store.get(1)
    assert call.trigger_type == "scheduled"


def test_a_scheduled_call_is_skipped_when_a_call_is_already_running(tmp_path):
    """어르신이 방금 앱에서 전화를 요청했는데 스케줄러가 한 통 더 걸면,
    어르신 쪽에서는 전화가 두 번 오는 것이다."""
    from app.api.dialer import place_scheduled_call
    from app.api.lifecycle import CallLifecycle
    from app.api.store import InMemoryCallStore
    from app.media.stream_server import InMemoryCallRegistry
    from app.telephony.client import FakeTelephony

    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    telephony = FakeTelephony()
    lifecycle = CallLifecycle(store, InMemoryCallRegistry())
    store.find_active_or_create(12, trigger_type="requested")

    place_scheduled_call(
        12, store=store, telephony=telephony,
        lifecycle=lifecycle, answer_url="https://api.example.com/v1/voiceml",
    )

    assert telephony.placed == []
