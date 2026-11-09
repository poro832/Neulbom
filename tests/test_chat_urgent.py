"""위급한 말 찾기는 AI가 아니라 규칙이다 — 같은 말은 늘 같은 결과."""

import pytest

from app.chat.urgent import FALL, GUARDIAN_ALERT_MESSAGE, HELP, MEDICAL, SELF_HARM, detect_urgent, safety_notice


@pytest.mark.parametrize(
    "text, category",
    [
        ("가슴이 너무 아파요", MEDICAL),
        ("가슴이아파", MEDICAL),
        ("가슴 이 답답하네", MEDICAL),
        ("숨이 차서 못 걷겠어", MEDICAL),
        ("숨을 못 쉬겠어요", MEDICAL),
        ("갑자기 어지러워요", MEDICAL),
        ("어지럽다", MEDICAL),
        ("쓰러질 것 같아", MEDICAL),
        ("피를 토했어요", MEDICAL),
        ("말이 안 나와요", MEDICAL),
        ("어제 넘어졌어요", FALL),
        ("일어나지 못하겠어", FALL),
        ("119 불러 줘", HELP),
        ("살려 주세요", HELP),
        ("죽고 싶어요", SELF_HARM),
        ("살기 싫다", SELF_HARM),
    ],
)
def test_urgent_words_are_found(text, category):
    match = detect_urgent(text)
    assert match is not None and match.category == category


@pytest.mark.parametrize(
    "text",
    [
        "오늘 날씨 어때요?",
        "점심은 된장찌개를 먹었어",
        "가슴이 안 아파요",  # 부정은 목록에 걸리지 않는다
        "숨이 안 차요",
        "어지럽지 않아요",
        "손주가 보고 싶어요",
        "",
        "   ",
    ],
)
def test_ordinary_words_are_not_urgent(text):
    assert detect_urgent(text) is None


def test_the_most_urgent_category_wins_when_several_match():
    assert detect_urgent("가슴이 아파서 죽고 싶어요").category == SELF_HARM


def test_the_safety_notice_names_a_way_out_and_tells_that_the_family_will_know():
    for category in (MEDICAL, FALL, HELP, SELF_HARM):
        notice = safety_notice(category)
        assert "119" in notice and "가족" in notice
    assert "109" in safety_notice(SELF_HARM)


def test_the_guardian_alert_never_carries_what_the_elder_said():
    assert "가슴" not in GUARDIAN_ALERT_MESSAGE and "죽" not in GUARDIAN_ALERT_MESSAGE
