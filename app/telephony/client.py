"""발신 요청 (전화망 설계 4.2).

Responder와 같은 패턴이다. 규약으로 분리해 두면 ClawOps 계정 신청이
끝나기 전에 트리거 API 전체를 FakeTelephony로 완성할 수 있다.
"""

from __future__ import annotations

import itertools
from typing import Protocol

import httpx

CLAWOPS_BASE_URL = "https://api.claw-ops.com"

# 상태 통보를 받을 이벤트(공백으로 구분). 공식 문서의 기본값과 같다.
STATUS_CALLBACK_EVENTS = "initiated ringing answered completed"


class Telephony(Protocol):
    def place_call(
        self, *, to: str, answer_url: str, status_callback_url: str | None = None
    ) -> str:
        """발신을 요청하고 사업자 측 통화 식별자를 돌려준다.

        실패하면 예외를 던진다. 미응답은 실패가 아니다 — 그건 통화가
        시작된 뒤에 웹훅으로 알려진다.

        status_callback_url은 통화 상태가 바뀔 때마다 사업자가 부르는 주소다.
        **안 받음을 아는 유일한 길이다** — 어르신이 받지 않으면 answer_url
        (VoiceML)은 한 번도 불리지 않고, 그 안에 든 종료 웹훅도 오지 않는다.
        """
        ...


class FakeTelephony:
    """테스트용. 실제로 걸지 않고 무엇을 요청받았는지만 기록한다."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.placed: list[tuple[str, str]] = []
        # placed의 모양을 바꾸지 않으려고 따로 둔다(기존 테스트가 튜플을 비교한다).
        self.status_callbacks: list[str | None] = []
        self._fail_with = fail_with
        self._counter = itertools.count(1)

    def place_call(
        self, *, to: str, answer_url: str, status_callback_url: str | None = None
    ) -> str:
        if self._fail_with is not None:
            raise self._fail_with
        self.placed.append((to, answer_url))
        self.status_callbacks.append(status_callback_url)
        return f"CA{next(self._counter):08d}"


class ClawOpsTelephony:
    """실제 발신. 발신번호는 계정이 보유한 070이어야 거절되지 않는다."""

    def __init__(
        self,
        account_sid: str,
        api_key: str,
        from_number: str,
        base_url: str = CLAWOPS_BASE_URL,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._account_sid = account_sid
        self._api_key = api_key
        self._from_number = from_number
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def place_call(
        self, *, to: str, answer_url: str, status_callback_url: str | None = None
    ) -> str:
        # ClawOps는 번호를 숫자만으로 저장하고 응답한다(07052767846).
        # 하이픈을 그대로 보내도 되는지 문서에 없어서, 보내는 쪽에서 맞춘다.
        data = {
            "To": _digits(to),
            "From": _digits(self._from_number),
            "Url": answer_url,
        }
        if status_callback_url:
            data["StatusCallback"] = status_callback_url
            # 문서의 기본값과 같지만 **명시한다** — 기본값이 바뀌는 날 안 받음
            # 통보가 조용히 끊기면 미응답 이력(20점)이 다시 죽는다.
            data["StatusCallbackEvent"] = STATUS_CALLBACK_EVENTS

        response = httpx.post(
            f"{self._base_url}/v1/accounts/{self._account_sid}/calls",
            headers={"Authorization": f"Bearer {self._api_key}"},
            data=data,
            timeout=self._timeout,
        )
        if response.is_error:
            # raise_for_status만 쓰면 "400 Bad Request"만 남아 원인(발신번호 회수,
            # 계정 문제 등)을 사업자 콘솔까지 가서 찾아야 한다(2026-10-09).
            raise RuntimeError(
                "ClawOps가 발신을 거절했다: "
                f"status={response.status_code} body={_truncate(response.text)}"
            )

        # 경로·인증 헤더는 공식 문서(2026-10-06)와 맞는다. 응답 필드는 처음에
        # call_id로 추측했는데 실제는 callId였다 — 전화는 이미 나간 뒤에 이
        # 줄에서 터졌을 것이다. 어긋나면 여기서 드러나므로 상태 코드와 본문을
        # 남긴다.
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "ClawOps 응답이 JSON이 아니다: "
                f"status={response.status_code} body={_truncate(response.text)}"
            ) from exc

        try:
            return payload["callId"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                "ClawOps 응답에 callId 필드가 없다: "
                f"status={response.status_code} body={_truncate(response.text)}"
            ) from exc


def _digits(number: str) -> str:
    return "".join(ch for ch in number if ch.isdigit())


def _truncate(body: str, limit: int = 300) -> str:
    """거대한 HTML 에러 페이지가 로그를 뒤덮지 않도록 자른다."""
    return body if len(body) <= limit else body[:limit] + "…"
