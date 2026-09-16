"""Telephony 규약 (전화망 설계 4.2).

FakeTelephony로 트리거 API 전체를 ClawOps 계정 없이 테스트한다 —
계정 신청이 끝나기 전에 구현을 끝낼 수 있다.
"""

import pytest

from app.telephony.client import FakeTelephony


def test_fake_records_what_was_asked():
    telephony = FakeTelephony()
    sid = telephony.place_call(to="070-1234-5678", answer_url="https://x/voiceml")

    assert telephony.placed == [("070-1234-5678", "https://x/voiceml")]
    assert sid.startswith("CA")


def test_each_call_gets_a_distinct_sid():
    """같은 SID가 두 번 나오면 DB의 UNIQUE 제약에 걸린다."""
    telephony = FakeTelephony()
    first = telephony.place_call(to="070-1", answer_url="https://x")
    second = telephony.place_call(to="070-2", answer_url="https://x")
    assert first != second


def test_fake_can_be_told_to_fail():
    """발신 실패는 정상적으로 일어난다. API가 그걸 다룰 수 있어야 한다."""
    telephony = FakeTelephony(fail_with=RuntimeError("사업자 오류"))
    with pytest.raises(RuntimeError):
        telephony.place_call(to="070-1", answer_url="https://x")
