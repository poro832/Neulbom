"""인증 없는 요청에서 온 값을 로그에 찍기 전의 정리.

바깥에 열린 주소(전화망 웹훅)의 폼 값을 그대로 찍으면, 값에 줄바꿈을 넣어 진짜처럼 보이는
로그 줄을 끼워 넣거나 로그를 한없이 부풀릴 수 있다.
"""

from __future__ import annotations

DEFAULT_LIMIT = 64


def sanitize_for_log(value: object, limit: int = DEFAULT_LIMIT) -> str:
    """줄바꿈과 제어 문자를 공백으로 바꾸고 limit글자로 자른다(잘리면 끝에 …)."""
    text = "".join(" " if (ord(ch) < 32 or ord(ch) == 127) else ch for ch in str(value))
    if len(text) > limit:
        text = text[:limit] + "…"
    return text
