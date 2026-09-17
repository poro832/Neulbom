"""통화 하나의 시작과 끝을 한 곳에 모은다 (전화망 설계 5장, 8장).

끝을 처리하는 일은 두 가지다: 기록을 종료 상태로 옮기는 것과, 그 통화의
1회용 스트림 토큰을 폐기하는 것. 둘을 각자 하면 한쪽만 일어난다.

- 상태만 옮기고 토큰을 두면, 끝난 통화의 토큰이 인증 없는 /v1/voiceml에서
  영원히 꺼내지고 그 토큰으로 아무나 스트림에 붙을 수 있다.
- 토큰만 지우고 상태를 두면, 그 어르신은 영원히 409를 받아 다시는 전화를
  요청할 수 없다 — 그런데 앱은 409를 성공으로 보여 준다.

끝을 알리는 신호는 세 개다 — 우리 소켓의 종료, 사업자 웹훅, 그리고 둘 다
유실됐을 때 저장소의 바닥 시간. 셋 다 유실되거나 늦을 수 있고 순서도
보장되지 않아서, 여기의 모든 종료 처리는 멱등이다(실제 전이 판정은 store가
한다). 셋 모두 이 파일을 지나야 한다 — 한 경로라도 store를 직접 고치면
그 통화의 토큰만 살아남는다.
"""

from __future__ import annotations

import logging
import secrets
import threading

from app.api.store import CallRecord, CallStore
from app.media.stream_server import CallRegistry

logger = logging.getLogger(__name__)

# 사업자가 action URL로 보내는 StreamEvent 중 '아직 안 끝났다'는 뜻인 값들.
#
# 이 필드는 지금까지 받아서 로그만 찍고 버렸다. 그래서 스트림이 시작됐다는
# 통보 하나가 통화를 통째로 끝내 버렸다 — 어르신은 이제 막 받았는데 기록은
# 끝난다. 여기 없는 값은 여전히 종료로 본다(빈 문자열 포함): 사업자가
# 우리가 모르는 종료 이름을 쓰더라도 통화는 끝나야 하고, 그러지 않으면
# 미응답 통화가 바닥 시간까지 20분간 어르신을 잠근다. 이 목록에 없는
# 비종료 이벤트가 새로 생기면 그때 여기에 더한다.
NON_TERMINAL_STREAM_EVENTS = frozenset(
    {"start", "started", "stream-started", "connected", "media", "mark"}
)


