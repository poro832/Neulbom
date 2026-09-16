"""통화 하나의 시작과 끝을 한 곳에 모은다 (전화망 설계 5장, 8장).

끝을 처리하는 일은 두 가지다: 기록을 종료 상태로 옮기는 것과, 그 통화의
1회용 스트림 토큰을 폐기하는 것. 둘을 각자 하면 한쪽만 일어난다.

- 상태만 옮기고 토큰을 두면, 끝난 통화의 토큰이 인증 없는 /v1/voiceml에서
  영원히 꺼내지고 그 토큰으로 아무나 스트림에 붙을 수 있다.
- 토큰만 지우고 상태를 두면, 그 어르신은 영원히 409를 받아 다시는 전화를
  요청할 수 없다 — 그런데 앱은 409를 성공으로 보여 준다.

끝을 알리는 신호는 두 개이고 둘 다 유실될 수 있어 순서도 보장되지 않는다.
그래서 여기의 모든 종료 처리는 멱등이다(실제 전이 판정은 store가 한다).
"""

from __future__ import annotations

import logging
import secrets
import threading

from app.api.store import CallStore
from app.media.stream_server import CallRegistry

logger = logging.getLogger(__name__)


class CallLifecycle:
    def __init__(self, store: CallStore, registry: CallRegistry) -> None:
        self._store = store
        self._registry = registry
        # 사업자 CallId → 그 통화의 1회용 토큰. VoiceML을 만들 때 심는다.
        self._tokens: dict[str, str] = {}
        self._lock = threading.Lock()

    def issue_token(self, call_id: int, sid: str) -> str:
        """이 통화에 쓸 1회용 스트림 토큰을 만들어 레지스트리에 등록한다."""
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._tokens[sid] = token
        self._registry.issue(token, str(call_id))
        return token

    def token_for(self, sid: str) -> str | None:
        """pop이 아니라 조회다 — 사업자 웹훅은 같은 CallId로 재전송된다."""
        with self._lock:
            return self._tokens.get(sid)

    def discard_token(self, sid: str) -> None:
        """발신 후처리가 실패했을 때처럼, 통화가 시작되기도 전에 접는다."""
        self._revoke(sid)

    def stream_finished(self, call_id: int, audio_key: str | None) -> None:
        """우리 스트림이 닫혔다 — 이 통화의 끝을 우리가 직접 본 유일한 순간이다.

        사업자 웹훅(action URL)은 오지 않을 수도, 늦을 수도 있다. 여기서
        옮기지 않으면 정상적으로 끝난 통화가 'ringing'으로 굳는다.

        녹음이 없으면 completed가 아니다. 스키마가 'completed면 audio_key가
        있어야 한다'를 제약으로 걸어 둔 것과 같은 이유로, 분석할 오디오가
        없는 통화를 정상 종료로 세면 후속 파이프라인이 조용히 멈춘다.
        """
        if audio_key is None:
            logger.error(
                "녹음 없이 스트림이 끝났다 — 실패로 남긴다 call_id=%s", call_id
            )
            self._store.mark_failed(call_id)
        else:
            self._store.mark_completed(call_id, audio_key)
        self._revoke_for_call(call_id)

    def carrier_finished(self, sid: str) -> None:
        """사업자가 스트림 종료를 알려 왔다.

        스트림이 우리 쪽에 한 번도 붙지 않은 통화(어르신이 받지 않았거나
        VoiceML이 404로 끝난 경우)는 이 신호가 유일한 끝이다. 이미 스트림이
        끝내 놓은 통화라면 store가 멱등하게 무시한다.
        """
        call = self._store.find_by_sid(sid)
        if call is None:
            logger.warning("모르는 CallId의 스트림 종료 CallId=%s", sid)
            return
        # 여기까지 활성으로 남아 있다는 것은 오디오가 한 번도 붙지 않았다는
        # 뜻이다 — 실패가 아니라 미응답이다. 지표는 이 둘을 다르게 센다.
        self._store.mark_no_answer(call.call_id)
        self._revoke(sid)

    def _revoke_for_call(self, call_id: int) -> None:
        sid = self._store.get(call_id).provider_call_sid
        if sid is not None:
            self._revoke(sid)

    def _revoke(self, sid: str) -> None:
        with self._lock:
            token = self._tokens.pop(sid, None)
        if token is not None:
            self._registry.revoke(token)
