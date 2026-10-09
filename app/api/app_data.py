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
from dataclasses import dataclass, field
from datetime import date, datetime

from fastapi import FastAPI, Header, HTTPException, Path, Query, Response
from pydantic import BaseModel, Field

from app.api.alerts import AlertStore
from app.api.calls import MAX_ELDER_ID
from app.api.contacts import ContactStore, TooManyContacts
from app.api.elder_auth import ElderAuth, ElderKeyStore, elder_key_label, generate_elder_key
from app.api.elder_directory import (
    STATUS_PENDING,
    ElderDirectory,
    PendingLimit,
    PhoneTaken,
    digits_of,
)
from app.api.guardian_auth import GuardianAuth, attempt_label
from app.api.invites import InviteStore, hash_invite_code, new_invite_code
from app.api.pairing import PairingStore, hash_code, new_code
from app.api.rate_limit import FailureLimiter
from app.api.reports import Reports, kst_week_start, sunday_on_or_before
from app.scheduler import KST

logger = logging.getLogger(__name__)

NEED_KEY = "열쇠가 필요합니다"
NO_ELDER = "등록되지 않은 어르신입니다"
BAD_PAIR = "연결 코드를 확인해 주세요"
UNAVAILABLE = "인증을 확인할 수 없습니다"
BAD_SIGNUP = "가입 코드를 확인해 주세요"
PHONE_TAKEN = "이미 등록된 번호예요"
NEEDS_AGREEMENT = "안부 전화를 받는 데 동의해야 가입할 수 있어요"
TRY_LATER = "잠시 뒤에 다시 해 주세요"
WAITING = "보호자 승인을 기다리고 있어요"
NOT_PENDING = "승인 대기 중인 어르신이 아니에요"

# 한 보호자의 승인 대기 상한. 코드를 찍어 보는 사람이 보호자 화면을 도배하지 못하게 한다.
MAX_PENDING_PER_GUARDIAN = 5


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
    invites: InviteStore
    wall_clock: Callable[[], float] = time.time
    signup_limiter: FailureLimiter = field(default_factory=FailureLimiter)


def iso_kst(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, KST).isoformat(timespec="seconds")


class SignupRequest(BaseModel):
    code: str = Field(pattern=r"^[0-9]{8}$")
    name: str = Field(min_length=1, max_length=30)
    phone: str = Field(pattern=r"^[0-9+\- ]{9,20}$")
    agreed: bool


class PairRequest(BaseModel):
    code: str = Field(pattern=r"^[0-9]{6}$")
    phone: str = Field(min_length=7, max_length=20)


