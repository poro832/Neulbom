"""앱 'AI 채팅' 주소 — 어르신의 글 대화와 보호자의 요약 조회.

  POST /v1/me/chat                 어르신 열쇠. 말 한 마디를 보내면 AI의 답이 온다.
  GET  /v1/elders/{id}/chats       보호자 열쇠. 어르신이 공유에 동의했을 때만 **요약**이 보인다(원문은 보이지 않는다).

위급한 말의 보호자 알림은 어르신의 공유 동의와 상관없이 나간다(서비스가 처리). 알림에는 말 내용이 없다.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.api.app_data import MAX_ELDER_ID, iso_kst
from app.chat.persona import clean_persona
from app.chat.service import MAX_REQUEST_CHARS, ChatLimitReached, ChatSessionNotFound, ChatUnavailable
from app.chat.translate import MAX_TRANSLATE_CHARS, TranslateLimitReached, TranslateUnavailable, clean_language

logger = logging.getLogger(__name__)

CHAT_CLOSED = "AI 채팅은 아직 준비 중이에요"
CHAT_BUSY = "지금은 대답하기 어려워요. 잠시 뒤에 다시 해 주세요"
CHAT_LIMIT = "오늘은 이야기를 많이 나눴어요. 내일 또 이야기해요"
CHAT_EMPTY = "하고 싶은 말씀을 적어 주세요"
CHAT_NOT_FOUND = "그 대화를 찾을 수 없어요"
TRANSLATE_CLOSED = "번역은 아직 준비 중이에요"
TRANSLATE_BUSY = "지금은 번역하기 어려워요. 잠시 뒤에 다시 해 주세요"
TRANSLATE_LIMIT = "오늘은 번역을 많이 했어요. 내일 또 해 보세요"
TRANSLATE_LANGUAGE = "지원하지 않는 언어예요"
MAX_ID = 2**62
PREVIEW_CHARS = 40


def _preview(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS] + "…"


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TRANSLATE_CHARS)
    language: str = Field(max_length=16)  # en · ja · zh · vi · th · ru


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_REQUEST_CHARS)
    persona: str | None = Field(default=None, max_length=40)  # 어르신이 지은 AI 친구 이름(서버가 거른다)
    session_id: int | None = Field(default=None, ge=1, le=2**62)  # 지난 대화에 이어 말할 때 그 대화 번호



def add_chat_routes(app: FastAPI, *, data, guarded, guardian_id_of, ready_elder_id_of, owned_elder) -> None:
    service = data.chat

    @app.post("/v1/me/chat")
    @guarded
    def send_chat(body: ChatRequest, authorization: str | None = Header(default=None)) -> dict:
        elder_id = ready_elder_id_of(authorization)
        try:
            result = service.send(elder_id, body.message, clean_persona(body.persona), body.session_id)
        except ValueError:
            raise HTTPException(status_code=422, detail=CHAT_EMPTY)
        except ChatSessionNotFound:
            raise HTTPException(status_code=404, detail=CHAT_NOT_FOUND)
        except ChatLimitReached:
            raise HTTPException(status_code=429, detail=CHAT_LIMIT)
        except ChatUnavailable:
            # 모델이 없으면 '준비 중', 있는데 못 만들었으면 '잠시 뒤에'. 위급한 말은 어느 쪽이든 서비스가 먼저 알린다.
            raise HTTPException(status_code=503, detail=CHAT_BUSY if service.available else CHAT_CLOSED)
        # 말 내용은 로그에 남기지 않는다.
        logger.info("채팅 응답 elder_id=%s urgent=%s", elder_id, result.urgent is not None)
        return {"reply": result.reply, "urgent": result.urgent is not None}

    @app.post("/v1/me/translate")
    @guarded
    def translate(body: TranslateRequest, authorization: str | None = Header(default=None)) -> dict:
        """AI의 말을 어르신이 설정한 언어로 번역한다. 번역문은 저장하지 않고, 말 내용은 로그에 남기지 않는다."""
        elder_id = ready_elder_id_of(authorization)
        language = clean_language(body.language)
        if language is None:
            raise HTTPException(status_code=422, detail=TRANSLATE_LANGUAGE)
        try:
            text = service.translate(elder_id, body.text, language)
        except ValueError:
            raise HTTPException(status_code=422, detail=CHAT_EMPTY)
        except TranslateLimitReached:
            raise HTTPException(status_code=429, detail=TRANSLATE_LIMIT)
        except TranslateUnavailable:
            # 번역기가 없으면 '준비 중', 있는데 못 만들었으면 '잠시 뒤에'.
            raise HTTPException(status_code=503, detail=TRANSLATE_BUSY if service.translator_available else TRANSLATE_CLOSED)
        return {"text": text, "language": language}

    @app.get("/v1/me/chats")
    @guarded
    def my_chats(limit: int = Query(default=30, ge=1, le=50), authorization: str | None = Header(default=None)) -> dict:
        """어르신 본인의 지난 대화 목록(앱 햄버거 메뉴). 원문이 남아 있는 30일 안쪽만 보인다."""
        elder_id = ready_elder_id_of(authorization)
        return {
            "sessions": [
                {"session_id": s.session_id, "started_at": iso_kst(s.started_at), "preview": _preview(s.preview)}
                for s in service.my_sessions(elder_id, limit=limit)
            ]
        }

    @app.get("/v1/me/chats/{session_id}")
    @guarded
    def my_chat(session_id: int = Path(ge=1, le=MAX_ID), authorization: str | None = Header(default=None)) -> dict:
        elder_id = ready_elder_id_of(authorization)
        messages = service.my_session_messages(elder_id, session_id)
        if messages is None:
            raise HTTPException(status_code=404, detail=CHAT_NOT_FOUND)
        return {
            "session_id": session_id,
            "messages": [{"role": m.role, "text": m.text, "created_at": iso_kst(m.created_at)} for m in messages],
        }

    @app.get("/v1/elders/{elder_id}/chats")
    @guarded
    def elder_chats(
        elder_id: int = Path(ge=1, le=MAX_ELDER_ID),
        limit: int = Query(default=10, ge=1, le=30),
        authorization: str | None = Header(default=None),
    ) -> dict:
        guardian_id = guardian_id_of(authorization)
        owned_elder(guardian_id, elder_id)
        # 어르신이 공유에 동의하지 않았으면 요약을 만들지도 않는다 — 동의 없는 대화는 처리하지 않는다.
        if not data.content.share_agreed(elder_id):
            return {"share_agreed": False, "chats": []}
        return {
            "share_agreed": True,
            "chats": [
                {"session_id": s.session_id, "started_at": iso_kst(s.started_at), "summary": s.summary}
                for s in service.summaries(elder_id, limit=limit)
            ],
        }
