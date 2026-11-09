"""채팅에서 위급한 말이 잡혔을 때 보호자 전원에게 알림을 남기고 푸시를 보낸다."""

from __future__ import annotations

import logging

from app.chat.urgent import GUARDIAN_ALERT_MESSAGE

logger = logging.getLogger(__name__)

# 기존 알림 표가 이미 받는 종류다(표를 바꾸지 않는다). 앱에서는 '위급 표현'으로 보인다.
ALERT_TYPE = "emergency_keyword"


def make_urgent_alerter(*, elders, alerts, notifier):
    def alert(elder_id: int, category: str) -> None:  # category는 알림에 싣지 않는다 — 어르신의 말을 알리지 않는다
        access = elders.get(elder_id)
        if access is None:
            return
        notify = getattr(notifier, "notify_chat_urgent", None)
        for guardian_id in access.guardian_ids:
            try:
                alerts.raise_alert(
                    elder_id=elder_id,
                    guardian_id=guardian_id,
                    call_id=None,
                    alert_type=ALERT_TYPE,
                    severity="critical",
                    message=GUARDIAN_ALERT_MESSAGE,
                )
                if notify is not None:
                    notify(guardian_id, elder_id)
            except Exception:
                # 한 보호자의 실패가 나머지 보호자의 알림을 막지 않는다.
                logger.exception("보호자 위급 알림 실패 guardian_id=%s", guardian_id)

    return alert
