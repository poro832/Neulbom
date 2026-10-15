"""통화 속 건강·기분 언급 집계 — 동의 전에는 어떤 값도 나가지 않는다."""

from __future__ import annotations

import logging

from app.api.call_content import Mention
from tests.app_data_helpers import kst, make_app_kit

NOW = kst(2026, 10, 8, 9, 0, 0)  # 2026-10-08은 목요일 → 그 주 일요일은 2026-10-04
PATH = "/v1/elders/12/mentions"
ORDER = ["body", "sleep", "meal", "mood", "activity"]


def call(kit, call_id, when, elder_id=12):
    kit.reports.add_call(
        call_id=call_id, elder_id=elder_id, status="completed", created_at=when, score=10, duration_ms=60000
    )
    kit.data.content.set_owner(call_id, elder_id)


def seeded(agreed=True):
    kit = make_app_kit(NOW)
    call(kit, 1, NOW - 3600)  # 이번 주
    call(kit, 2, NOW - 7200)  # 이번 주(더 이른 통화)
    call(kit, 3, NOW - 8 * 86400)  # 지난 주
    kit.data.content.save_mentions(
        1, [Mention("body", "bad", "허리가 아파요"), Mention("sleep", "bad", "잠을 못 잤어")], "m"
    )
    kit.data.content.save_mentions(
        2, [Mention("body", "ok", "무릎이 조금 그래"), Mention("meal", "good", "밥 잘 먹었어")], "m"
    )
    kit.data.content.save_mentions(3, [Mention("mood", "bad", "외로워요")], "m")
    if agreed:
        kit.data.content.agree_share(12)
    return kit


def get(kit, path=PATH, **params):
    return kit.client.get(path, params=params, headers=kit.guardian_headers)


def test_the_week_is_summed_by_category_in_a_fixed_order():
    body = get(seeded()).json()

    assert body["share_agreed"] is True and body["week_start"] == "2026-10-04"
    assert [c["category"] for c in body["categories"]] == ORDER
    by = {c["category"]: c for c in body["categories"]}
    assert (by["body"]["negative"], by["body"]["neutral"], by["body"]["positive"]) == (1, 1, 0)
    assert (by["sleep"]["negative"], by["meal"]["positive"]) == (1, 1)
    assert by["mood"]["items"] == [] and by["activity"]["items"] == []  # 지난 주 것은 들어오지 않는다


def test_items_are_newest_call_first_with_the_elders_own_words():
    by = {c["category"]: c for c in get(seeded()).json()["categories"]}

    assert [i["quote"] for i in by["body"]["items"]] == ["허리가 아파요", "무릎이 조금 그래"]
    first = by["body"]["items"][0]
    assert first["call_id"] == 1 and first["said"] == "bad" and first["date"].startswith("2026-10-08")


def test_another_week_and_a_midweek_date_are_mapped_to_that_sunday():
    last = get(seeded(), week_start="2026-10-01").json()  # 목요일 → 그 주 일요일 2026-09-27

    assert last["week_start"] == "2026-09-27"
    # 지난 주 통화(3번, 9/30)의 mood만 들어 있다
    assert [c["category"] for c in last["categories"] if c["items"]] == ["mood"]

    prev = get(seeded(), week_start="2026-10-03").json()  # 토요일 → 일요일 2026-09-27
    assert prev["week_start"] == "2026-09-27"


def test_before_the_elder_agrees_nothing_leaves():
    body = get(seeded(agreed=False)).json()

    assert body == {"share_agreed": False, "week_start": "2026-10-04", "categories": []}


def test_other_guardians_elders_are_404_and_a_key_is_needed():
    kit = seeded()

    assert get(kit, "/v1/elders/14/mentions").status_code == 404
    assert kit.client.get(PATH).status_code == 401
    assert kit.client.get(PATH, headers=kit.elder_headers(12)).status_code == 401


def test_a_lookup_failure_gives_empty_counts_instead_of_an_error():
    kit = seeded()

    def boom(call_ids):
        raise RuntimeError("table missing")

    kit.data.content.mentions = boom
    body = get(kit)

    assert body.status_code == 200
    assert [c["items"] for c in body.json()["categories"]] == [[], [], [], [], []]


def test_a_bad_week_start_is_rejected():
    assert get(seeded(), week_start="not-a-date").status_code == 422


def test_quotes_are_never_logged(caplog):
    kit = seeded()
    with caplog.at_level(logging.DEBUG):
        get(kit)
    assert "허리가 아파요" not in caplog.text


def test_an_older_week_still_has_its_mentions_when_more_than_a_hundred_newer_calls_exist():
    kit = make_app_kit(NOW)
    for i in range(120):
        call(kit, 100 + i, NOW - 60 * (i + 1))  # 이번 주 120통
    call(kit, 1, NOW - 8 * 86400)  # 지난 주 한 통
    kit.data.content.save_mentions(1, [Mention("mood", "bad", "외로워요")], "m")
    kit.data.content.agree_share(12)
    mood = {c["category"]: c for c in get(kit, week_start="2026-09-27").json()["categories"]}["mood"]
    assert [i["quote"] for i in mood["items"]] == ["외로워요"]
