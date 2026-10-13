"""FCM 푸시 발송기 (설계: 푸시 알림).

전송 계층(HTTP)과 OAuth 토큰 발급을 주입받으므로 서비스 계정 열쇠 없이도 규약 전체가
테스트로 검증된다. **어떤 실패도 예외로 밖에 내지 않는다** — 결과만 돌려준다.
서비스 계정 열쇠(JSON)는 코드·로그에 남기지 않는다. 환경 변수 FCM_SERVICE_ACCOUNT_FILE의
경로만 읽는다.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable, Mapping
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

SENT = "sent"
INVALID_TOKEN = "invalid_token"
FAILED = "failed"

SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


class PushSender(Protocol):
    def send(self, token: str, title: str, body: str, data: dict[str, str]) -> str:
        """SENT | INVALID_TOKEN | FAILED. 예외를 내지 않는다."""
        ...


def _http_post(url: str, *, headers: dict, payload: dict, timeout: float) -> tuple[int, bytes]:
    response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    return response.status_code, response.content


def _is_bad_token(status: int, body: bytes) -> bool:
    """토큰이 더 이상 없거나 잘못됐다는 답인가. 그 밖의 400(페이로드 문제 등)은 아니다."""
    if status == 404:
        return True
    if status == 400:
        text = body.decode("utf-8", "replace")
        return "message.token" in text or "registration token" in text.lower()
    return False


class FcmSender:
    def __init__(
        self,
        project_id: str,
        token_provider: Callable[[], str],
        *,
        transport: Callable[..., tuple[int, bytes]] = _http_post,
        timeout: float = 10.0,
    ) -> None:
        self._url = SEND_URL.format(project_id=project_id)
        self._token_provider = token_provider
        self._transport = transport
        self._timeout = timeout

    def send(self, token: str, title: str, body: str, data: dict[str, str]) -> str:
        try:
            access_token = self._token_provider()
            status, response_body = self._transport(
                self._url,
                headers={"Authorization": f"Bearer {access_token}"},
                payload={
                    "message": {
                        "token": token,
                        "notification": {"title": title, "body": body},
                        "data": {k: str(v) for k, v in data.items()},
                        "android": {"priority": "HIGH"},
                    }
                },
                timeout=self._timeout,
            )
        except Exception:
            # 토큰·본문은 남기지 않는다. 오류 종류만.
            logger.exception("푸시 발송 중 오류 token=%s", token[:8])
            return FAILED
        if 200 <= status < 300:
            return SENT
        if _is_bad_token(status, response_body):
            return INVALID_TOKEN
        logger.warning("푸시 발송 실패 status=%s token=%s", status, token[:8])
        return FAILED


class _HttpxRequest:
    """google-auth가 토큰을 새로 받을 때 쓰는 전송 계층을 httpx로 채운다(requests를 끌어오지 않으려고)."""

    def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kwargs):
        import google.auth.transport

        class _Response(google.auth.transport.Response):
            def __init__(self, r: httpx.Response) -> None:
                self._r = r

            @property
            def status(self):
                return self._r.status_code

            @property
            def headers(self):
                return self._r.headers

            @property
            def data(self):
                return self._r.content

        r = httpx.request(method, url, content=body, headers=headers, timeout=timeout or 10.0)
        return _Response(r)


def service_account_token_provider(path: str) -> tuple[str, Callable[[], str]]:
    """(프로젝트 ID, 토큰을 돌려주는 함수). 파일을 읽지 못하면 예외."""
    import threading

    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(path, scopes=[SCOPE])
    request = _HttpxRequest()
    lock = threading.Lock()

    def provider() -> str:
        with lock:
            if not credentials.valid:
                credentials.refresh(request)
            return credentials.token

    return credentials.project_id, provider


def sender_from_env(env: Mapping[str, str] = os.environ) -> PushSender | None:
    """서비스 계정 열쇠 파일이 있으면 발송기를, 없거나 못 읽으면 None(푸시 꺼짐). 서버는 계속 뜬다."""
    path = env.get("FCM_SERVICE_ACCOUNT_FILE", "").strip()
    if not path:
        return None
    try:
        project_id, provider = service_account_token_provider(path)
    except Exception:
        # 파일 내용은 로그에 남기지 않는다.
        logger.exception("서비스 계정 열쇠를 읽지 못했다 — 푸시를 끈다")
        return None
    return FcmSender(project_id, provider)


TITLE = "늘봄"


def _spawn_thread(job: Callable[[], None]) -> None:
    threading.Thread(target=job, name="push-notify", daemon=True).start()


class PushNotifier:
    """알림이 새로 저장되면 그 어르신의 보호자 폰들에 푸시를 보낸다. 어떤 예외도 밖으로 내지 않는다."""

    def __init__(
        self,
        *,
        devices,
        elders,
        sender: PushSender | None,
        spawn: Callable[[Callable[[], None]], None] = _spawn_thread,
    ) -> None:
        self._devices = devices
        self._elders = elders
        self._sender = sender
        self._spawn = spawn

    def notify(self, guardian_id: int, elder_id: int) -> None:
        if self._sender is None:
            return
        try:
            self._spawn(lambda: self._send_all(guardian_id, elder_id))
        except Exception:
            logger.exception("푸시 작업을 시작하지 못했다 guardian_id=%s", guardian_id)

    def _send_all(self, guardian_id: int, elder_id: int) -> None:
        try:
            access = self._elders.get(elder_id)
            name = (access.name or "").strip() if access is not None else ""
            body = f"{name} 어르신 확인이 필요해요" if name else "어르신 확인이 필요해요"
            tokens = self._devices.tokens_for(guardian_id)
        except Exception:
            logger.exception("푸시 대상을 읽지 못했다 guardian_id=%s", guardian_id)
            return
        for token in tokens:
            try:
                result = self._sender.send(token, TITLE, body, {"elder_id": str(elder_id)})
            except Exception:
                logger.exception("푸시 발송 오류 guardian_id=%s token=%s", guardian_id, token[:8])
                continue
            if result == INVALID_TOKEN:
                try:
                    self._devices.remove_token(token)
                except Exception:
                    logger.exception("무효 토큰을 지우지 못했다 token=%s", token[:8])
            logger.info(
                "푸시 결과 guardian_id=%s elder_id=%s token=%s 결과=%s",
                guardian_id,
                elder_id,
                token[:8],
                result,
            )
