"""안부 전화 시간 — 보호자가 보고(GET) 바꾼다(PUT). 스케줄러는 같은 값을 매분 새로 읽는다."""

from __future__ import annotations

import logging
from datetime import time

import pytest

from app.api.passwords import NO_LOGIN
from tests.app_data_helpers import kst, make_app_kit

CALL_TIME = "/v1/elders/{}/call-time"
OUT_OF_RANGE = {"detail": "안부 전화 시간은 오전 7시부터 오후 9시까지 30분 단위로 고를 수 있어요"}
JUST_PASSED = {
    "detail": "방금 지난 시간이라 곧바로 전화가 걸릴 수 있어요. "
    "지금보다 나중 시간이나 더 일찍 지난 시간(내일부터 걸려요)을 골라 주세요"
}
NO_ELDER = {"detail": "등록되지 않은 어르신입니다"}
NEED_KEY = {"detail": "열쇠가 필요합니다"}


def get(kit, elder_id=12, headers=None):
    return kit.client.get(CALL_TIME.format(elder_id), headers=kit.guardian_headers if headers is None else headers)


def put(kit, value, elder_id=12, headers=None):
    return kit.client.put(
        CALL_TIME.format(elder_id),
        json={"call_time": value},
        headers=kit.guardian_headers if headers is None else headers,
    )


def kit_at(hour: int, minute: int):
    """한국 시간 2026-10-08 hour:minute에 멈춘 시계."""
    return make_app_kit(now=kst(2026, 10, 8, hour, minute, 0))


# ------------------------------------------------ 보기


def test_the_call_time_starts_at_nine():
    kit = make_app_kit()

    response = get(kit)

    assert response.status_code == 200
    assert response.json() == {"call_time": "09:00"}


def test_a_changed_call_time_is_what_get_returns_next():
    kit = kit_at(12, 0)

    saved = put(kit, "18:30")

    assert saved.status_code == 200 and saved.json() == {"call_time": "18:30"}
    assert get(kit).json() == {"call_time": "18:30"}
    assert kit.data.elders.call_time_of(12) == time(18, 30)
    assert get(kit, 13).json() == {"call_time": "09:00"}  # 다른 어르신은 그대로


@pytest.mark.parametrize("value", ["07:00", "07:30", "12:00", "20:30", "21:00"])
def test_every_half_hour_from_seven_to_nine_pm_can_be_chosen(value):
    kit = kit_at(6, 0)  # 아직 아무 시간도 지나지 않았다

    response = put(kit, value)

    assert response.status_code == 200 and response.json() == {"call_time": value}


# ------------------------------------------------ 형식과 범위


@pytest.mark.parametrize(
    "value",
    ["09:15", "9:00", "0900", "24:00", "09:00:00", "", "aa:bb", " 09:00", "09:00\n", "０９:00", "٠٩:00"],
)
def test_a_badly_formed_time_is_422_and_nothing_changes(value):
    kit = kit_at(12, 0)

    response = put(kit, value)

    assert response.status_code == 422
    assert kit.data.elders.call_time_of(12) == time(9, 0)


@pytest.mark.parametrize("body", [{}, {"call_time": 930}, {"call_time": None}, {"time": "10:00"}])
def test_a_missing_or_non_text_time_is_422(body):
    kit = kit_at(12, 0)

    response = kit.client.put(CALL_TIME.format(12), json=body, headers=kit.guardian_headers)

    assert response.status_code == 422
    assert kit.data.elders.call_time_of(12) == time(9, 0)


@pytest.mark.parametrize("value", ["06:30", "00:00", "21:30", "23:30"])
def test_a_time_outside_seven_to_nine_pm_is_422_with_the_reason(value):
    kit = kit_at(12, 0)

    response = put(kit, value)

    assert response.status_code == 422
    assert response.json() == OUT_OF_RANGE
    assert kit.data.elders.call_time_of(12) == time(9, 0)


# ------------------------------------------------ 방금 지난 시간 (유예 30분 안이면 곧바로 걸린다)


@pytest.mark.parametrize(
    ("value", "status"),
    [
        ("09:00", 409),  # 10분 전 — 유예 안이라 다음 확인에서 곧바로 걸린다
        ("08:30", 200),  # 40분 전 — 유예를 넘어 오늘은 건너뛰고 내일부터 걸린다
        ("07:00", 200),
        ("09:30", 200),  # 아직 오지 않은 시간
        ("21:00", 200),
    ],
)
def test_a_time_that_just_passed_is_refused_at_ten_past_nine(value, status):
    kit = kit_at(9, 10)

    response = put(kit, value)

    assert response.status_code == status
    if status == 409:
        assert response.json() == JUST_PASSED
        assert kit.data.elders.call_time_of(12) == time(9, 0)
    else:
        assert response.json() == {"call_time": value}


def test_the_current_minute_itself_is_refused():
    kit = kit_at(9, 30)

    response = put(kit, "09:30")

    assert response.status_code == 409 and response.json() == JUST_PASSED


def test_exactly_thirty_minutes_back_is_still_refused_and_an_hour_back_is_not():
    kit = kit_at(9, 30)

    assert put(kit, "09:00").status_code == 409  # 차이 30 — 유예의 끝도 곧바로 걸린다
    assert put(kit, "08:30").status_code == 200  # 차이 60


@pytest.mark.parametrize("value", ["09:10", "08:40"])
def test_minutes_that_are_not_a_choice_get_the_form_check_first(value):
    """9:10에 09:10(차이 0)과 08:40(차이 30)은 30분 단위가 아니라 형식에서 먼저 422다. 차이 계산은 아래 순수 함수로 본다."""
    kit = kit_at(9, 10)

    assert put(kit, value).status_code == 422


