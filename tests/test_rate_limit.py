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


# ------------------------------------------------ 이메일별 실패 한도 (보호자 로그인)


from app.api.rate_limit import KeyedFailureLimiter  # noqa: E402


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_keyed_limiter_blocks_only_the_key_that_failed_enough():
    clock = _Clock()
    limiter = KeyedFailureLimiter(limit=3, window_seconds=900, clock=clock)
    for _ in range(3):
        limiter.record_failure("a@example.com")
    assert limiter.blocked("a@example.com") is True
    assert limiter.blocked("b@example.com") is False


def test_keyed_limiter_stays_open_below_the_limit():
    limiter = KeyedFailureLimiter(limit=3, window_seconds=900, clock=_Clock())
    limiter.record_failure("a@example.com")
    limiter.record_failure("a@example.com")
    assert limiter.blocked("a@example.com") is False


def test_keyed_limiter_forgets_after_the_window():
    clock = _Clock()
    limiter = KeyedFailureLimiter(limit=2, window_seconds=900, clock=clock)
    limiter.record_failure("a")
    limiter.record_failure("a")
    assert limiter.blocked("a") is True
    clock.now += 901
    assert limiter.blocked("a") is False


def test_keyed_limiter_clear_resets_a_key():
    limiter = KeyedFailureLimiter(limit=2, window_seconds=900, clock=_Clock())
    limiter.record_failure("a")
    limiter.record_failure("a")
    limiter.clear("a")
    assert limiter.blocked("a") is False


def test_keyed_limiter_does_not_grow_without_bound():
    clock = _Clock()
    limiter = KeyedFailureLimiter(limit=5, window_seconds=10, clock=clock, max_keys=100)
    for i in range(1000):
        clock.now += 0.001
        limiter.record_failure(f"k{i}")
    assert limiter.tracked() <= 100
