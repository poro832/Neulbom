"""앱 AI 채팅 주소 — 어르신의 글 대화, 위급한 말 알림, 보호자의 요약 조회."""

from app.api.chat_routes import CHAT_BUSY, CHAT_CLOSED, CHAT_EMPTY, CHAT_LIMIT
from app.chat.alerting import make_urgent_alerter
from app.chat.service import DAILY_LIMIT, SESSION_IDLE_SECONDS, ChatService
from app.chat.store import InMemoryChatStore
from app.chat.urgent import GUARDIAN_ALERT_MESSAGE
from app.media.call_summary import CallSummarizer
from tests.app_data_helpers import make_app_kit


class FakeModel:
    def __init__(self, answer="네, 좋은 생각이에요.", fail=False):
        self.answer = answer
        self.fail = fail
        self.calls = 0

    def reply(self, history):
        self.calls += 1
        if self.fail:
            raise TimeoutError("느림")
        return self.answer


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


def make(model="default", summary_model=None):
    clock = Clock()
    model = FakeModel() if model == "default" else model
    summary_model = summary_model or FakeModel("어르신이 날씨를 궁금해하셨어요.")
    service = ChatService(
        store=InMemoryChatStore(),
        model=model,
        summarizer=CallSummarizer(summary_model, "test-model"),
        clock=clock,
    )
    kit = make_app_kit(chat=service)
    service._on_urgent = make_urgent_alerter(elders=kit.data.elders, alerts=kit.alerts, notifier=None)
    return kit, service, clock, summary_model


# ------------------------------------------------------------------ 어르신: 보내기


def test_the_elder_sends_a_message_and_gets_an_answer():
    kit, _, _, _ = make()

    r = kit.client.post("/v1/me/chat", json={"message": "오늘 날씨 어때요?"}, headers=kit.elder_headers(12))

    assert r.status_code == 200
    assert r.json() == {"reply": "네, 좋은 생각이에요.", "urgent": False}


def test_the_chat_needs_an_elder_key():
    kit, _, _, _ = make()
    assert kit.client.post("/v1/me/chat", json={"message": "안녕"}).status_code == 401
    # 보호자 열쇠로는 어르신 주소를 열 수 없다
    assert kit.client.post("/v1/me/chat", json={"message": "안녕"}, headers=kit.guardian_headers).status_code == 401


def test_bad_messages_are_refused_without_calling_the_model():
    kit, _, _, _ = make()
    model = kit.data.chat._model
    headers = kit.elder_headers(12)

    assert kit.client.post("/v1/me/chat", json={"message": ""}, headers=headers).status_code == 422
    assert kit.client.post("/v1/me/chat", json={"message": "가" * 2001}, headers=headers).status_code == 422
    blank = kit.client.post("/v1/me/chat", json={"message": "   "}, headers=headers)
    assert blank.status_code == 422 and blank.json()["detail"] == CHAT_EMPTY
    assert model.calls == 0


def test_without_a_model_the_chat_says_it_is_not_ready():
    kit, _, _, _ = make(model=None)
    r = kit.client.post("/v1/me/chat", json={"message": "안녕"}, headers=kit.elder_headers(12))
    assert r.status_code == 503 and r.json()["detail"] == CHAT_CLOSED


def test_a_model_failure_is_a_plain_try_later_never_a_fake_answer():
    kit, _, _, _ = make(model=FakeModel(fail=True))
    r = kit.client.post("/v1/me/chat", json={"message": "안녕"}, headers=kit.elder_headers(12))
    assert r.status_code == 503 and r.json()["detail"] == CHAT_BUSY


def test_the_daily_limit_answers_429():
    kit, _, _, _ = make()
    headers = kit.elder_headers(12)
    for _ in range(DAILY_LIMIT):
        assert kit.client.post("/v1/me/chat", json={"message": "응"}, headers=headers).status_code == 200
    r = kit.client.post("/v1/me/chat", json={"message": "응"}, headers=headers)
    assert r.status_code == 429 and r.json()["detail"] == CHAT_LIMIT


# ------------------------------------------------------------------ 위급한 말


def test_an_urgent_message_alerts_the_guardian_even_without_the_share_consent_and_never_quotes_it():
    kit, _, _, _ = make()
    assert kit.data.content.share_agreed(12) is False

    r = kit.client.post("/v1/me/chat", json={"message": "가슴이 너무 아파요"}, headers=kit.elder_headers(12))

    body = r.json()
    assert body["urgent"] is True and "119" in body["reply"]
    alerts = kit.client.get("/v1/guardian/alerts", headers=kit.guardian_headers).json()["alerts"]
    assert [(a["type"], a["severity"], a["message"]) for a in alerts] == [
        ("emergency_keyword", "critical", GUARDIAN_ALERT_MESSAGE)
    ]
    assert "가슴" not in alerts[0]["message"]


