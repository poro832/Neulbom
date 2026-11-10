"""LLM 게이트웨이(OpenAI 호환) 대화 어댑터 — 전송 계층을 주입받으므로 키 없이도 규약 전체가 검증된다."""

import json
import logging

import pytest

from app.media.conversation import Turn
from app.media.gateway_chat import (
    DEFAULT_MODEL,
    GatewayChat,
    GatewayError,
    chat_model_from_env,
    gateway_settings_from_env,
    summary_model_from_env,
)

BASE = "https://gateway.example.test/v1"


class FakeTransport:
    def __init__(self, reply: bytes):
        self.reply = reply
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url: str, *, headers: dict, payload: dict, timeout: float) -> bytes:
        self.calls.append((url, headers, payload))
        return self.reply


def reply_of(text="안녕하세요, 어르신.", usage=(40, 12), finish="stop"):
    return json.dumps(
        {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]},
        }
    ).encode()


def make(reply=None, **kwargs):
    transport = FakeTransport(reply if reply is not None else reply_of())
    chat = GatewayChat("KEY", BASE, transport=transport, **kwargs)
    return chat, transport


def test_calls_chat_completions_with_the_bearer_key_and_the_gateway_model_alias():
    chat, transport = make()

    chat.reply([Turn("elder", "안녕")])

    url, headers, payload = transport.calls[0]
    assert url == "https://gateway.example.test/v1/chat/completions"
    assert headers["Authorization"] == "Bearer KEY"
    assert payload["model"] == DEFAULT_MODEL == "bedrock-haiku"


@pytest.mark.parametrize(
    "base",
    ["https://g.test/v1", "https://g.test/v1/", "https://g.test/v1/chat/completions", "  https://g.test/v1  "],
)
def test_the_base_url_may_be_given_with_or_without_the_endpoint_path(base):
    transport = FakeTransport(reply_of())
    GatewayChat("KEY", base, transport=transport).reply([Turn("elder", "안녕")])
    assert transport.calls[0][0] == "https://g.test/v1/chat/completions"


def test_sends_the_system_prompt_first_and_alternating_messages_ending_with_the_elder():
    chat, transport = make()

    text = chat.reply([Turn("elder", "오늘 날씨 어때?"), Turn("ai", "맑아요."), Turn("elder", "산책 갈까")])

    payload = transport.calls[0][2]
    assert payload["messages"][0] == {"role": "system", "content": chat.system_prompt}
    assert [m["role"] for m in payload["messages"]] == ["system", "user", "assistant", "user"]
    assert payload["messages"][-1]["content"] == "산책 갈까"
    assert payload["max_tokens"] == chat.max_tokens
    assert text == "안녕하세요, 어르신."


def test_same_speaker_turns_are_merged_and_a_leading_ai_turn_is_dropped():
    chat, transport = make()

    chat.reply([Turn("ai", "먼저 인사"), Turn("elder", "응"), Turn("elder", "그래"), Turn("ai", "네")])

    messages = transport.calls[0][2]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant"]
    assert messages[1]["content"] == "응\n그래"


def test_list_shaped_content_is_joined_empty_answer_is_empty_and_junk_raises():
    parts = json.dumps(
        {"choices": [{"message": {"content": [{"type": "text", "text": "안녕"}, {"type": "text", "text": "하세요"}]}}]}
    ).encode()
    chat, _ = make(reply=parts)
    assert chat.reply([Turn("elder", "응")]) == "안녕하세요"

    empty, _ = make(reply=reply_of(""))
    assert empty.reply([Turn("elder", "응")]) == ""

    for junk in (b"<html>", b"{}", json.dumps({"choices": []}).encode()):
        broken, _ = make(reply=junk)
        with pytest.raises(GatewayError):
            broken.reply([Turn("elder", "응")])


def test_transport_failures_are_not_swallowed():
    def boom(url, *, headers, payload, timeout):
        raise TimeoutError("느림")

    with pytest.raises(TimeoutError):
        GatewayChat("KEY", BASE, transport=boom).reply([Turn("elder", "응")])


def test_logs_tokens_but_never_the_key_or_the_words(caplog):
    chat, _ = make()
    with caplog.at_level(logging.INFO):
        chat.reply([Turn("elder", "비밀번호는 1234예요")])

    assert "입력 40 토큰, 출력 12 토큰" in caplog.text
    assert "KEY" not in caplog.text and "1234" not in caplog.text


def test_a_rejected_request_is_logged_as_a_gateway_failure_with_the_reason_and_never_the_key(monkeypatch, caplog):
    import httpx

    def reject(url, **kwargs):
        return httpx.Response(429, json={"error": "budget exceeded"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", reject)
    chat = GatewayChat("SECRET-KEY-VALUE", BASE)

    with caplog.at_level(logging.ERROR), pytest.raises(httpx.HTTPStatusError):
        chat.reply([Turn("elder", "안녕")])

    assert "LLM 게이트웨이 요청 실패 status=429" in caplog.text and "budget exceeded" in caplog.text
    assert "CLOVA" not in caplog.text and "SECRET-KEY-VALUE" not in caplog.text


def test_the_chat_is_closed_unless_both_the_key_and_the_address_are_set():
    assert gateway_settings_from_env({}) is None
    assert chat_model_from_env({}) is None
    assert chat_model_from_env({"LLM_GATEWAY_API_KEY": "K"}) is None  # 주소가 없다
    assert chat_model_from_env({"LLM_GATEWAY_BASE_URL": BASE}) is None  # 키가 없다
    assert chat_model_from_env({"LLM_GATEWAY_API_KEY": "  ", "LLM_GATEWAY_BASE_URL": BASE}) is None


def test_the_models_are_configurable_and_the_summary_model_has_its_own_prompt():
    env = {"LLM_GATEWAY_API_KEY": "K", "LLM_GATEWAY_BASE_URL": BASE, "LLM_GATEWAY_MODEL": "bedrock-sonnet"}
    chat, summary = chat_model_from_env(env), summary_model_from_env(env)

    assert chat.model == summary.model == "bedrock-sonnet"
    assert chat.system_prompt != summary.system_prompt
    assert chat_model_from_env({"LLM_GATEWAY_API_KEY": "K", "LLM_GATEWAY_BASE_URL": BASE}).model == "bedrock-haiku"