class CallLifecycle:
    def __init__(self, store: CallStore, registry: CallRegistry) -> None:
        self._store = store
        self._registry = registry
        # 사업자 CallId → 그 통화의 1회용 토큰. VoiceML을 만들 때 심는다.
        self._tokens: dict[str, str] = {}
        self._lock = threading.Lock()
        # 바닥 시간이 통화를 접는 일은 저장소 안에서 혼자 일어난다. 여기서
        # 손을 들어 두지 않으면 그 통화의 토큰을 폐기할 사람이 없다.
        self._store.add_expiry_listener(self._expired)

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

    def stream_started(self, call_id: int) -> None:
        """우리 소켓에 스트림이 붙었다 — 어르신이 받았다는 우리 쪽 증거다.

        이 기록이 없으면 종료 처리가 "여기까지 활성이면 오디오가 안 붙었다"고
        추론하는 수밖에 없고, 그 추론은 사업자 웹훅이 통화 중에 도착하는
        순간 틀린다 — 녹음까지 남긴 통화가 no_answer로 기록된다.
        """
        self._store.mark_answered(call_id)

    def stream_finished(self, call_id: int, audio_key: str | None) -> None:
        """우리 스트림이 닫혔다 — 이 통화의 끝을 우리가 직접 본 유일한 순간이다.

        사업자 웹훅(action URL)은 오지 않을 수도, 늦을 수도 있다. 여기서
        옮기지 않으면 정상적으로 끝난 통화가 'ringing'으로 굳는다.

        녹음이 없으면 completed가 아니다. 스키마가 'completed면 audio_key가
        있어야 한다'를 제약으로 걸어 둔 것과 같은 이유로, 분석할 오디오가
        없는 통화를 정상 종료로 세면 후속 파이프라인이 조용히 멈춘다.
        """
        try:
            if audio_key is None:
                logger.error(
                    "녹음 없이 스트림이 끝났다 — 실패로 남긴다 call_id=%s", call_id
                )
                self._store.mark_failed(call_id)
            else:
                self._store.mark_completed(call_id, audio_key)
        finally:
            # 상태 전이가 터져도 토큰은 반드시 닫는다. 이 둘 중 하나만
            # 일어나는 것이 이 모듈이 막으려고 존재하는 바로 그 일이고,
            # 상태를 못 옮긴 통화의 토큰이 남는 쪽이 더 나쁘다 — 그 토큰은
            # 인증 없는 /v1/voiceml에서 계속 꺼내진다.
            self._revoke_for_call(call_id)

    def carrier_finished(self, sid: str, event: str = "") -> None:
        """사업자가 스트림 종료를 알려 왔다.

        스트림이 우리 쪽에 한 번도 붙지 않은 통화(어르신이 받지 않았거나
        VoiceML이 404로 끝난 경우)는 이 신호가 유일한 끝이다. 이미 스트림이
        끝내 놓은 통화라면 store가 멱등하게 무시한다.
        """
        if event in NON_TERMINAL_STREAM_EVENTS:
            # 끝이 아니라 진행 상황 통보다. 이걸 끝으로 세면 방금 시작한
            # 통화가 끝난 것으로 기록된다(위 상수 설명).
            logger.info("종료가 아닌 스트림 이벤트 CallId=%s event=%s", sid, event)
            return

        call = self._store.find_by_sid(sid)
        if call is None:
            logger.warning("모르는 CallId의 스트림 종료 CallId=%s", sid)
            return

        if call.status == "answered":
            # 우리 소켓에 스트림이 붙었던 통화다. 사업자 웹훅과 우리 소켓
            # 종료는 서로 다른 경로여서, <Connect action>의 POST는 우리가
            # 소켓을 닫는 바로 그 순간에 온다 — 통화 중에 먼저 도착한다.
            # 여기서 no_answer로 적으면 받아서 대화하고 녹음까지 남은 통화가
            # '전화를 받지 않음'이 되고, 그 값은 위험 점수의 입력이다(미응답
            # 이력 20점). 게다가 녹음이 있는 통화에 audio_key가 없게 되어
            # 스키마 규칙과도 어긋난다.
            #
            # 그래서 결론은 스트림 쪽에 맡긴다. 그쪽은 녹음이 있었는지를
            # 실제로 알고 completed/failed를 정확히 가른다. 소켓이 끝내
            # 닫히지 않으면 바닥 시간이 failed로 접는다 — 'no_answer'라고
            # 지어내는 것보다 '모른다'가 낫다.
            logger.info(
                "스트림이 붙었던 통화의 사업자 종료 웹훅 — 결과는 스트림이 정한다"
                " call_id=%s event=%s",
                call.call_id,
                event,
            )
            self._revoke(sid)
            return

        # 여기까지 'answered'가 아니라는 것은 오디오가 한 번도 붙지 않았다는
        # 뜻이다 — 실패가 아니라 미응답이다. 지표는 이 둘을 다르게 센다.
        self._store.mark_no_answer(call.call_id)
        self._revoke(sid)

    def _expired(self, call: CallRecord) -> None:
        """바닥 시간이 통화를 접었다 — 토큰도 같이 접는다.

        이 경로는 끝 신호가 둘 다 유실된 통화다. 다른 폐기 지점이 하나도
        불리지 않았으므로 여기가 그 토큰의 마지막 기회다.
        """
        if call.provider_call_sid is not None:
            self._revoke(call.provider_call_sid)

    def _revoke_for_call(self, call_id: int) -> None:
        try:
            sid = self._store.get(call_id).provider_call_sid
        except KeyError:
            # 모르는 call_id다. 여기서 터지면 호출부의 나머지 마무리까지
            # 같이 죽는다 — 알 수 없는 것 하나 때문에 아는 일을 못 하게
            # 두지 않는다.
            logger.error("모르는 통화의 토큰을 폐기하려 했다 call_id=%s", call_id)
            return
        if sid is not None:
            self._revoke(sid)

    def _revoke(self, sid: str) -> None:
        with self._lock:
            token = self._tokens.pop(sid, None)
        if token is not None:
            self._registry.revoke(token)
