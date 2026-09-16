"""Telephony 규약 (전화망 설계 4.2).

FakeTelephony로 트리거 API 전체를 ClawOps 계정 없이 테스트한다 —
계정 신청이 끝나기 전에 구현을 끝낼 수 있다.
"""

import httpx
import pytest

from app.telephony.client import ClawOpsTelephony, FakeTelephony


def _clawops() -> ClawOpsTelephony:
    return ClawOpsTelephony(
        account_sid="AC1",
        api_key="key",
        from_number="070-0000-0000",
    )


def _fake_response(**kwargs) -> httpx.Response:
    # 직접 만든 Response는 request가 없으면 raise_for_status()가 그 사실 자체로
    # 예외를 던진다. 실제 httpx.post가 돌려주는 것과 같은 모양을 만들어야 한다.
    return httpx.Response(request=httpx.Request("POST", "https://x/calls"), **kwargs)


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


def test_non_json_response_error_carries_status_and_body(monkeypatch):
    """엔드포인트·인증·필드명이 전부 추측이라, 실제 API가 다르면 여기서 처음
    드러난다. 그때 팀원이 가진 단서는 이 에러 메시지뿐이어야 한다."""
    response = _fake_response(status_code=200, text="<html>Bad Gateway</html>")
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)

    with pytest.raises(RuntimeError) as excinfo:
        _clawops().place_call(to="070-1", answer_url="https://x")

    message = str(excinfo.value)
    assert "200" in message
    assert "Bad Gateway" in message


def test_missing_call_id_error_carries_status_and_body(monkeypatch):
    response = _fake_response(status_code=200, json={"id": "abc123"})
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)

    with pytest.raises(RuntimeError) as excinfo:
        _clawops().place_call(to="070-1", answer_url="https://x")

    message = str(excinfo.value)
    assert "200" in message
    # call_id는 없지만 원본 본문이 그대로 남아 있어야 실제 필드명을 알 수 있다.
    assert "abc123" in message
