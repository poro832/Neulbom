"""AWS Bedrock 대화 어댑터 — 앱의 'AI 채팅'(글 대화)과 채팅 요약에 쓴다.

전화 대화는 CLOVA(`clova_chat.py`)가 맡는다. 이쪽은 어르신이 앱에서 글로 하는 말동무 대화다.
**점수에는 닿지 않는다.** 위험 점수는 전화 통화에서만 규칙으로 계산한다.

Bedrock **API 키**(긴 수명 키)를 쓴다 — 서버 환경 변수 `AWS_BEARER_TOKEN_BEDROCK`. IAM 역할을 건드리지
않고 키 하나로 호출한다. 키는 서버에만 있고 앱에는 없다. 코드·로그·저장소에 남기지 않는다.

Converse API(모델이 달라도 같은 요청 모양)로 REST 호출한다. 전송 계층을 주입받으므로 키 없이도
규약 전체가 테스트로 검증된다.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from urllib.parse import quote

import httpx

from app.media.clova_chat import Transport
from app.media.conversation import Turn

logger = logging.getLogger(__name__)

DEFAULT_REGION = "ap-northeast-2"

# 서울 리전에서 Haiku 5.5는 모델 번호가 아니라 '추론 프로필' 이름으로만 부를 수 있다(직접 호출은 거절된다).
# 짧은 한국어 글 대화라 가볍고 빠른 모델이면 충분하다. BEDROCK_CHAT_MODEL로 바꾼다.
DEFAULT_MODEL = "global.anthropic.claude-haiku-5-5"

_ROLE_OF = {"elder": "user", "ai": "assistant"}


def _http_post(url: str, *, headers: dict, payload: dict, timeout: float) -> bytes:
    """Bedrock 호출. 실패 로그에 'Bedrock'이라고 적는다(CLOVA와 같은 함수를 쓰면 로그가 CLOVA 오류처럼 읽힌다)."""
    response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    if response.status_code >= 400:
        # 본문에는 Bedrock이 준 이유가 있다(예: 키 형식 오류, 모델 접근 거절). 요청 헤더의 키는 싣지 않는다.
        logger.error("Bedrock 요청 실패 status=%s body=%s", response.status_code, response.text[:500])
    response.raise_for_status()
    return response.content


class BedrockError(RuntimeError):
    """Bedrock이 알아볼 수 없는 응답을 줬다."""


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


class BedrockChat:
    """실제 생성. 자격 증명은 생성자로만 받는다 — 코드에 박지 않는다."""

    def __init__(
        self,
        api_key: str,
        *,
        region: str = DEFAULT_REGION,
        model: str = DEFAULT_MODEL,
        system_prompt: str = CHAT_SYSTEM_PROMPT,
        max_tokens: int = 300,
        temperature: float = 0.5,
        transport: Transport = _http_post,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._api_key = api_key
        # 모델 이름의 ':'도 인코딩해야 서명 없는 키 호출이 같은 주소로 읽힌다.
        self._url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{quote(model, safe='')}/converse"
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
                "system": [{"text": self.system_prompt}],
                "messages": self._messages(history),
                "inferenceConfig": {"maxTokens": self.max_tokens, "temperature": self._temperature},
            },
            timeout=self._timeout,
        )
        return self._text_of(raw)

    @staticmethod
    def _messages(history: Sequence[Turn]) -> list[dict]:
        """Converse는 user로 시작해 user·assistant가 번갈아야 한다 — 같은 쪽이 이어지면 한 덩이로 합친다."""
        merged: list[dict] = []
        for turn in history:
            role = _ROLE_OF.get(turn.speaker)
            text = turn.text.strip()
            if role is None or not text:
                continue
            if merged and merged[-1]["role"] == role:
                merged[-1]["content"][0]["text"] += "\n" + text
            else:
                merged.append({"role": role, "content": [{"text": text}]})
        while merged and merged[0]["role"] != "user":
            merged.pop(0)
        return merged

    @staticmethod
    def _text_of(raw: bytes) -> str:
        try:
            body = json.loads(raw)
            parts = body["output"]["message"]["content"]
        except (ValueError, TypeError, KeyError) as exc:
            logger.error("Bedrock 응답을 읽을 수 없다 body=%r", raw[:200])
            raise BedrockError("읽을 수 없는 응답") from exc
        usage = body.get("usage") or {}
        if usage:
            # 토큰이 곧 요금이다. 남기지 않으면 청구서를 보고 나서야 안다.
            logger.info("채팅 생성 — 입력 %s 토큰, 출력 %s 토큰", usage.get("inputTokens"), usage.get("outputTokens"))
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
        if not text:
            logger.warning("Bedrock 응답이 비어 있다 stopReason=%s", body.get("stopReason"))
        return text


def bedrock_key_from_env(env=os.environ) -> str | None:
    """서버 환경 변수의 Bedrock API 키. 없으면 None(채팅은 닫힌다)."""
    return (env.get("AWS_BEARER_TOKEN_BEDROCK") or "").strip() or None


def chat_model_from_env(env=os.environ, *, transport: Transport | None = None) -> BedrockChat | None:
    key = bedrock_key_from_env(env)
    if key is None:
        return None
    extra = {} if transport is None else {"transport": transport}
    return BedrockChat(
        key,
        region=env.get("BEDROCK_REGION") or DEFAULT_REGION,
        model=env.get("BEDROCK_CHAT_MODEL") or DEFAULT_MODEL,
        **extra,
    )


def summary_model_from_env(env=os.environ, *, transport: Transport | None = None) -> BedrockChat | None:
    key = bedrock_key_from_env(env)
    if key is None:
        return None
    extra = {} if transport is None else {"transport": transport}
    return BedrockChat(
        key,
        region=env.get("BEDROCK_REGION") or DEFAULT_REGION,
        model=env.get("BEDROCK_CHAT_MODEL") or DEFAULT_MODEL,
        system_prompt=SUMMARY_SYSTEM_PROMPT,
        max_tokens=200,
        temperature=0.2,
        **extra,
    )
