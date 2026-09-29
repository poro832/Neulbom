"""실제로 전화를 거는 한 자리.

트리거 API와 스케줄러가 **같은 경로**로 나가야 해서 꺼내 두었다. 발신
뒤처리가 까다로운데(아래), 두 곳에서 각자 구현하면 언젠가 한쪽만 고쳐진다.

**어려운 부분은 "전화는 걸렸는데 그 다음이 실패한" 경우다.** Telephony에는
취소나 끊기 수단이 없어서 그 통화를 멈출 수 없다. 이때 통화를 '진행 중'으로
두면 그 어르신은 **다시는 요청할 수 없게 되고 그건 복구가 안 된다.** 실패로
돌려 재시도를 열어주면 최악이 전화가 한 번 더 울리는 정도다 — 복구 가능한
쪽을 택한다.
"""

from __future__ import annotations

import logging

from app.api.lifecycle import CallLifecycle
from app.api.store import CallRecord, CallStore
from app.telephony.client import Telephony

logger = logging.getLogger(__name__)


class DialFailed(Exception):
    """발신에 실패했다. 통화는 실패로 표시됐고 재시도가 열려 있다."""


def answer_url_for(public_base_url: str) -> str:
    """사업자가 통화 응답 때 부를 주소. 트리거 API와 스케줄러가 같은 값을 쓴다."""
    return f"{public_base_url.rstrip('/')}/v1/voiceml"


def dial(
    call: CallRecord,
    *,
    store: CallStore,
    telephony: Telephony,
    lifecycle: CallLifecycle,
    answer_url: str,
) -> None:
    """이미 만들어진 통화에 실제로 전화를 건다."""
    phone = store.find_elder(call.elder_id)
    try:
        sid = telephony.place_call(to=phone, answer_url=answer_url)
    except Exception as exc:
        # 발신 자체가 실패했다 — 실제 통화는 나가지 않았다. 안전하게
        # 실패 처리해 재시도를 열어준다.
        store.mark_failed(call.call_id)
        logger.exception("발신 실패 call_id=%s", call.call_id)
        raise DialFailed("전화를 걸지 못했습니다") from exc

    try:
        store.attach_sid(call.call_id, sid)
        lifecycle.issue_token(call.call_id, sid)
    except Exception as exc:
        # 여기서부터는 전화가 이미 걸렸다(모듈 설명 참고). 토큰이 없으면
        # 그 통화는 VoiceML에서 404로 끝나 어차피 오디오가 붙지 않는다.
        lifecycle.discard_token(sid)
        store.mark_failed(call.call_id)
        logger.exception(
            "발신 후 처리 실패 call_id=%s sid=%s — 통화가 걸렸어도 연결되지 않는다",
            call.call_id,
            sid,
        )
        raise DialFailed("통화 연결 준비에 실패했습니다") from exc


def place_scheduled_call(
    elder_id: int,
    *,
    store: CallStore,
    telephony: Telephony,
    lifecycle: CallLifecycle,
    answer_url: str,
) -> None:
    """스케줄러가 부르는 자리. 예약 통화를 만들고 건다.

    이미 진행 중인 통화가 있으면 **조용히 넘어간다.** 어르신이 방금 앱에서
    전화를 요청했는데 스케줄러가 한 통 더 거는 일을 막는다 — 어르신 쪽에서
    보면 전화가 두 번 오는 것이고, 그건 버그가 아니라 실제 불편이다.
    """
    call, created = store.find_active_or_create(elder_id, trigger_type="scheduled")
    if not created:
        logger.info(
            "진행 중인 통화가 있어 예약 발신을 건너뛴다 elder_id=%s call_id=%s",
            elder_id,
            call.call_id,
        )
        return
    dial(
        call,
        store=store,
        telephony=telephony,
        lifecycle=lifecycle,
        answer_url=answer_url,
    )
