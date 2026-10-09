"""앱 화면용 주소 모음 — 어르신 연결, 보호자 조회, 어르신 조회·연락처 (설계: 앱 화면을 실제 데이터로).

기존 `/v1/calls/request`와 같은 원칙이다: 열쇠가 없거나 틀리면 401(이유는 말하지 않는다),
남의 어르신이면 없는 어르신과 같은 404, 저장소가 고장 나면 503(열린 채로 두지 않는다).
`AppData`를 주지 않으면 이 주소들은 아예 등록되지 않는다.
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from fastapi import FastAPI, Header, HTTPException, Path, Query, Response
from pydantic import BaseModel, Field

from app.api.alerts import AlertStore
from app.api.calls import MAX_ELDER_ID
from app.api.contacts import ContactStore, TooManyContacts
from app.api.elder_auth import ElderAuth, ElderKeyStore, elder_key_label, generate_elder_key
from app.api.elder_directory import ElderDirectory, digits_of
from app.api.guardian_auth import GuardianAuth, attempt_label
from app.api.pairing import PairingStore, hash_code, new_code
from app.api.reports import Reports, kst_week_start, sunday_on_or_before
from app.scheduler import KST

logger = logging.getLogger(__name__)

NEED_KEY = "열쇠가 필요합니다"
NO_ELDER = "등록되지 않은 어르신입니다"
BAD_PAIR = "연결 코드를 확인해 주세요"
UNAVAILABLE = "인증을 확인할 수 없습니다"


@dataclass
class AppData:
    guardian_auth: GuardianAuth
    elder_auth: ElderAuth
    elders: ElderDirectory
    pairings: PairingStore
    elder_keys: ElderKeyStore
    contacts: ContactStore
    reports: Reports
    alerts: AlertStore
    wall_clock: Callable[[], float] = time.time


def iso_kst(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, KST).isoformat(timespec="seconds")


class PairRequest(BaseModel):
    code: str = Field(pattern=r"^[0-9]{6}$")
    phone: str = Field(min_length=7, max_length=20)


def add_app_routes(app: FastAPI, data: AppData) -> None:
    def guarded(fn):
        """저장소 오류는 401도 200도 아니다 — 503으로 닫는다."""

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as exc:
                logger.exception("앱 데이터 저장소 오류 — 요청을 거부한다 route=%s", fn.__name__)
                raise HTTPException(status_code=503, detail=UNAVAILABLE) from exc

        return wrapper

    def guardian_id_of(authorization: str | None) -> int:
        guardian_id = data.guardian_auth.authenticate(authorization)
        if guardian_id is None:
            logger.warning("열쇠 인증 실패 key=%s", attempt_label(authorization))
            raise HTTPException(status_code=401, detail=NEED_KEY)
        return guardian_id

    def elder_id_of(authorization: str | None) -> int:
        elder_id = data.elder_auth.authenticate(authorization)
        if elder_id is None:
            logger.warning("어르신 열쇠 인증 실패 key=%s", elder_key_label(authorization))
            raise HTTPException(status_code=401, detail=NEED_KEY)
        return elder_id

    def owned_elder(guardian_id: int, elder_id: int):
        access = data.elders.get(elder_id)
        if access is None or access.guardian_id != guardian_id:
            raise HTTPException(status_code=404, detail=NO_ELDER)
        return access

    # ------------------------------------------------ 어르신 연결

    @app.post("/v1/elders/{elder_id}/pairing-code")
    @guarded
    def issue_pairing_code(
        elder_id: int = Path(ge=1, le=MAX_ELDER_ID),
        authorization: str | None = Header(default=None),
    ) -> dict:
        guardian_id = guardian_id_of(authorization)
        owned_elder(guardian_id, elder_id)
        code = new_code()
        expires_at = data.pairings.issue(elder_id, hash_code(code))
        # 코드 원문은 응답에만 있다. 로그에는 발급 사실만 남긴다.
        logger.info("연결 코드를 발급했다 elder_id=%s guardian_id=%s", elder_id, guardian_id)
        return {"code": code, "expires_at": iso_kst(expires_at)}

    @app.post("/v1/pair")
    @guarded
    def pair(body: PairRequest) -> dict:
        code_hash = hash_code(body.code)
        elder_id = data.elders.find_by_phone(digits_of(body.phone))
        # 없는 번호, 틀린 코드, 만료, 잠금 모두 같은 응답이다 — 어느 쪽인지 알려 주면
        # 등록된 번호를 찾아내는 데 쓰인다.
        if elder_id is None or not data.pairings.redeem(elder_id, code_hash):
            logger.warning("연결 실패")
            raise HTTPException(status_code=401, detail=BAD_PAIR)
        new = generate_elder_key()
        data.elder_keys.replace(
            elder_id=elder_id, key_prefix=new.key_prefix, key_hash=new.key_hash
        )
        access = data.elders.get(elder_id)
        logger.info("어르신 폰을 연결했다 elder_id=%s key=%s", elder_id, new.key_prefix)
        return {"elder_key": new.key, "elder_name": "" if access is None else access.name}
