"""CLOVA Studio 대화 생성 어댑터.

전송 계층을 주입받으므로 키 없이도 규약 전체가 검증된다.
"""

import json
import logging

import pytest

from app.media.clova_chat import DEFAULT_MODEL, ClovaChat
from app.media.conversation import Turn


class FakeTransport:
    def __init__(self, reply: bytes):
        self.reply = reply
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url: str, *, headers: dict, payload: dict, timeout: float) -> bytes:
        self.calls.append((url, headers, payload))
        return self.reply


def reply_of(content="반갑습니다", finish="stop", code="20000", tokens=(120, 30)):
    return json.dumps(
        {
            "status": {"code": code, "message": "OK"},
            "result": {
                "message": {"role": "assistant", "content": content},
                "finishReason": finish,
                "usage": {
                    "promptTokens": tokens[0],
                    "completionTokens": tokens[1],
                    "totalTokens": sum(tokens),
                },
            },
        }
    ).encode()


def make(reply=None, **kwargs):
    transport = FakeTransport(reply if reply is not None else reply_of())
    chat = ClovaChat(
        api_key="KEY",
        base_url="https://example.test",
        transport=transport,
        **kwargs,
    )
    return chat, transport


HISTORY = [Turn("elder", "안녕하세요"), Turn("ai", "반갑습니다"), Turn("elder", "밥 먹었어요")]


# ------------------------------------------------------------ 요청 형식


def test_the_model_name_is_in_the_path():
    chat, transport = make()

    chat.reply(HISTORY)

    url, _, _ = transport.calls[0]
    assert url == f"https://example.test/v3/chat-completions/{DEFAULT_MODEL}"


def test_the_api_key_is_a_bearer_token():
    """Speech는 X-CLOVASPEECH-API-KEY, Voice는 X-NCP-APIGW-*, 여기는 Bearer다.
    셋이 전부 다르다 — 섞으면 401이 나는데 원인이 안 보인다."""
    chat, transport = make()

    chat.reply(HISTORY)

    _, headers, _ = transport.calls[0]
    assert headers["Authorization"] == "Bearer KEY"
    assert headers["Content-Type"] == "application/json"


def test_each_request_carries_its_own_id():
    """사업자에 문의할 때 이 값으로 특정 요청을 짚는다. 같으면 못 짚는다."""
    chat, transport = make()

    chat.reply(HISTORY)
    chat.reply(HISTORY)

    first = transport.calls[0][1]["X-NCP-CLOVASTUDIO-REQUEST-ID"]
    second = transport.calls[1][1]["X-NCP-CLOVASTUDIO-REQUEST-ID"]
    assert first and second and first != second


def test_our_turns_become_the_apis_roles():
    """elder는 user, ai는 assistant다. 뒤집히면 모델이 자기 말을 어르신
    말로 읽고, 어르신에게 할 말을 자기가 이미 했다고 여긴다."""
    chat, transport = make()

    chat.reply(HISTORY)

    _, _, payload = transport.calls[0]
    assert payload["messages"] == [
        {"role": "system", "content": chat.system_prompt},
        {"role": "user", "content": "안녕하세요"},
        {"role": "assistant", "content": "반갑습니다"},
        {"role": "user", "content": "밥 먹었어요"},
    ]


def test_the_reply_length_is_capped():
    """길면 어르신이 기다리고, TTS 상한에 걸리고, AI 발화 길이가 들쭉날쭉해
    지표의 분모가 흔들린다. 세 가지가 같은 방향을 가리킨다."""
    chat, transport = make()

    chat.reply(HISTORY)

    _, _, payload = transport.calls[0]
    assert payload["maxTokens"] == chat.max_tokens


# ------------------------------------------------------------ 응답


def test_the_generated_text_comes_back():
    chat, _ = make(reply=reply_of("저런, 많이 불편하시겠어요"))

    assert chat.reply(HISTORY) == "저런, 많이 불편하시겠어요"


def test_a_business_error_code_is_not_treated_as_success(caplog):
    """HTTP는 200인데 본문 status.code가 실패인 경우가 있다.

    그걸 그대로 쓰면 오류 메시지가 어르신에게 음성으로 나간다.
    """
    chat, _ = make(reply=reply_of(content="", code="42901"))

    with caplog.at_level(logging.ERROR, logger="app.media.clova_chat"):
        assert chat.reply(HISTORY) == ""

    assert any("42901" in record.getMessage() for record in caplog.records)


def test_a_truncated_reply_is_trimmed_to_the_last_finished_sentence(caplog):
    """finishReason이 length면 토큰 상한에서 잘린 것이다.

    그대로 읽으면 어르신은 문장이 뚝 끊기는 소리를 듣는다. 마지막 완결
    문장까지만 말하는 편이 낫다.
    """
    chat, _ = make(reply=reply_of("밥은 드셨어요? 오늘 날씨가 좋은데 산책이라도", finish="length"))

    with caplog.at_level(logging.WARNING, logger="app.media.clova_chat"):
        assert chat.reply(HISTORY) == "밥은 드셨어요?"

    assert caplog.records


def test_a_truncated_reply_with_no_finished_sentence_is_kept():
    """잘린 문장 하나뿐이면 버리는 것보다 말하는 편이 낫다 — 침묵이 더 나쁘다."""
    chat, _ = make(reply=reply_of("오늘 날씨가 좋은데 산책이라도", finish="length"))

    assert chat.reply(HISTORY) == "오늘 날씨가 좋은데 산책이라도"


def test_token_usage_is_logged(caplog):
    """토큰이 곧 요금이다. 남기지 않으면 청구서를 보고 나서야 안다."""
    chat, _ = make(reply=reply_of(tokens=(500, 80)))

    with caplog.at_level(logging.INFO, logger="app.media.clova_chat"):
        chat.reply(HISTORY)

    message = " ".join(record.getMessage() for record in caplog.records)
    assert "500" in message and "80" in message


def test_a_broken_reply_yields_silence_not_a_crash():
    chat, _ = make(reply=b"<html>oops</html>")

    assert chat.reply(HISTORY) == ""


def test_a_transport_failure_is_raised_for_the_caller_to_handle():
    """ConversationResponder가 이 예외를 잡아 '이 턴은 침묵한다'로 처리한다.

    여기서 삼키고 빈 문자열을 주면 '모델이 할 말이 없었다'와 '모델이
    죽었다'가 같은 값이 되어, 로그만 보고는 구분할 수 없다.
    """

    def exploding(url, *, headers, payload, timeout):
        raise RuntimeError("연결 실패")

    chat = ClovaChat(api_key="KEY", base_url="https://example.test", transport=exploding)

    with pytest.raises(RuntimeError):
        chat.reply(HISTORY)
