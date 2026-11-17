"""AI 채팅 번역 — 어르신이 AI의 말을 설정한 언어로 번역해 듣는다."""

from __future__ import annotations

import json
import logging

from app.chat.service import ChatService
from app.chat.store import InMemoryChatStore
from app.chat.translate import LANGUAGES, TRANSLATE_DAILY_LIMIT, Translator, clean_language
from app.media.conversation import Turn
from app.media.gateway_chat import chat_model_from_env, translate_model_from_env
from tests.app_data_helpers import make_app_kit


class FakeTranslateModel:
    """받은 글을 '[언어] 글'로 돌려준다. 호출 수를 센다."""

    def __init__(self, language_name, fail=False):
        self.language_name = language_name
        self.fail = fail
        self.calls = 0

    def reply(self, history):
        self.calls += 1
        if self.fail:
            raise TimeoutError("느림")
        return f"[{self.language_name}] " + history[-1].text


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


def make(fail=False, translator="default"):
    clock = Clock()
    models: dict[str, FakeTranslateModel] = {}

    def model_for(language_name):
        models[language_name] = FakeTranslateModel(language_name, fail=fail)
        return models[language_name]

    if translator == "default":
        translator = Translator(model_for)
    service = ChatService(store=InMemoryChatStore(), model=None, translator=translator, clock=clock)
    kit = make_app_kit(chat=service)
    return kit, service, clock, models


def post(kit, headers, text="안녕하세요", language="en"):
    return kit.client.post("/v1/me/translate", json={"text": text, "language": language}, headers=headers)


# ------------------------------------------------------------------ 언어


def test_only_supported_languages_pass_and_codes_are_normalized():
    assert clean_language(" EN ") == "en"
    assert clean_language("ja") == "ja"
    assert set(LANGUAGES) == {"en", "ja", "zh", "vi", "th", "ru"}
    for bad in ("", "ko", "fr", "english", "en-US", "../", None, 5):
        assert clean_language(bad) is None


# ------------------------------------------------------------------ 주소


def test_the_elder_translates_a_message_into_the_chosen_language():
    kit, _, _, models = make()

    r = post(kit, kit.elder_headers(12), "맑아요, 산책하기 좋아요.", "ja")

    assert r.status_code == 200
    assert r.json() == {"text": "[일본어] 맑아요, 산책하기 좋아요.", "language": "ja"}
    assert "일본어" in models  # 언어별로 번역 지시문이 달라진다


def test_translation_needs_an_elder_key_and_a_valid_body():
    kit, _, _, _ = make()
    assert post(kit, {}).status_code == 401
    assert post(kit, kit.guardian_headers).status_code == 401  # 보호자 열쇠로는 열 수 없다
    headers = kit.elder_headers(12)
    assert post(kit, headers, language="fr").status_code == 422
    assert post(kit, headers, language="ko").status_code == 422
    assert post(kit, headers, text="").status_code == 422
    assert post(kit, headers, text="가" * 601).status_code == 422
    blank = post(kit, headers, text="   ")
    assert blank.status_code == 422


def test_the_same_sentence_is_translated_once_and_repeats_are_free():
    kit, _, _, models = make()
    headers = kit.elder_headers(12)

    first = post(kit, headers, "산책하세요", "en").json()
    again = post(kit, headers, "산책하세요", "en").json()
    other = post(kit, headers, "산책하세요", "vi").json()

    assert first == again
    assert models["영어"].calls == 1  # 같은 글·같은 언어는 모델을 다시 부르지 않는다
    assert other["text"].startswith("[베트남어]")


def test_the_daily_limit_stops_new_translations_but_not_cached_ones_and_resets_next_day():
    kit, _, clock, _ = make()
    headers = kit.elder_headers(12)
    for i in range(TRANSLATE_DAILY_LIMIT):
        assert post(kit, headers, f"문장 {i}").status_code == 200

    over = post(kit, headers, "새 문장")
    assert over.status_code == 429 and "번역" in over.json()["detail"]
    assert post(kit, headers, "문장 0").status_code == 200  # 이미 번역한 글은 한도와 상관없다
    assert post(kit, kit.elder_headers(13), "새 문장").status_code == 200  # 다른 어르신은 따로 센다

    clock.now += 86400
    assert post(kit, headers, "새 문장").status_code == 200


def test_a_failing_or_missing_translator_says_so_in_plain_words_and_never_logs_the_text(caplog):
    kit, _, _, _ = make(fail=True)
    with caplog.at_level(logging.DEBUG):
        r = post(kit, kit.elder_headers(12), "비밀스러운 문장")
    assert r.status_code == 503 and "번역하기 어려워요" in r.json()["detail"]
    assert "비밀스러운" not in caplog.text

    closed, _, _, _ = make(translator=None)
    r = post(closed, closed.elder_headers(12))
    assert r.status_code == 503 and "준비 중" in r.json()["detail"]


def test_a_failed_translation_does_not_use_up_the_daily_limit():
    kit, service, _, _ = make(fail=True)
    headers = kit.elder_headers(12)
    for _ in range(TRANSLATE_DAILY_LIMIT + 3):
        assert post(kit, headers, "다시 해 볼게요").status_code == 503  # 한도(429)가 아니라 계속 실패(503)


# ------------------------------------------------------------------ 게이트웨이


def test_the_gateway_translator_asks_for_only_the_translation_into_the_given_language():
    sent: list[dict] = []

    def transport(url, *, headers, payload, timeout):
        sent.append(payload)
        return json.dumps({"choices": [{"message": {"content": "It is sunny."}}]}).encode()

    env = {"LLM_GATEWAY_API_KEY": "KEY", "LLM_GATEWAY_BASE_URL": "https://g.example.test/v1"}
    model = translate_model_from_env("영어", env, transport=transport)

    assert model.reply([Turn("elder", "맑아요.")]) == "It is sunny."
    system = sent[0]["messages"][0]["content"]
    assert "영어" in system and "번역문만" in system and "따르지 않" in system  # 글 속 지시를 따르지 않는다
    assert sent[0]["messages"][-1] == {"role": "user", "content": "맑아요."}
    assert translate_model_from_env("영어", {}) is None  # 키·주소가 없으면 닫힌다
    assert chat_model_from_env(env) is not None
