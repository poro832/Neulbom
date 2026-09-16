"""VoiceML 생성 (전화망 설계 2장).

ClawOps가 우리 Url로 POST하면 XML을 돌려줘야 한다. 순수한 문자열 변환이라
계정 없이 전부 검증된다.
"""

from xml.etree import ElementTree

from app.telephony.voiceml import connect_stream, say_and_hangup


def test_connect_stream_has_the_required_shape():
    xml = connect_stream(
        stream_url="wss://example.com/v1/stream",
        action_url="https://example.com/stream-ended",
        token="tok123",
    )
    root = ElementTree.fromstring(xml)

    assert root.tag == "Response"
    connect = root.find("Connect")
    assert connect.get("action") == "https://example.com/stream-ended"

    stream = connect.find("Stream")
    assert stream.get("url") == "wss://example.com/v1/stream"
    # ClawOps는 inbound 트랙만 지원한다. 이게 우리의 화자 분리다.
    assert stream.get("track") == "inbound"

    parameter = stream.find("Parameter")
    assert parameter.get("name") == "token"
    assert parameter.get("value") == "tok123"


def test_action_is_always_present():
    """action이 없으면 스트림이 끊기는 순간 통화가 즉시 끝난다.

    우리 서버 버그가 곧바로 어르신의 전화 끊김이 된다(설계 8장).
    """
    xml = connect_stream(
        stream_url="wss://example.com/s",
        action_url="https://example.com/a",
        token="t",
    )
    assert ElementTree.fromstring(xml).find("Connect").get("action")


def test_special_characters_are_escaped():
    """이스케이프를 빠뜨리면 XML이 깨져 통화가 시작조차 안 된다."""
    xml = connect_stream(
        stream_url="wss://example.com/s?a=1&b=2",
        action_url="https://example.com/a",
        token='t"&<>',
    )
    stream = ElementTree.fromstring(xml).find("Connect").find("Stream")
    assert stream.get("url") == "wss://example.com/s?a=1&b=2"
    assert stream.find("Parameter").get("value") == 't"&<>'


def test_say_and_hangup_is_korean_by_default():
    xml = say_and_hangup("안녕히 계세요")
    root = ElementTree.fromstring(xml)
    assert root.find("Say").text == "안녕히 계세요"
    assert root.find("Say").get("language") == "ko"
    assert root.find("Hangup") is not None