@pytest.mark.parametrize(
    ("value", "refused"),
    [
        (time(9, 10), True),   # 차이 0
        (time(9, 0), True),    # 차이 10
        (time(8, 40), True),   # 차이 30
        (time(8, 39), False),  # 차이 31
        (time(8, 30), False),  # 차이 40
        (time(9, 11), False),  # 아직 오지 않았다
        (time(9, 30), False),
    ],
)
def test_just_passed_counts_minutes_back_from_now_up_to_the_grace(value, refused):
    from datetime import datetime

    from app.api.app_data import just_passed
    from app.scheduler import KST

    assert just_passed(datetime(2026, 10, 8, 9, 10, 0, tzinfo=KST), value) is refused


def test_seconds_do_not_shorten_the_refusal():
    """9:30:59에 09:00은 분으로 30분 차이 — 거절한다. 9:31:00이 되어야 받는다(스케줄러보다 조금 더 조심한다)."""
    late = make_app_kit(now=kst(2026, 10, 8, 9, 30, 59))
    later = make_app_kit(now=kst(2026, 10, 8, 9, 31, 0))

    assert put(late, "09:00").status_code == 409
    assert put(later, "09:00").status_code == 200


def test_the_grace_follows_the_schedulers_constant(monkeypatch):
    import app.api.app_data as app_data

    monkeypatch.setattr(app_data, "DEFAULT_GRACE_SECONDS", 3600)
    kit = kit_at(9, 10)

    assert put(kit, "08:30").status_code == 409  # 유예가 60분이면 40분 전도 곧바로 걸린다


# ------------------------------------------------ 누가 보고 바꾸는가


def test_another_guardians_elder_is_404_and_unchanged():
    kit = kit_at(12, 0)

    assert (get(kit, 14).status_code, get(kit, 14).json()) == (404, NO_ELDER)
    response = put(kit, "10:00", elder_id=14)

    assert (response.status_code, response.json()) == (404, NO_ELDER)
    assert kit.data.elders.call_time_of(14) == time(9, 0)


def test_an_unknown_elder_is_404():
    kit = kit_at(12, 0)

    assert get(kit, 999).status_code == 404
    assert put(kit, "10:00", elder_id=999).status_code == 404


def test_no_key_or_an_elder_key_is_401():
    kit = kit_at(12, 0)
    elder = kit.elder_headers(12)

    for headers in ({}, {"Authorization": "Bearer nlb_wrong"}, elder):
        assert (get(kit, headers=headers).status_code, get(kit, headers=headers).json()) == (401, NEED_KEY)
        response = put(kit, "10:00", headers=headers)
        assert (response.status_code, response.json()) == (401, NEED_KEY)
    assert kit.data.elders.call_time_of(12) == time(9, 0)


def test_a_guardian_waiting_for_email_or_the_operator_can_see_but_not_change_it():
    kit = kit_at(12, 0)
    for n in (1, 2):  # kit의 열쇠가 보호자 1·2를 쓰므로 번호를 비켜 간다
        kit.data.accounts.create("자리", f"placeholder{n}@no-login.invalid", "010-0", NO_LOGIN)
    signup = kit.client.post(
        "/v1/guardian/signup",
        json={"name": "김보호", "email": "kim@example.com", "phone": "010-1111-2222", "password": "correct-horse-1"},
    ).json()
    headers = {"Authorization": f"Bearer {signup['key']}"}
    guardian_id = kit.data.accounts.find_by_email("kim@example.com").guardian_id
    elder_id = kit.data.elders.create_unlinked(name="홍길동", phone="010-9999-1111")
    assert kit.data.elders.link(elder_id, guardian_id)

    assert get(kit, elder_id, headers=headers).json() == {"call_time": "09:00"}
    before_email = put(kit, "10:00", elder_id=elder_id, headers=headers)
    kit.data.accounts.mark_email_verified(guardian_id)
    before_operator = put(kit, "10:00", elder_id=elder_id, headers=headers)

    assert (before_email.status_code, before_email.json()) == (403, {"detail": "이메일 인증 후 사용할 수 있어요"})
    assert (before_operator.status_code, before_operator.json()) == (403, {"detail": "운영자 확인 후 사용할 수 있어요"})
    assert kit.data.elders.call_time_of(elder_id) == time(9, 0)


def test_if_the_elder_moves_away_while_saving_it_is_404(monkeypatch):
    kit = kit_at(12, 0)
    monkeypatch.setattr(kit.data.elders, "set_call_time", lambda *args: False)

    response = put(kit, "10:00")

    assert (response.status_code, response.json()) == (404, NO_ELDER)


def test_a_broken_store_is_503_not_a_silent_success(monkeypatch):
    kit = kit_at(12, 0)

    def broken(*args):
        raise RuntimeError("DB가 끊겼다")

    monkeypatch.setattr(kit.data.elders, "set_call_time", broken)

    assert put(kit, "10:00").status_code == 503


# ------------------------------------------------ 기록


def test_the_change_is_logged_without_phone_numbers_or_names(caplog):
    kit = kit_at(12, 0)

    with caplog.at_level(logging.INFO):
        put(kit, "18:30")

    assert "안부 전화 시간을 바꿨다 elder_id=12 guardian_id=1 시각=18:30" in caplog.messages
    for secret in ("070-1111-2222", "07011112222", "어르신 12", "보호자1", "010-0000-0001"):
        assert secret not in caplog.text
