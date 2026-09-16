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

from app.api.store import CallRecord, CallStore
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

        # find_active와 create를 store 안에서 락으로 묶어 한 번에 처리한다.
        # 따로 부르면 sync 라우트가 스레드풀에서 도는 동안 두 스레드가 모두
        # "활성 통화 없음"을 보고 둘 다 전화를 걸 수 있다.
        call, created = store.find_active_or_create(body.elder_id, trigger_type="requested")
        if not created:
            # 두 번 누르는 것은 오류가 아니다. 전화가 안 오는 것 같아서
            # 다시 누른 것이므로, 그 통화의 대기 화면으로 보낸다.
            return JSONResponse(
                status_code=409,
                content={"call_id": call.call_id, "status": "in_progress"},
            )

        return _dial(call)

    def _dial(call: CallRecord) -> JSONResponse:
        phone = store.find_elder(call.elder_id)
        try:
            sid = telephony.place_call(to=phone, answer_url=answer_url)
        except Exception:
            # 발신 자체가 실패했다 — 실제 통화는 나가지 않았다. 안전하게
            # 실패 처리해 재시도를 열어준다.
            store.mark_failed(call.call_id)
            logger.exception("발신 실패 call_id=%s", call.call_id)
            raise HTTPException(status_code=502, detail="전화를 걸지 못했습니다")

        try:
            store.attach_sid(call.call_id, sid)
            pending_tokens[sid] = secrets.token_urlsafe(24)
            registry.issue(pending_tokens[sid], str(call.call_id))
        except Exception:
            # 여기서부터는 전화가 이미 걸렸다 — Telephony에는 취소/끊기
            # 수단이 없으므로 그 통화를 멈출 수 없다. 하지만 토큰이 없으면
            # 그 통화는 VoiceML에서 404로 끝나 어차피 오디오가 붙지 않는다.
            # '진행 중'으로 영원히 잠그면(이번 버그) 그 어르신은 다시는
            # 요청할 수 없게 되는데, 이는 절대 복구가 안 된다. 반면 실패로
            # 돌려 재시도를 열어주면 최악의 경우 전화가 중복으로 한 번 더
            # 울리는 정도다 — 복구 가능한 쪽을 택한다.
            pending_tokens.pop(sid, None)
            store.mark_failed(call.call_id)
            logger.exception(
                "발신 후 처리 실패 call_id=%s sid=%s — 통화가 걸렸어도 연결되지 않는다",
                call.call_id,
                sid,
            )
            raise HTTPException(status_code=502, detail="통화 연결 준비에 실패했습니다")

        return JSONResponse(
            status_code=202,
            content={"call_id": call.call_id, "status": call.trigger_type},
        )

    @app.post("/v1/voiceml")
    def voiceml(CallId: str = Form(...)) -> Response:
        """어르신이 받았다. 오디오를 우리 소켓으로 끌어온다.

        pop이 아니라 get이다 — 사업자 웹훅은 느리거나 실패한 ACK에 재전송을
        한다. 정상 동작이므로 같은 CallId의 재전송에는 같은 VoiceML을
        돌려줘야 한다. 모르는 CallId만 여전히 404다.
        """
        token = pending_tokens.get(CallId)
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
