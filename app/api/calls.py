"""트리거 API (전화망 설계 5장).

앱 버튼은 "전화를 걸어 달라"는 신호다. 인앱 마이크도 소켓도 없다.
스케줄러의 정기 통화도 같은 경로를 쓰고 trigger_type만 다르다.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.api.store import CallStore
from app.media.stream_server import CallRegistry
from app.telephony.client import Telephony
from app.telephony.voiceml import connect_stream, say_and_hangup

logger = logging.getLogger(__name__)


class CallRequest(BaseModel):
    elder_id: int


def build_app(
    store: CallStore,
    telephony: Telephony,
    registry: CallRegistry,
    public_base_url: str,
    stream_base_url: str,
) -> FastAPI:
    app = FastAPI(title="늘봄 통화 트리거")
    answer_url = f"{public_base_url.rstrip('/')}/v1/voiceml"
    action_url = f"{public_base_url.rstrip('/')}/v1/stream-ended"
    stream_url = f"{stream_base_url.rstrip('/')}/v1/stream"

    # CallId → 그 통화의 1회용 토큰. VoiceML을 만들 때 심는다.
    pending_tokens: dict[str, str] = {}

    @app.post("/v1/calls/request")
    def request_call(body: CallRequest) -> JSONResponse:
        if store.find_elder(body.elder_id) is None:
            raise HTTPException(status_code=404, detail="등록되지 않은 어르신입니다")

        active = store.find_active(body.elder_id)
        if active is not None:
            # 두 번 누르는 것은 오류가 아니다. 전화가 안 오는 것 같아서
            # 다시 누른 것이므로, 그 통화의 대기 화면으로 보낸다.
            return JSONResponse(
                status_code=409,
                content={"call_id": active.call_id, "status": "in_progress"},
            )

        return _place(body.elder_id, trigger_type="requested")

    def _place(elder_id: int, trigger_type: str) -> JSONResponse:
        phone = store.find_elder(elder_id)
        call = store.create(elder_id, trigger_type)
        try:
            sid = telephony.place_call(to=phone, answer_url=answer_url)
        except Exception:
            # 실패한 통화를 '진행 중'으로 남기면 그 어르신은 영원히 409를 받는다.
            store.mark_failed(call.call_id)
            logger.exception("발신 실패 call_id=%s", call.call_id)
            raise HTTPException(status_code=502, detail="전화를 걸지 못했습니다")

        store.attach_sid(call.call_id, sid)
        pending_tokens[sid] = secrets.token_urlsafe(24)
        registry.issue(pending_tokens[sid], str(call.call_id))
        return JSONResponse(
            status_code=202,
            content={"call_id": call.call_id, "status": trigger_type},
        )

    @app.post("/v1/voiceml")
    def voiceml(CallId: str = Form(...)) -> Response:
        """어르신이 받았다. 오디오를 우리 소켓으로 끌어온다."""
        token = pending_tokens.pop(CallId, None)
        if token is None:
            # 우리가 만들지 않은 통화다. 토큰을 내주면 안 된다.
            logger.warning("모르는 CallId로 VoiceML 요청 CallId=%s", CallId)
            raise HTTPException(status_code=404, detail="unknown call")
        return Response(
            content=connect_stream(
                stream_url=stream_url, action_url=action_url, token=token
            ),
            media_type="application/xml",
        )

    @app.post("/v1/stream-ended")
    def stream_ended(CallId: str = Form(...), StreamEvent: str = Form("")) -> Response:
        """스트림이 끝났다. 마무리 인사를 하고 끊는다."""
        logger.info("스트림 종료 CallId=%s event=%s", CallId, StreamEvent)
        return Response(
            content=say_and_hangup("오늘도 좋은 하루 보내세요. 안녕히 계세요."),
            media_type="application/xml",
        )

    return app
