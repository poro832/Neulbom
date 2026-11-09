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
from app.chat.service import MAX_REQUEST_CHARS, ChatLimitReached, ChatUnavailable

logger = logging.getLogger(__name__)

CHAT_CLOSED = "AI 채팅은 아직 준비 중이에요"
CHAT_BUSY = "지금은 대답하기 어려워요. 잠시 뒤에 다시 해 주세요"
CHAT_LIMIT = "오늘은 이야기를 많이 나눴어요. 내일 또 이야기해요"
CHAT_EMPTY = "하고 싶은 말씀을 적어 주세요"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_REQUEST_CHARS)


def add_chat_routes(app: FastAPI, *, data, guarded, guardian_id_of, ready_elder_id_of, owned_elder) -> None:
    service = data.chat

    @app.post("/v1/me/chat")
    @guarded
    def send_chat(body: ChatRequest, authorization: str | None = Header(default=None)) -> dict:
        elder_id = ready_elder_id_of(authorization)
        try:
            result = service.send(elder_id, body.message)
        except ValueError:
            raise HTTPException(status_code=422, detail=CHAT_EMPTY)
        except ChatLimitReached:
            raise HTTPException(status_code=429, detail=CHAT_LIMIT)
        except ChatUnavailable:
            # 모델이 없으면 '준비 중', 있는데 못 만들었으면 '잠시 뒤에'. 위급한 말은 어느 쪽이든 서비스가 먼저 알린다.
            raise HTTPException(status_code=503, detail=CHAT_BUSY if service.available else CHAT_CLOSED)
        # 말 내용은 로그에 남기지 않는다.
        logger.info("채팅 응답 elder_id=%s urgent=%s", elder_id, result.urgent is not None)
        return {"reply": result.reply, "urgent": result.urgent is not None}

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
