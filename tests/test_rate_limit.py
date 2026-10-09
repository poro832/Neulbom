"""FailureLimiter — 틀린 가입 시도가 한도를 넘으면 잠시 막는다."""

from __future__ import annotations

from app.api.rate_limit import FailureLimiter


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


def test_it_blocks_only_after_the_limit_is_reached():
    limiter = FailureLimiter(limit=3, clock=Clock())

    for _ in range(2):
        limiter.record_failure()
    assert limiter.blocked() is False

    limiter.record_failure()
    assert limiter.blocked() is True


def test_failures_expire_after_the_window():
    clock = Clock()
    limiter = FailureLimiter(limit=2, window_seconds=60, clock=clock)
    limiter.record_failure()
    limiter.record_failure()
    assert limiter.blocked() is True

    clock.now += 61

    assert limiter.blocked() is False


def test_a_failure_just_inside_the_window_still_counts():
    clock = Clock()
    limiter = FailureLimiter(limit=1, window_seconds=60, clock=clock)
    limiter.record_failure()

    clock.now += 59

    assert limiter.blocked() is True


def test_the_default_is_twenty_per_minute():
    limiter = FailureLimiter(clock=Clock())

    for _ in range(19):
        limiter.record_failure()
    assert limiter.blocked() is False

    limiter.record_failure()
    assert limiter.blocked() is True
