"""알림을 만들지 말지 정하는 규칙 (설계: 앱 화면을 실제 데이터로).

여기는 통화 종료 경로(위험 판정 sink, 안 받음 웹훅)에서 불린다. **어떤 예외도 밖으로
내보내지 않는다** — 알림 하나 못 만들었다고 점수 저장이나 통화 종료가 막히면 어르신이
'통화 중'으로 잠긴다.
"""

from __future__ import annotations

import logging

from app.api.alerts import NO_ANSWER_MESSAGE, RISK_MESSAGES, AlertStore
from app.api.elder_directory import ElderDirectory
from app.api.store import CallRecord

logger = logging.getLogger(__name__)

_RISK_SEVERITY = {"watch": "warning", "alert": "critical"}


class AlertRules:
    def __init__(self, *, alerts: AlertStore, elders: ElderDirectory) -> None:
        self._alerts = alerts
        self._elders = elders

    def on_risk(self, *, call_id: int, elder_id: int, risk_level: str) -> None:
        severity = _RISK_SEVERITY.get(risk_level)
        if severity is None:
            return
        self._raise(
            call_id=call_id,
            elder_id=elder_id,
            alert_type="risk_rise",
            severity=severity,
            message=RISK_MESSAGES[risk_level],
        )

    def on_no_answer(self, call: CallRecord) -> None:
        # 수동 요청의 미응답은 알림이 아니다 — 버튼을 누르고 전화기를 못 찾은 것일 뿐이다.
        if call.trigger_type != "scheduled":
            return
        self._raise(
            call_id=call.call_id,
            elder_id=call.elder_id,
            alert_type="no_answer",
            severity="info",
            message=NO_ANSWER_MESSAGE,
        )

    def _raise(
        self, *, call_id: int, elder_id: int, alert_type: str, severity: str, message: str
    ) -> None:
        try:
            access = self._elders.get(elder_id)
            if access is None:
                logger.warning("알림을 받을 보호자를 모른다 — 버린다 elder_id=%s", elder_id)
                return
            created = self._alerts.raise_alert(
                elder_id=elder_id,
                guardian_id=access.guardian_id,
                call_id=call_id,
                alert_type=alert_type,
                severity=severity,
                message=message,
            )
            if created:
                logger.info(
                    "알림을 남겼다 call_id=%s elder_id=%s type=%s severity=%s",
                    call_id,
                    elder_id,
                    alert_type,
                    severity,
                )
        except Exception:
            logger.exception("알림 생성 실패 call_id=%s elder_id=%s", call_id, elder_id)
