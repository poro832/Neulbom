"""Bedrock 대화 어댑터 — 전송 계층을 주입받으므로 키 없이도 규약 전체가 검증된다."""

import json
import logging

import pytest

from app.media.bedrock_chat import (
    DEFAULT_MODEL,
    BedrockChat,
    BedrockError,
    bedrock_key_from_env,
    chat_model_from_env,
)
from app.media.conversation import Turn


class FakeTransport:
    def __init__(self, reply: bytes):
        self.reply = reply
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url: str, *, headers: dict, payload: dict, timeout: float) -> bytes:
        self.calls.append((url, headers, payload))
        return self.reply


def reply_of(text="안녕하세요, 어르신.", usage=(40, 12)):
    return json.dumps(
        {
            "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": usage[0], "outputTokens": usage[1]},
        }
    ).encode()


def make(reply=None, **kwargs):
    transport = FakeTransport(reply if reply is not None else reply_of())
    chat = BedrockChat("KEY", transport=transport, **kwargs)
    return chat, transport


def test_calls_the_converse_endpoint_with_the_bearer_key_and_an_encoded_model_name():
    chat, transport = make(model="apac.anthropic.claude-haiku-4-5-20251001-v1:0")

    chat.reply([Turn("elder", "안녕")])

    url, headers, _ = transport.calls[0]
    assert url == (
        "https://bedrock-runtime.ap-northeast-2.amazonaws.com/model/"
        "apac.anthropic.claude-haiku-4-5-20251001-v1%3A0/converse"
    )
    assert headers["Authorization"] == "Bearer KEY"


def test_default_model_is_a_haiku_inference_profile():
    assert DEFAULT_MODEL.startswith("global.anthropic.claude-haiku")


def test_sends_system_prompt_and_alternating_messages_ending_with_the_elder():
    chat, transport = make()

    text = chat.reply([Turn("elder", "오늘 날씨 어때?"), Turn("ai", "맑아요."), Turn("elder", "산책 갈까")])

    payload = transport.calls[0][2]
    assert payload["system"][0]["text"] == chat.system_prompt
    assert [m["role"] for m in payload["messages"]] == ["user", "assistant", "user"]
    assert payload["messages"][-1]["content"][0]["text"] == "산책 갈까"
    assert payload["inferenceConfig"]["maxTokens"] == chat.max_tokens
    assert text == "안녕하세요, 어르신."


def test_same_speaker_turns_are_merged_and_a_leading_ai_turn_is_dropped():
    chat, transport = make()

    chat.reply([Turn("ai", "먼저 인사"), Turn("elder", "응"), Turn("elder", "그래"), Turn("ai", "네")])

    roles = [m["role"] for m in transport.calls[0][2]["messages"]]
    assert roles == ["user", "assistant"]
    assert transport.calls[0][2]["messages"][0]["content"][0]["text"] == "응\n그래"


def test_empty_answer_is_an_empty_string_and_junk_raises():
    chat, _ = make(reply=reply_of(""))
    assert chat.reply([Turn("elder", "응")]) == ""

    broken, _ = make(reply=b"<html>")
    with pytest.raises(BedrockError):
        broken.reply([Turn("elder", "응")])


def test_transport_failures_are_not_swallowed():
    def boom(url, *, headers, payload, timeout):
        raise TimeoutError("느림")

    with pytest.raises(TimeoutError):
        BedrockChat("KEY", transport=boom).reply([Turn("elder", "응")])


def test_logs_tokens_but_never_the_key_or_the_words(caplog):
    chat, _ = make()
    with caplog.at_level(logging.INFO):
        chat.reply([Turn("elder", "비밀번호는 1234예요")])

    assert "입력 40 토큰, 출력 12 토큰" in caplog.text
    assert "KEY" not in caplog.text and "1234" not in caplog.text


def test_the_model_is_closed_without_a_key_and_configurable_with_one():
    assert bedrock_key_from_env({}) is None
    assert chat_model_from_env({}) is None
    assert chat_model_from_env({"AWS_BEARER_TOKEN_BEDROCK": "  "}) is None

    chat = chat_model_from_env({"AWS_BEARER_TOKEN_BEDROCK": "K", "BEDROCK_CHAT_MODEL": "m", "BEDROCK_REGION": "us-east-1"})
    assert chat.model == "m"
    assert "us-east-1" in chat._url
