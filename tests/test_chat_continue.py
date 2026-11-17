"""지난 대화에서 이어서 말하기 — 같은 대화에 말이 붙고, 요약이 다시 만들어지고, 남의 대화는 건드릴 수 없다."""

from __future__ import annotations

from app.chat.service import SESSION_IDLE_SECONDS
from tests.test_app_chat_routes import FakeModel, make
from tests.test_chat_store_contract import IDLE, NOW, say, store  # noqa: F401  (store는 fixture)

# ------------------------------------------------------------------ 저장소


def test_the_list_is_ordered_by_the_last_message_so_a_continued_conversation_comes_first(store):
    old = store.session_for(12, NOW, IDLE)
    say(store, old, "elder", "예전 이야기", NOW)
    newer = store.session_for(12, NOW + 3 * IDLE, IDLE)
    say(store, newer, "elder", "최근 이야기", NOW + 3 * IDLE)
    say(store, old, "elder", "예전 이야기에 이어서", NOW + 5 * IDLE)  # 오래된 대화에 이어 말했다

    assert [i.session_id for i in store.sessions_for_elder(12, 10)] == [old, newer]


def test_reopening_a_summarized_conversation_makes_it_due_for_a_fresh_summary(store):
    session = store.session_for(12, NOW, IDLE)
    say(store, session, "elder", "안녕", NOW)
    store.save_summary(session, "첫 요약", "m", NOW + IDLE)
    assert store.sessions_to_summarize(12, NOW + 10 * IDLE, 5) == []

    store.reopen_for_summary(session)

    assert store.sessions_to_summarize(12, NOW + 10 * IDLE, 5) == [session]


# ------------------------------------------------------------------ 주소


class Recording(FakeModel):
    """모델이 받은 대화 기록을 남긴다."""

    def __init__(self):
        super().__init__("이어서 말씀해 주세요.")
        self.histories = []

    def reply(self, history):
        self.histories.append([t.text for t in history])
        return super().reply(history)


def first_session_id(kit, headers):
    # elder_headers()를 다시 부르면 열쇠가 새로 바뀌어 앞 열쇠가 무효가 된다 — 열쇠를 받아서 쓴다.
    return kit.client.get("/v1/me/chats", headers=headers).json()["sessions"][0]["session_id"]


def test_a_message_with_a_session_id_continues_that_conversation_even_after_a_long_pause():
    model = Recording()
    kit, _, clock, _ = make(model=model)
    headers = kit.elder_headers(12)
    kit.client.post("/v1/me/chat", json={"message": "첫 이야기"}, headers=headers)
    session_id = first_session_id(kit, headers)
    clock.now += SESSION_IDLE_SECONDS * 4  # 30분이 훨씬 지났다 — 그냥 보내면 새 대화가 된다

    r = kit.client.post("/v1/me/chat", json={"message": "이어서 해요", "session_id": session_id}, headers=headers)

    assert r.status_code == 200
    sessions = kit.client.get("/v1/me/chats", headers=headers).json()["sessions"]
    assert [s["session_id"] for s in sessions] == [session_id]  # 새 대화가 생기지 않았다
    messages = kit.client.get(f"/v1/me/chats/{session_id}", headers=headers).json()["messages"]
    assert [m["text"] for m in messages] == ["첫 이야기", "이어서 말씀해 주세요.", "이어서 해요", "이어서 말씀해 주세요."]
    assert model.histories[-1] == ["첫 이야기", "이어서 말씀해 주세요.", "이어서 해요"]  # AI가 앞 대화를 기억한다


def test_without_a_session_id_a_long_pause_still_starts_a_new_conversation():
    kit, _, clock, _ = make()
    headers = kit.elder_headers(12)
    kit.client.post("/v1/me/chat", json={"message": "첫 이야기"}, headers=headers)
    clock.now += SESSION_IDLE_SECONDS * 4

    kit.client.post("/v1/me/chat", json={"message": "새 이야기"}, headers=headers)

    assert len(kit.client.get("/v1/me/chats", headers=headers).json()["sessions"]) == 2


def test_another_elders_session_is_refused_and_nothing_is_stored_there():
    kit, _, _, _ = make()
    mine = kit.elder_headers(12)
    other = kit.elder_headers(13)
    kit.client.post("/v1/me/chat", json={"message": "비밀 이야기"}, headers=mine)
    theirs = first_session_id(kit, mine)

    r = kit.client.post("/v1/me/chat", json={"message": "끼어들기", "session_id": theirs}, headers=other)

    assert r.status_code == 404
    messages = kit.client.get(f"/v1/me/chats/{theirs}", headers=mine).json()["messages"]
    assert [m["text"] for m in messages] == ["비밀 이야기", "네, 좋은 생각이에요."]
    assert kit.client.get("/v1/me/chats", headers=other).json() == {"sessions": []}


def test_an_unknown_session_id_is_a_not_found_but_an_urgent_phrase_is_still_handled():
    kit, _, _, _ = make()
    headers = kit.elder_headers(12)

    plain = kit.client.post("/v1/me/chat", json={"message": "안녕", "session_id": 999_999}, headers=headers)
    assert plain.status_code == 404

    urgent = kit.client.post("/v1/me/chat", json={"message": "숨이 안 쉬어져요", "session_id": 999_999}, headers=headers)
    assert urgent.status_code == 200 and urgent.json()["urgent"] is True  # 잘못된 번호여도 위급한 말은 놓치지 않는다
    assert kit.client.get("/v1/guardian/alerts", headers=kit.guardian_headers).json()["alerts"]


def test_a_bad_session_id_is_a_validation_error():
    kit, _, _, _ = make()
    r = kit.client.post("/v1/me/chat", json={"message": "안녕", "session_id": 0}, headers=kit.elder_headers(12))
    assert r.status_code == 422


def test_continuing_a_summarized_conversation_refreshes_the_guardians_summary():
    kit, _, clock, summary_model = make()
    kit.data.content.agree_share(12)
    headers = kit.elder_headers(12)
    kit.client.post("/v1/me/chat", json={"message": "날씨 어때요?"}, headers=headers)
    session_id = first_session_id(kit, headers)
    clock.now += SESSION_IDLE_SECONDS + 60
    kit.client.get("/v1/elders/12/chats", headers=kit.guardian_headers)  # 첫 요약
    assert summary_model.calls == 1

    clock.now += SESSION_IDLE_SECONDS
    kit.client.post("/v1/me/chat", json={"message": "점심 뭐 먹을까요", "session_id": session_id}, headers=headers)
    # 아직 이어 말하는 중이면 다시 요약하지 않는다
    kit.client.get("/v1/elders/12/chats", headers=kit.guardian_headers)
    assert summary_model.calls == 1

    clock.now += SESSION_IDLE_SECONDS + 60
    chats = kit.client.get("/v1/elders/12/chats", headers=kit.guardian_headers).json()["chats"]

    assert summary_model.calls == 2  # 대화가 끝나면 이어진 내용까지 다시 요약한다
    assert len(chats) == 1 and chats[0]["session_id"] == session_id
