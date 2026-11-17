"""AI 친구 이름(앱에서 어르신이 지은 이름)을 모델에 넘기기 전에 거른다.

이름은 모델 지시문(시스템 프롬프트)에 들어간다. 어르신 폰에서 온 글이라 믿지 않는다 —
한글·영문·숫자·공백만 남기고 12자까지 자른다. 따옴표·줄바꿈·기호가 없으니 지시문을 바꿔 쓸 수 없다.
"""

from __future__ import annotations

import re

MAX_PERSONA_CHARS = 12
_NOT_ALLOWED = re.compile(r"[^0-9A-Za-z가-힣 ]")


def clean_persona(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    kept = " ".join(_NOT_ALLOWED.sub("", value).split())[:MAX_PERSONA_CHARS].strip()
    return kept or None
