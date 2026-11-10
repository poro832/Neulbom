"""LLM 게이트웨이(OpenAI 호환 API) 대화 어댑터 — 앱의 'AI 채팅'(글 대화)과 채팅 요약에 쓴다.

수업 계정에서는 Bedrock을 **직접** 부를 수 없다(사용량 제어가 안 돼 과금 사고 위험이 있어 권한이 회수된다).
대신 사용 한도가 걸린 **게이트웨이 키**로 부른다. 게이트웨이는 OpenAI 호환이라
`POST {base_url}/chat/completions`에 Bearer 키를 보내고, 모델은 `bedrock-haiku` 같은 게이트웨이의 별칭이다.

전화 대화는 CLOVA(`clova_chat.py`)가 맡는다. 이쪽은 어르신이 앱에서 글로 하는 말동무 대화다.
**점수에는 닿지 않는다.** 위험 점수는 전화 통화에서만 규칙으로 계산한다.

키는 서버 환경 변수에만 있고 앱에는 없다. 코드·로그·저장소에 남기지 않는다. 전송 계층을 주입받으므로 키 없이도
규약 전체가 테스트로 검증된다.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence

import httpx

from app.media.clova_chat import Transport
from app.media.conversation import Turn

logger = logging.getLogger(__name__)

# 한도 안에서 쓸 수 있는 모델: bedrock-haiku · bedrock-sonnet · bedrock-gpt-5.6-luna.
# 짧은 한국어 글 대화라 가볍고 빠른 모델이면 충분하다. LLM_GATEWAY_MODEL로 바꾼다.
DEFAULT_MODEL = "bedrock-haiku"

_ROLE_OF = {"elder": "user", "ai": "assistant"}


def _http_post(url: str, *, headers: dict, payload: dict, timeout: float) -> bytes:
    """게이트웨이 호출. 실패 로그에 'LLM 게이트웨이'라고 적는다(CLOVA와 같은 함수를 쓰면 CLOVA 오류처럼 읽힌다)."""
    response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    if response.status_code >= 400:
        # 본문에는 게이트웨이가 준 이유가 있다(예: 키 오류, 한도 초과, 없는 모델). 요청 헤더의 키는 싣지 않는다.
        logger.error("LLM 게이트웨이 요청 실패 status=%s body=%s", response.status_code, response.text[:500])
    response.raise_for_status()
    return response.content


class GatewayError(RuntimeError):
    """게이트웨이가 알아볼 수 없는 응답을 줬다."""


CHAT_SYSTEM_PROMPT = """당신은 혼자 사는 어르신의 말동무 '늘봄이'입니다. 앱에서 글로 대화합니다.
- 존댓말로 따뜻하고 쉽게, 두세 문장 안으로 답합니다. 어려운 말과 영어를 쓰지 않습니다.
- 어르신이 궁금해하시는 것(날씨, 음식, 생활 정보, 건강 상식 등)은 아는 만큼 쉽게 알려 드립니다. 모르면 모른다고 말합니다.
- 병이나 약은 일반적인 이야기만 합니다. 진단하거나 약을 정해 드리지 않습니다. 몸이 많이 불편하시면 가족이나 병원에 알리시라고 권합니다.
- 돈, 투자, 보험, 개인정보(주민등록번호, 계좌, 비밀번호)는 묻지도 받지도 않습니다. 그런 이야기가 나오면 가족과 상의하시라고 권합니다.
- 이모지, 목록, 마크다운 없이 대화체 문장으로만 씁니다."""

SUMMARY_SYSTEM_PROMPT = """당신은 어르신과 AI의 글 대화를 보호자에게 전하는 기록자입니다.
- 어르신이 실제로 한 말과 궁금해하신 것을 두세 문장으로 전합니다. 백오십 자 안팎, 존댓말("~하셨어요", "~궁금해하셨어요").
- 추측, 평가, 조언, 병이나 마음 상태의 판단을 쓰지 않습니다. 무엇이 의심된다고 말하지 않습니다.
- 이모지, 목록, 따옴표 없이 문장만 씁니다."""


def _endpoint(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


class GatewayChat:
    """실제 생성. 자격 증명은 생성자로만 받는다 — 코드에 박지 않는다."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        model: str = DEFAULT_MODEL,
        system_prompt: str = CHAT_SYSTEM_PROMPT,
        max_tokens: int = 300,
        temperature: float = 0.5,
        transport: Transport = _http_post,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._api_key = api_key
        self._url = _endpoint(base_url)
        self.model = model
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self._temperature = temperature
        self._transport = transport
        self._timeout = timeout_seconds

    def reply(self, history: Sequence[Turn]) -> str:
        # 전송 실패는 여기서 삼키지 않는다 — 호출자가 '지금은 대답하기 어려워요'로 알린다.
        raw = self._transport(
            self._url,
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            payload={
                "model": self.model,
                "messages": [{"role": "system", "content": self.system_prompt}, *self._messages(history)],
                "max_tokens": self.max_tokens,
                "temperature": self._temperature,
            },
            timeout=self._timeout,
        )
        return self._text_of(raw)

    @staticmethod
    def _messages(history: Sequence[Turn]) -> list[dict]:
        """같은 쪽이 이어지면 한 덩이로 합치고, AI 말로 시작하면 그 앞부분을 뺀다(모델이 user부터 읽게)."""
        merged: list[dict] = []
        for turn in history:
            role = _ROLE_OF.get(turn.speaker)
            text = turn.text.strip()
            if role is None or not text:
                continue
            if merged and merged[-1]["role"] == role:
                merged[-1]["content"] += "\n" + text
            else:
                merged.append({"role": role, "content": text})
        while merged and merged[0]["role"] != "user":
            merged.pop(0)
        return merged

    @staticmethod
    def _text_of(raw: bytes) -> str:
        try:
            body = json.loads(raw)
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            logger.error("게이트웨이 응답을 읽을 수 없다 body=%r", raw[:200])
            raise GatewayError("읽을 수 없는 응답") from exc
        usage = body.get("usage") or {}
        if usage:
            # 토큰이 곧 요금(한도)이다. 남기지 않으면 청구서를 보고 나서야 안다.
            logger.info("채팅 생성 — 입력 %s 토큰, 출력 %s 토큰", usage.get("prompt_tokens"), usage.get("completion_tokens"))
        if isinstance(content, list):  # 일부 게이트웨이는 조각 목록으로 준다
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        text = content.strip() if isinstance(content, str) else ""
        if not text:
            logger.warning("게이트웨이 응답이 비어 있다 finish=%s", choice.get("finish_reason"))
        return text


