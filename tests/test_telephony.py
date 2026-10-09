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
    # callId는 없지만 원본 본문이 그대로 남아 있어야 실제 필드명을 알 수 있다.
    assert "abc123" in message


def test_the_call_id_is_read_from_the_documented_field(monkeypatch):
    """공식 문서의 응답은 callId(camelCase)다. call_id로 읽으면 전화가 나간
    뒤에 실패한다."""
    response = _fake_response(
        status_code=201, json={"callId": "CAabc123", "status": "queued"}
    )
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)

    assert _clawops().place_call(to="070-1", answer_url="https://x") == "CAabc123"


def test_numbers_are_sent_as_digits_only(monkeypatch):
    """ClawOps는 번호를 07052767846처럼 숫자만으로 저장한다."""
    sent = {}

    def fake_post(url, **kwargs):
        sent["url"] = url
        sent["headers"] = kwargs["headers"]
        sent["data"] = kwargs["data"]
        return _fake_response(status_code=201, json={"callId": "CAx"})

    monkeypatch.setattr(httpx, "post", fake_post)

    _clawops().place_call(to="010-3447-2884", answer_url="https://x/voiceml")

    assert sent["data"]["To"] == "01034472884"
    assert sent["data"]["From"] == "07000000000"
    assert sent["url"].endswith("/v1/accounts/AC1/calls")
    assert sent["headers"]["Authorization"] == "Bearer key"


def test_a_carrier_refusal_carries_its_reason(monkeypatch):
    """2026-10-09: 400 Bad Request만 남아서 원인이 발신번호라는 것을 번호 목록까지
    조회해서야 알았다. 사업자가 보낸 거절 사유를 예외와 로그에 남긴다."""
    response = _fake_response(
        status_code=400,
        text='{"error":{"code":"InvalidFrom","message":"From number not owned by account"}}',
    )
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)

    with pytest.raises(RuntimeError) as excinfo:
        _clawops().place_call(to="070-1", answer_url="https://x")

    message = str(excinfo.value)
    assert "400" in message
    assert "From number not owned by account" in message
