"""켜질 때 DB에 실제로 닿는지 본다 — 2026-09-30 RDS가 꺼진 채 서버가 떠 있었다."""

from __future__ import annotations

import logging
from contextlib import contextmanager

from app.api.db import check


class FakeConn:
    def __init__(self):
        self.sql = []

    def execute(self, sql):
        self.sql.append(sql)


class FakePool:
    def __init__(self, fail=False):
        self.fail = fail
        self.conn = FakeConn()
        self.timeouts = []

    @contextmanager
    def connection(self, timeout=None):
        self.timeouts.append(timeout)
        if self.fail:
            raise TimeoutError("couldn't get a connection after 10.00 sec")
        yield self.conn


def test_a_reachable_database_passes():
    pool = FakePool()

    assert check(pool) is True
    assert pool.conn.sql == ["SELECT 1"]


def test_an_unreachable_database_is_reported_loudly(caplog):
    with caplog.at_level(logging.ERROR, logger="app.api.db"):
        ok = check(FakePool(fail=True))

    assert ok is False
    assert "DB에 연결할 수 없다" in caplog.text
    assert "stopped" in caplog.text


def test_an_unreachable_database_does_not_stop_the_server():
    """예외를 밖으로 던지지 않는다. 풀은 DB가 돌아오면 다시 붙는다."""
    check(FakePool(fail=True))


def test_the_check_does_not_wait_forever():
    pool = FakePool()

    check(pool, timeout=3.0)

    assert pool.timeouts == [3.0]
