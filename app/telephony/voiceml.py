"""VoiceML 생성 (전화망 설계 2장).

ClawOps가 어르신 응답 후 우리 Url로 POST하면 이 XML을 돌려준다.
순수한 문자열 변환이라 계정 없이 검증된다.
"""

from __future__ import annotations

from xml.sax.saxutils import quoteattr


def connect_stream(stream_url: str, action_url: str, token: str) -> str:
    """통화 오디오를 우리 소켓으로 끌어온다.

    track="inbound"는 ClawOps가 지원하는 유일한 값이자 우리가 원하는 값이다 —
    어르신 트랙만 온다. 이것이 Asterisk 없이 얻는 화자 분리다(설계 1장).

    action을 반드시 넣는다. 없으면 스트림이 끊기는 순간 통화가 즉시 끝나
    우리 서버 버그가 곧바로 어르신의 전화 끊김이 된다(설계 8장).
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Connect action={quoteattr(action_url)}>"
        f"<Stream url={quoteattr(stream_url)} track=\"inbound\">"
        f"<Parameter name=\"token\" value={quoteattr(token)}/>"
        "</Stream>"
        "</Connect>"
        "</Response>"
    )


def say_and_hangup(text: str, language: str = "ko") -> str:
    """스트림이 끝난 뒤 마무리 인사를 하고 끊는다."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Say language={quoteattr(language)}>{_escape_text(text)}</Say>"
        "<Hangup/>"
        "</Response>"
    )


def _escape_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