def gateway_settings_from_env(env=os.environ) -> tuple[str, str] | None:
    """(키, 주소). 둘 중 하나라도 없으면 None(채팅은 닫힌다)."""
    key = (env.get("LLM_GATEWAY_API_KEY") or "").strip()
    base_url = (env.get("LLM_GATEWAY_BASE_URL") or "").strip()
    return (key, base_url) if key and base_url else None


def chat_model_from_env(env=os.environ, *, transport: Transport | None = None) -> GatewayChat | None:
    settings = gateway_settings_from_env(env)
    if settings is None:
        return None
    key, base_url = settings
    extra = {} if transport is None else {"transport": transport}
    return GatewayChat(key, base_url, model=env.get("LLM_GATEWAY_MODEL") or DEFAULT_MODEL, **extra)


def summary_model_from_env(env=os.environ, *, transport: Transport | None = None) -> GatewayChat | None:
    settings = gateway_settings_from_env(env)
    if settings is None:
        return None
    key, base_url = settings
    extra = {} if transport is None else {"transport": transport}
    return GatewayChat(
        key,
        base_url,
        model=env.get("LLM_GATEWAY_MODEL") or DEFAULT_MODEL,
        system_prompt=SUMMARY_SYSTEM_PROMPT,
        max_tokens=200,
        temperature=0.2,
        **extra,
    )
