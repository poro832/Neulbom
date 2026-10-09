"""전화 음성으로 나갈 말의 규칙이 프롬프트에 남아 있는가.

프롬프트는 문장이라 고치다 보면 규칙이 조용히 빠진다. 핵심 규칙이 들어
있는지만 지킨다 — 문구 전체를 고정하지는 않는다.
"""

from __future__ import annotations

from app.media.clova_chat import DEFAULT_SYSTEM_PROMPT as P


def test_the_prompt_says_the_words_go_out_as_voice():
    assert "전화 음성" in P


def test_the_prompt_keeps_the_core_rules():
    assert "존댓말" in P
    assert "진단이나 치료법은 말하지 않습니다" in P


def test_the_prompt_asks_for_speakable_text():
    for rule in ("스무 자", "소리 내어 읽는 대로", "기호를 쓰지 않습니다", "글자로 쓰지 않습니다"):
        assert rule in P


def test_the_prompt_asks_for_a_very_short_reply():
    """합성 시간은 답 길이에 비례한다(2026-10-09 실통화: 2.1초 → 5.6초). 어르신은
    답을 기다리는 침묵을 듣는다. 한두 문장, 마흔 자 안팎으로 묶는다."""
    assert "한두 문장" in P
    assert "마흔 자" in P
    assert "두세 문장" not in P


def test_the_token_cap_is_a_safety_net_for_short_replies():
    from app.media.clova_chat import DEFAULT_MAX_TOKENS

    # 프롬프트가 길이를 정하고, 상한은 모델이 길게 나가는 날을 막는 안전망이다.
    assert DEFAULT_MAX_TOKENS <= 80
