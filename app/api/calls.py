"""트리거 API (전화망 설계 5장).

앱 버튼은 "전화를 걸어 달라"는 신호다. 인앱 마이크도 소켓도 없다.
스케줄러의 정기 통화도 같은 경로를 쓰고 trigger_type만 다르다.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import datetime

from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.api.dialer import DialFailed, answer_url_for, dial, status_callback_url_for
from app.api.elder_directory import ElderDirectory
from app.api.guardian_auth import GuardianAuth, attempt_label
from app.api.lifecycle import CallLifecycle
from app.api.store import CallRecord, CallStore
from app.media.stream_server import CallRegistry
from app.scheduler import KST
from app.telephony.client import Telephony
from app.telephony.voiceml import connect_stream, say_and_hangup

logger = logging.getLogger(__name__)

# 상태 통보 본문을 이만큼보다 크게 받지 않는다. 바깥에 열린 주소다.
MAX_STATUS_BODY_BYTES = 8 * 1024
# 로그에 남기는 값 하나의 최대 길이.
_MAX_LOGGED_VALUE = 48
# 전화번호처럼 보이는 값. 로그에는 남기지 않는다.
_PHONE_LIKE = re.compile(r"^\+?[\d\- ]{8,}$")


def describe_status_payload(data: dict) -> str:
    """상태 통보의 필드 이름과 값을 로그용 한 줄로 만든다.

    **왜 내용을 남기나.** ClawOps 문서에 이 통보의 필드 이름과 상태 값이
    적혀 있지 않다. 안 받음을 '미응답'으로 세려면 어느 필드의 어느 값이
    안 받음인지 알아야 하는데, 추측으로 짜면 틀린 채로 조용히 통과한다.
    그래서 실제로 온 것을 먼저 본다.

    전화번호처럼 보이는 값은 가린다 — 어르신의 번호다. 값은 짧게 자르고
    줄바꿈은 지운다(바깥에 열린 주소라 로그를 어지럽힐 수 있다).
    """
    parts = []
    for key, value in data.items():
        text = str(value).replace("\n", " ").replace("\r", " ")
        if _PHONE_LIKE.match(text):
            text = "***"
        if len(text) > _MAX_LOGGED_VALUE:
            text = text[:_MAX_LOGGED_VALUE] + "…"
        parts.append(f"{str(key)[:32]}={text}")
    return ", ".join(parts)


DEFAULT_MANUAL_CALLS_PER_DAY = 3
# elders.elder_id는 BIGINT다. 이보다 큰 값은 DB가 오류를 낸다 — 서버 오류가 아니라
# 요청 오류(422)로 돌려보낸다.
MAX_ELDER_ID = 2**63 - 1


class CallRequest(BaseModel):
    elder_id: int = Field(ge=1, le=MAX_ELDER_ID)


def kst_day_start(now: float) -> float:
    """한국시간 기준 오늘 0시의 유닉스 시각. 수동 요청 횟수는 이 시각부터 센다."""
    local = datetime.fromtimestamp(now, KST)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def build_app(
    store: CallStore,
    telephony: Telephony,
    registry: CallRegistry,
    public_base_url: str,
    stream_base_url: str,
    lifecycle: CallLifecycle | None = None,
    guardian_auth: GuardianAuth | None = None,
    elders: ElderDirectory | None = None,
    manual_calls_per_day: int = DEFAULT_MANUAL_CALLS_PER_DAY,
    wall_clock: Callable[[], float] = time.time,
) -> FastAPI:
    # 조립 지점(app/main.py)은 스트림 소켓과 같은 lifecycle을 넘긴다. 통화의
    # 끝을 양쪽이 각자 처리하면 한쪽만 일어난다(lifecycle 모듈 설명 참고).
    lifecycle = lifecycle or CallLifecycle(store, registry)
    app = FastAPI(title="늘봄 통화 트리거")
    answer_url = answer_url_for(public_base_url)
    status_callback_url = status_callback_url_for(public_base_url)
    action_url = f"{public_base_url.rstrip('/')}/v1/stream-ended"
    stream_url = f"{stream_base_url.rstrip('/')}/v1/stream"

    if guardian_auth is not None:
        if elders is None:
            raise ValueError("guardian_auth를 쓰려면 elders(어르신 조회)도 있어야 한다")

        def _authorize(body: CallRequest, authorization: str | None) -> int:
            """다섯 개의 문 중 앞의 넷. 통과하면 보호자 번호를 돌려준다.

            순서가 곧 정보 노출의 경계다. 소유(③)를 동의(④)보다 먼저 보므로,
            남의 어르신이면 동의 여부를 알려 주기 전에 404로 끝난다.
            """
            guardian_id = guardian_auth.authenticate(authorization)
            if guardian_id is None:
                # 틀린 시도는 앞 12글자만 남긴다. 이유(없음/틀림/폐기)는 응답에 쓰지 않는다.
                logger.warning("열쇠 인증 실패 key=%s", attempt_label(authorization))
                raise HTTPException(status_code=401, detail="열쇠가 필요합니다")

            access = elders.get(body.elder_id)
            if access is None or access.guardian_id != guardian_id:
                raise HTTPException(status_code=404, detail="등록되지 않은 어르신입니다")
            if not access.consenting:
                raise HTTPException(status_code=403, detail="어르신의 동의가 없습니다")

            since = kst_day_start(wall_clock())
            if store.count_requested_since(body.elder_id, since) >= manual_calls_per_day:
                raise HTTPException(status_code=429, detail="오늘 요청 횟수를 넘었습니다")
            return guardian_id

        @app.post("/v1/calls/request")
        def request_call(
            body: CallRequest, authorization: str | None = Header(default=None)
        ) -> JSONResponse:
            try:
                guardian_id = _authorize(body, authorization)
            except HTTPException:
                raise
            except Exception as exc:
                # 저장소 장애는 "열쇠가 틀렸다"(401)도 "열려 있다"(202)도 아니다.
                logger.exception("인증 저장소 오류 — 요청을 거부한다")
                raise HTTPException(
                    status_code=503, detail="인증을 확인할 수 없습니다"
                ) from exc

            if store.find_elder(body.elder_id) is None:
                # 소유와 동의는 통과했지만 전화번호가 없다(명부와 DB가 어긋남).
                raise HTTPException(status_code=404, detail="등록되지 않은 어르신입니다")

            # find_active와 create를 store 안에서 락으로 묶어 한 번에 처리한다.
            # 따로 부르면 sync 라우트가 스레드풀에서 도는 동안 두 스레드가 모두
            # "활성 통화 없음"을 보고 둘 다 전화를 걸 수 있다.
            call, created = store.find_active_or_create(
                body.elder_id, trigger_type="requested", requested_by=guardian_id
            )
            if not created:
                # 두 번 누르는 것은 오류가 아니다. 전화가 안 오는 것 같아서
                # 다시 누른 것이므로, 그 통화의 대기 화면으로 보낸다.
                return JSONResponse(
                    status_code=409,
                    content={"call_id": call.call_id, "status": "in_progress"},
                )

            return _dial(call)

    def _dial(call: CallRecord) -> JSONResponse:
        # 실제 발신은 app/api/dialer.py에 있다. 스케줄러가 같은 경로를 쓴다.
        try:
            dial(
                call,
                store=store,
                telephony=telephony,
                lifecycle=lifecycle,
                answer_url=answer_url,
                status_callback_url=status_callback_url,
            )
        except DialFailed as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

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
        token = lifecycle.token_for(CallId)
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
        """스트림이 끝났다. 마무리 인사를 하고 끊는다.

        통화 상태를 여기서도 옮긴다. 우리 스트림이 한 번도 붙지 않은 통화
        (어르신이 받지 않았거나 VoiceML이 404로 끝난 경우)는 이 웹훅이
        끝을 알리는 유일한 신호이기 때문이다 — 스트림 쪽 종료 처리만 두면
        그런 통화는 영원히 '진행 중'으로 남아 그 어르신을 잠근다.
        스트림이 이미 끝내 놓은 통화라면 store가 멱등하게 무시한다.

        StreamEvent를 그냥 넘긴다. 이 필드를 로그에만 쓰고 버리던 동안은
        '스트림이 시작됐다' 같은 비종료 통보 하나가 통화를 끝내 버렸다 —
        어느 값이 끝인지는 lifecycle이 판정한다.
        """
        logger.info("스트림 종료 CallId=%s event=%s", CallId, StreamEvent)
        lifecycle.carrier_finished(CallId, StreamEvent)
        return Response(
            content=say_and_hangup("오늘도 좋은 하루 보내세요. 안녕히 계세요."),
            media_type="application/xml",
        )

    @app.post("/v1/call-status")
    async def call_status(request: Request) -> Response:
        """통화 상태가 바뀔 때 사업자가 부른다. **지금은 로그만 남긴다.**

        어르신이 받지 않으면 VoiceML도 종료 웹훅도 오지 않아서, 이 통보가
        안 받음을 아는 유일한 길이다. 다만 필드 이름과 값을 문서에서 확인하지
        못해 상태는 바꾸지 않고 실제로 온 것을 먼저 기록한다. 모양을 본 뒤에
        안 받음 처리를 붙인다.

        바깥에 열린 주소이므로 본문 크기를 제한하고, 어떤 모양이 와도(폼,
        JSON, 빈 본문) 오류로 돌려보내지 않는다 — 사업자가 실패로 보고 재전송
        하면 같은 통보가 반복된다.
        """
        body = await request.body()
        if len(body) > MAX_STATUS_BODY_BYTES:
            logger.warning("상태 통보가 너무 커서 버린다 bytes=%d", len(body))
            return Response(status_code=204)

        content_type = request.headers.get("content-type", "")
        data: dict = {}
        try:
            if "json" in content_type:
                import json

                parsed = json.loads(body or b"{}")
                data = parsed if isinstance(parsed, dict) else {"body": parsed}
            else:
                from urllib.parse import parse_qsl

                data = dict(parse_qsl(body.decode("utf-8", "replace")))
        except Exception:
            logger.warning("상태 통보를 읽지 못했다 content-type=%s bytes=%d", content_type, len(body))
            return Response(status_code=204)

        logger.info(
            "통화 상태 통보 content-type=%s 필드: %s",
            content_type.split(";")[0] or "-",
            describe_status_payload(data),
        )
        return Response(status_code=204)

    return app
