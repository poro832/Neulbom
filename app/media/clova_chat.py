"""CLOVA Studio 대화 생성 어댑터 — 어르신의 말에 이어 할 말을 만든다.

ClovaSpeech/ClovaVoice와 같은 패턴이다. 전송 계층을 주입받으므로 키가 없어도
규약 전체가 테스트로 검증된다.

**이 모델은 점수에 관여하지 않는다.** 위험 판정은 규칙이 하고 LLM은 대화만
한다 — 그게 이 서비스의 간판 주장이다. 그래서 시스템 프롬프트에도 상태를
평가하거나 점수를 매기라는 말을 넣지 않는다.

다만 **모델이 지표에 간접적으로 닿는다.** 말이 길어지면 AI 발화 시간이
늘고, 그것이 지표의 분모(통화 전체 − AI 발화)를 바꾼다. 모델이나 응답 길이
설정을 바꾸면 그 전후 점수를 같은 시계열로 비교할 수 없다 —
CALCULATOR_VERSION과 같은 성질이라 결과에 함께 기록해야 한다.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Sequence
from typing import Protocol

import httpx

from app.media.conversation import Turn

logger = logging.getLogger(__name__)

# 경량 모델. 짧은 한국어 턴이고 지연이 품질이라 큰 모델을 쓸 이유가 없다.
# 이미지도 다루지 않으므로 멀티모달 능력에 돈을 낼 필요가 없다.
DEFAULT_MODEL = "HCX-DASH-002"

# 응답 길이 상한. 세 가지가 같은 방향을 가리킨다.
#   1) 지연  — 길수록 합성이 오래 걸리고 어르신이 침묵을 듣는다
#   2) TTS   — 문장당 200자, 전체 2,000자 제약이 있다
#   3) 지표  — 응답 길이가 들쭉날쭉하면 분모가 흔들린다
#
# 150이라는 값에 근거는 없다. 다만 점수 임계값과 달리 이건 대화 정책이라
# 틀려도 숫자가 틀리지 않는다 — 실제 통화를 들어 보고 조정할 자리다.
DEFAULT_MAX_TOKENS = 150

# 낮게 둔다. 매번 다른 말을 하는 것보다 안정적인 편이 낫고, 어르신 대상
# 대화에서 창의성은 위험 요소에 가깝다.
DEFAULT_TEMPERATURE = 0.4

DEFAULT_SYSTEM_PROMPT = """당신은 독거 어르신께 매일 안부 전화를 드리는 다정한 말벗입니다.