def test_another_guardians_elder_gets_no_alert():
    kit, _, _, _ = make()
    kit.client.post("/v1/me/chat", json={"message": "숨이 안 쉬어져요"}, headers=kit.elder_headers(14))

    assert kit.client.get("/v1/guardian/alerts", headers=kit.guardian_headers).json()["alerts"] == []


# ------------------------------------------------------------------ 보호자: 요약


def test_the_guardian_sees_only_summaries_and_only_after_the_elder_agreed():
    kit, _, clock, summary_model = make()
    kit.client.post("/v1/me/chat", json={"message": "오늘 날씨 어때요?"}, headers=kit.elder_headers(12))
    clock.now += SESSION_IDLE_SECONDS + 60

    before = kit.client.get("/v1/elders/12/chats", headers=kit.guardian_headers)
    assert before.json() == {"share_agreed": False, "chats": []}
    assert summary_model.calls == 0  # 동의 없는 대화는 요약하지도 않는다

    kit.data.content.agree_share(12)
    after = kit.client.get("/v1/elders/12/chats", headers=kit.guardian_headers).json()
    assert after["share_agreed"] is True
    (chat,) = after["chats"]
    assert chat["summary"] == "어르신이 날씨를 궁금해하셨어요."
    assert set(chat) == {"session_id", "started_at", "summary"}  # 원문이 실려 나가지 않는다
    assert "날씨 어때요" not in str(after)


def test_a_conversation_still_going_is_not_summarized_yet():
    kit, _, _, summary_model = make()
    kit.data.content.agree_share(12)
    kit.client.post("/v1/me/chat", json={"message": "안녕"}, headers=kit.elder_headers(12))

    assert kit.client.get("/v1/elders/12/chats", headers=kit.guardian_headers).json()["chats"] == []
    assert summary_model.calls == 0


def test_the_summaries_need_the_owning_guardians_key():
    kit, _, _, _ = make()
    assert kit.client.get("/v1/elders/12/chats").status_code == 401
    assert kit.client.get("/v1/elders/14/chats", headers=kit.guardian_headers).status_code == 404
    assert kit.client.get("/v1/elders/12/chats?limit=0", headers=kit.guardian_headers).status_code == 422


def test_without_the_chat_service_there_are_no_chat_addresses():
    kit = make_app_kit()
    assert kit.client.post("/v1/me/chat", json={"message": "안녕"}, headers=kit.elder_headers(12)).status_code == 404


def test_a_long_message_is_accepted_and_still_checked_for_urgent_words():
    kit, _, _, _ = make()
    text = "오늘 있었던 일을 길게 적어요. " * 30 + "숨이 안 쉬어져요"

    r = kit.client.post("/v1/me/chat", json={"message": text}, headers=kit.elder_headers(12))

    assert r.status_code == 200 and r.json()["urgent"] is True
    assert len(kit.client.get("/v1/guardian/alerts", headers=kit.guardian_headers).json()["alerts"]) == 1


def test_an_urgent_message_gets_the_notice_and_alerts_even_when_the_chat_is_not_ready():
    kit, _, _, _ = make(model=None)
    headers = kit.elder_headers(12)

    urgent = kit.client.post("/v1/me/chat", json={"message": "가슴이 너무 아파요"}, headers=headers)

    assert urgent.status_code == 200 and "119" in urgent.json()["reply"]
    assert len(kit.client.get("/v1/guardian/alerts", headers=kit.guardian_headers).json()["alerts"]) == 1
    # 평범한 말은 여전히 '준비 중'이다
    assert kit.client.post("/v1/me/chat", json={"message": "안녕"}, headers=headers).status_code == 503


def test_an_urgent_message_gets_through_after_the_daily_limit():
    kit, _, _, _ = make()
    headers = kit.elder_headers(12)
    for _ in range(DAILY_LIMIT):
        kit.client.post("/v1/me/chat", json={"message": "응"}, headers=headers)

    assert kit.client.post("/v1/me/chat", json={"message": "응"}, headers=headers).status_code == 429
    urgent = kit.client.post("/v1/me/chat", json={"message": "어지러워서 쓰러질 것 같아요"}, headers=headers)

    assert urgent.status_code == 200 and "119" in urgent.json()["reply"]
    assert len(kit.client.get("/v1/guardian/alerts", headers=kit.guardian_headers).json()["alerts"]) == 1
