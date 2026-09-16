"""발신 요청 (전화망 설계 4.2).

Responder와 같은 패턴이다. 규약으로 분리해 두면 ClawOps 계정 신청이
끝나기 전에 트리거 API 전체를 FakeTelephony로 완성할 수 있다.
"""

from __future__ import annotations

import itertools
from typing import Protocol

import httpx

CLAWOPS_BASE_URL = "https://api.claw-ops.com"


class Telephony(Protocol):
    def place_call(self, *, to: str, answer_url: str) -> str:
        """발신을 요청하고 사업자 측 통화 식별자를 돌려준다.

        실패하면 예외를 던진다. 미응답은 실패가 아니다 — 그건 통화가
        시작된 뒤에 웹훅으로 알려진다.
        """
        ...


class FakeTelephony:
    """테스트용. 실제로 걸지 않고 무엇을 요청받았는지만 기록한다."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.placed: list[tuple[str, str]] = []
        self._fail_with = fail_with
        self._counter = itertools.count(1)

    def place_call(self, *, to: str, answer_url: str) -> str:
        if self._fail_with is not None:
            raise self._fail_with
        self.placed.append((to, answer_url))
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

    def place_call(self, *, to: str, answer_url: str) -> str:
        response = httpx.post(
            f"{self._base_url}/v1/accounts/{self._account_sid}/calls",
            headers={"Authorization": f"Bearer {self._api_key}"},
            data={"To": to, "From": self._from_number, "Url": answer_url},
            timeout=self._timeout,
        )
        response.raise_for_status()

        # 엔드포인트 경로·인증 헤더·응답 필드명(call_id) 셋 다 계정 없이 작성한
        # 추측이다. 실제 API와 어긋나면 바로 여기서 처음 드러난다 — 그 순간
        # 팀원이 가진 단서는 이 예외 메시지뿐이므로 상태 코드와 본문을 남긴다.
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "ClawOps 응답이 JSON이 아니다: "
                f"status={response.status_code} body={_truncate(response.text)}"
            ) from exc

        try:
            return payload["call_id"]
        except KeyError as exc:
            raise RuntimeError(
                "ClawOps 응답에 call_id 필드가 없다: "
                f"status={response.status_code} body={_truncate(response.text)}"
            ) from exc


def _truncate(body: str, limit: int = 300) -> str:
    """거대한 HTML 에러 페이지가 로그를 뒤덮지 않도록 자른다."""
    return body if len(body) <= limit else body[:limit] + "…"