- 항상 존댓말을 쓰고, 쉬운 말로 짧게 말합니다. 두세 문장을 넘기지 않습니다.
- 어르신의 말을 먼저 받아 주고, 그다음에 하나만 여쭙습니다. 한 번에 여러 개를 묻지 않습니다.
- 몸이 편찮다고 하시면 걱정하는 마음을 전하되, 진단이나 치료법은 말하지 않습니다. 병원에 가보셨는지 정도만 여쭙습니다.
- 어려운 낱말, 영어, 이모지, 괄호 설명을 쓰지 않습니다. 소리로 읽히는 말만 씁니다.
- 어르신이 대화를 마치고 싶어 하시면 따뜻하게 인사하고 마칩니다."""

# 문장이 끝난 자리. 잘린 응답을 여기까지만 남긴다.
_SENTENCE_END = re.compile(r"^.*[.!?。](?=\s|$)", re.S)

_SUCCESS_CODE = "20000"

_ROLE_OF = {"elder": "user", "ai": "assistant"}


class Transport(Protocol):
    def __call__(
        self, url: str, *, headers: dict, payload: dict, timeout: float
    ) -> bytes: ...


class ChatModel(Protocol):
    def reply(self, history: Sequence[Turn]) -> str:
        """지금까지의 대화를 보고 다음 말을 만든다."""
        ...


def _http_post(url: str, *, headers: dict, payload: dict, timeout: float) -> bytes:
    response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    if response.status_code >= 400:
        logger.error(
            "CLOVA Studio 요청 실패 status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
    response.raise_for_status()
    return response.content


class ClovaChat:
    """실제 생성. 자격 증명은 생성자로만 받는다 — 코드에 박지 않는다."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        model: str = DEFAULT_MODEL,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        transport: Transport = _http_post,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._url = f"{base_url.rstrip('/')}/v3/chat-completions/{model}"
        self.model = model
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self._temperature = temperature
        self._transport = transport
        self._timeout = timeout_seconds

    def reply(self, history: Sequence[Turn]) -> str:
        # 전송 실패는 여기서 삼키지 않는다. 삼키면 "모델이 할 말이 없었다"와
        # "모델이 죽었다"가 같은 빈 문자열이 되어 로그로 구분할 수 없다.
        # ConversationResponder가 잡아서 '이 턴은 침묵한다'로 처리한다.
        raw = self._transport(
            self._url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                # 사업자에 문의할 때 특정 요청을 짚는 값이다. 매번 새로 만든다.
                "X-NCP-CLOVASTUDIO-REQUEST-ID": uuid.uuid4().hex,
                "Content-Type": "application/json",
            },
            payload={
                "messages": self._messages(history),
                "maxTokens": self.max_tokens,
                "temperature": self._temperature,
            },
            timeout=self._timeout,
        )
        return self._content_of(raw)

    def _messages(self, history: Sequence[Turn]) -> list[dict]:
        messages = [{"role": "system", "content": self.system_prompt}]
        for turn in history:
            role = _ROLE_OF.get(turn.speaker)
            if role is None:
                # 모르는 화자를 끼워 넣으면 모델이 누가 한 말인지 잘못 읽는다.
                logger.warning("모르는 화자 — 대화에서 뺀다 speaker=%r", turn.speaker)
                continue
            messages.append({"role": role, "content": turn.text})
        return messages

    def _content_of(self, raw: bytes) -> str:
        try:
            body = json.loads(raw)
        except (ValueError, TypeError):
            logger.error("대화 응답을 읽을 수 없다 body=%r", raw[:200])
            return ""

        status = body.get("status") or {}
        if status.get("code") != _SUCCESS_CODE:
            # HTTP는 200인데 본문이 실패인 경우가 있다. 그대로 쓰면 오류
            # 메시지가 어르신에게 음성으로 나간다.
            logger.error(
                "CLOVA Studio가 실패를 알렸다 code=%s message=%s",
                status.get("code"),
                status.get("message"),
            )
            return ""

        result = body.get("result") or {}
        usage = result.get("usage") or {}
        if usage:
            # 토큰이 곧 요금이다. 남기지 않으면 청구서를 보고 나서야 안다.
            logger.info(
                "대화 생성 — 입력 %s 토큰, 출력 %s 토큰",
                usage.get("promptTokens"),
                usage.get("completionTokens"),
            )

        content = (result.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            logger.warning("대화 응답이 비어 있다 — 이 턴은 침묵한다")
            return ""
        content = content.strip()

        if result.get("finishReason") == "length":
            content = _trim_to_last_sentence(content)
        return content


def _trim_to_last_sentence(content: str) -> str:
    """토큰 상한에서 잘린 응답을 마지막 완결 문장까지만 남긴다.

    그대로 읽으면 어르신은 문장이 뚝 끊기는 소리를 듣는다. 다만 완결된
    문장이 하나도 없으면 그대로 둔다 — 잘린 한 문장이라도 말하는 편이
    침묵보다 낫다.
    """
    match = _SENTENCE_END.match(content)
    if match is None:
        logger.warning("응답이 잘렸는데 완결된 문장이 없다 — 그대로 말한다")
        return content
    logger.warning("응답이 토큰 상한에서 잘려 마지막 문장까지만 말한다")
    return match.group(0).strip()