class ContactRequest(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    relation: str = Field(default="", max_length=20)
    phone: str = Field(pattern=r"^[0-9+\- ]{5,20}$")


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

    def ready_elder_id_of(authorization: str | None) -> int:
        """어르신 열쇠 + 승인 대기가 아닐 것. 대기 중이면 403."""
        elder_id = elder_id_of(authorization)
        access = data.elders.get(elder_id)
        if access is not None and access.status == STATUS_PENDING:
            raise HTTPException(status_code=403, detail=WAITING)
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

    # ------------------------------------------------ 보호자 조회

    @app.get("/v1/guardian/elders")
    @guarded
    def guardian_elders(authorization: str | None = Header(default=None)) -> dict:
        guardian_id = guardian_id_of(authorization)
        week = kst_week_start(data.wall_clock())
        summaries = data.reports.elder_summaries(guardian_id, week)
        return {
            "week_start": week.isoformat(),
            "elders": [
                {
                    "elder_id": s.elder_id,
                    "name": s.name,
                    "last_call_at": None if s.last_call_at is None else iso_kst(s.last_call_at),
                    "last_status": s.last_status,
                    "week_calls": s.week_calls,
                    "week_avg_score": s.week_avg_score,
                    "week_alerts": s.week_alerts,
                    "status": s.status,
                    "phone": s.phone,
                }
                for s in summaries
            ],
        }

    @app.get("/v1/elders/{elder_id}/weekly")
    @guarded
    def elder_weekly(
        elder_id: int = Path(ge=1, le=MAX_ELDER_ID),
        week_start: date | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict:
        guardian_id = guardian_id_of(authorization)
        owned_elder(guardian_id, elder_id)
        week = (
            kst_week_start(data.wall_clock())
            if week_start is None
            else sunday_on_or_before(week_start)
        )
        days = data.reports.weekly(elder_id, week)
        scored = [d.avg_score for d in days if d.avg_score is not None]
        return {
            "week_start": week.isoformat(),
            "days": [{"date": d.date, "calls": d.calls, "avg_score": d.avg_score} for d in days],
            "total_calls": sum(d.calls for d in days),
            "avg_score": None if not scored else sum(scored) / len(scored),
        }

    @app.get("/v1/guardian/alerts")
    @guarded
    def guardian_alerts(
        limit: int = Query(default=20, ge=1, le=100),
        authorization: str | None = Header(default=None),
    ) -> dict:
        guardian_id = guardian_id_of(authorization)
        names = {ref.elder_id: ref.name for ref in data.elders.elders_of(guardian_id)}
        records = data.alerts.recent_for_guardian(guardian_id, limit)
        return {
            "alerts": [
                {
                    "alert_id": r.alert_id,
                    "elder_id": r.elder_id,
                    "elder_name": names.get(r.elder_id, ""),
                    "type": r.alert_type,
                    "severity": r.severity,
                    "message": r.message,
                    "created_at": iso_kst(r.created_at),
                }
                for r in records
            ]
        }

    # ------------------------------------------------ 어르신 조회·연락처

    @app.get("/v1/me/calls")
    @guarded
    def my_calls(
        limit: int = Query(default=30, ge=1, le=100),
        authorization: str | None = Header(default=None),
    ) -> dict:
        elder_id = ready_elder_id_of(authorization)
        lines = data.reports.call_lines(elder_id, limit)
        return {
            "calls": [
                {
                    "call_id": line.call_id,
                    "started_at": iso_kst(line.started_at),
                    "duration_s": line.duration_s,
                    "status": line.status,
                }
                for line in lines
            ]
        }

    @app.get("/v1/me/contacts")
    @guarded
    def my_contacts(authorization: str | None = Header(default=None)) -> dict:
        elder_id = ready_elder_id_of(authorization)
        access = data.elders.get(elder_id)
        profile = None if access is None else data.elders.guardian_profile(access.guardian_id)
        return {
            "guardians": []
            if profile is None
            else [{"name": profile.name, "relation": "보호자", "phone": profile.phone}],
            "contacts": [
                {"contact_id": c.contact_id, "name": c.name, "relation": c.relation, "phone": c.phone}
                for c in data.contacts.list(elder_id)
            ],
        }

    @app.post("/v1/me/contacts", status_code=201)
    @guarded
    def add_contact(body: ContactRequest, authorization: str | None = Header(default=None)) -> dict:
        elder_id = ready_elder_id_of(authorization)
        try:
            contact = data.contacts.add(
                elder_id, name=body.name, relation=body.relation, phone=body.phone
            )
        except TooManyContacts:
            raise HTTPException(status_code=400, detail="연락처는 20개까지 둘 수 있습니다")
        # 전화번호는 로그에 남기지 않는다.
        logger.info("연락처를 추가했다 elder_id=%s contact_id=%s", elder_id, contact.contact_id)
        return {
            "contact_id": contact.contact_id,
            "name": contact.name,
            "relation": contact.relation,
            "phone": contact.phone,
        }

    @app.delete("/v1/me/contacts/{contact_id}")
    @guarded
    def delete_contact(
        contact_id: int = Path(ge=1, le=MAX_ELDER_ID),
        authorization: str | None = Header(default=None),
    ) -> Response:
        elder_id = ready_elder_id_of(authorization)
        if not data.contacts.remove(elder_id, contact_id):
            raise HTTPException(status_code=404, detail="없는 연락처입니다")
        return Response(status_code=204)

    # ------------------------------------------------ 보호자 코드로 어르신 가입

    @app.post("/v1/guardian/invite")
    @guarded
    def issue_invite(authorization: str | None = Header(default=None)) -> dict:
        guardian_id = guardian_id_of(authorization)
        code = new_invite_code()
        data.invites.issue(guardian_id, hash_invite_code(code))
        # 코드 원문은 응답에만 있다. 로그에는 발급 사실만 남긴다.
        logger.info("보호자 개인 코드를 발급했다 guardian_id=%s", guardian_id)
        return {"code": code}

    @app.post("/v1/signup")
    @guarded
    def signup(body: SignupRequest) -> dict:
        if not body.agreed:
            raise HTTPException(status_code=400, detail=NEEDS_AGREEMENT)
        if data.signup_limiter.blocked():
            raise HTTPException(status_code=429, detail=TRY_LATER)
        guardian_id = data.invites.find_guardian(hash_invite_code(body.code))
        if guardian_id is None:
            # 코드를 찍어 보는 시도만 센다. 맞는 코드의 정상 가입은 한도에 걸리지 않는다.
            data.signup_limiter.record_failure()
            logger.warning("가입 실패")
            raise HTTPException(status_code=401, detail=BAD_SIGNUP)
        try:
            elder_id = data.elders.create_pending(
                guardian_id=guardian_id,
                name=body.name.strip(),
                phone=body.phone.strip(),
                max_pending=MAX_PENDING_PER_GUARDIAN,
            )
        except PhoneTaken:
            raise HTTPException(status_code=409, detail=PHONE_TAKEN)
        except PendingLimit:
            # 사유를 알려 주지 않는다 — 없는 코드와 같은 응답이다.
            raise HTTPException(status_code=401, detail=BAD_SIGNUP)
        new = generate_elder_key()
        data.elder_keys.replace(
            elder_id=elder_id, key_prefix=new.key_prefix, key_hash=new.key_hash
        )
        logger.info("승인 대기로 가입했다 elder_id=%s guardian_id=%s key=%s", elder_id, guardian_id, new.key_prefix)
        return {"elder_key": new.key, "status": STATUS_PENDING}

    @app.post("/v1/elders/{elder_id}/approve")
    @guarded
    def approve_elder(
        elder_id: int = Path(ge=1, le=MAX_ELDER_ID),
        authorization: str | None = Header(default=None),
    ) -> dict:
        guardian_id = guardian_id_of(authorization)
        owned_elder(guardian_id, elder_id)
        if not data.elders.approve(elder_id, guardian_id):
            raise HTTPException(status_code=409, detail=NOT_PENDING)
        logger.info("가입을 승인했다 elder_id=%s guardian_id=%s", elder_id, guardian_id)
        return {"status": "active"}

    @app.post("/v1/elders/{elder_id}/reject")
    @guarded
    def reject_elder(
        elder_id: int = Path(ge=1, le=MAX_ELDER_ID),
        authorization: str | None = Header(default=None),
    ) -> dict:
        guardian_id = guardian_id_of(authorization)
        owned_elder(guardian_id, elder_id)
        if not data.elders.reject(elder_id, guardian_id):
            raise HTTPException(status_code=409, detail=NOT_PENDING)
        logger.info("가입을 거절했다 elder_id=%s guardian_id=%s", elder_id, guardian_id)
        return {"status": "rejected"}

    @app.get("/v1/me/status")
    @guarded
    def my_status(authorization: str | None = Header(default=None)) -> dict:
        elder_id = elder_id_of(authorization)
        access = data.elders.get(elder_id)
        if access is None:
            # 거절돼 지워진 어르신의 열쇠다.
            raise HTTPException(status_code=401, detail=NEED_KEY)
        return {"status": access.status, "name": access.name}
