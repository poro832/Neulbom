"""앱 화면용 주소 모음 — 어르신 연결, 보호자 조회, 어르신 조회·연락처 (설계: 앱 화면을 실제 데이터로).

기존 `/v1/calls/request`와 같은 원칙이다: 열쇠가 없거나 틀리면 401(이유는 말하지 않는다),
남의 어르신이면 없는 어르신과 같은 404, 저장소가 고장 나면 503(열린 채로 두지 않는다).
`AppData`를 주지 않으면 이 주소들은 아예 등록되지 않는다.
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from datetime import time as time_of_day
from pathlib import Path as PathType  # fastapi.Path(주소 인자)와 이름이 겹친다

from fastapi import FastAPI, Header, HTTPException, Path, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool, field_validator

from app.api.account_deletion import withdraw_elder, withdraw_guardian
from app.api.alerts import AlertStore
from app.api.call_content import CallContentStore, InMemoryCallContent, MENTION_CATEGORIES
from app.api.calls import MAX_ELDER_ID
from app.api.contacts import ContactStore, TooManyContacts
from app.api.devices import DeviceStore, InMemoryDeviceStore
from app.api.elder_auth import ElderAuth, ElderKeyStore, elder_key_label, generate_elder_key
from app.api.elder_directory import (
    STATUS_PENDING,
    STATUS_UNLINKED,
    ElderDirectory,
    PendingLimit,
    PhoneTaken,
    digits_of,
    mask_phone,
)
from app.api.guardian_accounts import (
    EmailTaken,
    GuardianAccounts,
    InMemoryGuardianAccounts,
    normalize_email,
)
from app.api.guardian_auth import GuardianAuth, attempt_label, generate_key, hash_key, parse_bearer
from app.api.passwords import DUMMY_HASH, hash_password, verify_password
from app.api.invites import InviteStore, hash_invite_code, new_invite_code
from app.api.link_codes import CodeCollision, InMemoryLinkCodeStore, LinkCodeStore
from app.api.pairing import PairingStore, hash_code, new_code
from app.api.rate_limit import FailureLimiter, InFlightLimiter, KeyedFailureLimiter
from app.api.withdrawals import WITHDRAWAL_TTL_SECONDS, InMemoryWithdrawalStore, WithdrawalRequest, WithdrawalStore
from app.api.reports import (
    DayStat,
    Reports,
    kst_week_start,
    month_week_starts,
    sunday_on_or_before,
    week_bounds,
)
from app.firebase_verify import EmailVerifier
from app.recordings import RecordingDeleter
from app.scheduler import DEFAULT_GRACE_SECONDS, KST

logger = logging.getLogger(__name__)

NEED_KEY = "열쇠가 필요합니다"
NO_ELDER = "등록되지 않은 어르신입니다"
BAD_PAIR = "연결 코드를 확인해 주세요"
UNAVAILABLE = "인증을 확인할 수 없습니다"
BAD_SIGNUP = "가입 코드를 확인해 주세요"
# 언급은 30일 보관이라 한 주를 채울 만큼 통화를 넉넉히 가져와 주 경계로 거른다(많은 통화가 쌓여도 지난 주가 비지 않게).
MENTION_CALL_FETCH_LIMIT = 500
NEEDS_AGREEMENT = "안부 전화를 받는 데 동의해야 가입할 수 있어요"
TRY_LATER = "잠시 뒤에 다시 해 주세요"
WAITING = "보호자 승인을 기다리고 있어요"
NOT_PENDING = "승인 대기 중인 어르신이 아니에요"
NO_CALL = "없는 통화입니다"
BAD_LOGIN = "이메일이나 비밀번호를 확인해 주세요"
EMAIL_TAKEN = "이미 가입된 이메일이에요"
BAD_CURRENT = "현재 비밀번호를 확인해 주세요"
MIN_PASSWORD = 8
APP_KEY_LABEL = "앱"
NOT_ACTIVATED = "운영자 확인 후 사용할 수 있어요"
EMAIL_NOT_VERIFIED = "이메일 인증 후 사용할 수 있어요"
BAD_EMAIL_PROOF = "이메일 인증을 확인하지 못했어요"
EMAIL_VERIFY_OFF = "이메일 인증을 아직 쓸 수 없어요"
BAD_RESET = "비밀번호 재설정을 확인하지 못했어요"
BAD_LINK = "연결 코드를 확인해 주세요"
LINK_WAITING = "보호자 연결을 기다리고 있어요"
ALREADY_LINKED = "이미 보호자가 연결돼 있어요"
TOO_MANY_ELDERS = "더 이상 어르신을 연결할 수 없어요"
PHONE_USED = "이미 등록된 번호예요"
BAD_MONTH = "달을 확인해 주세요"
BAD_PASSWORD = "비밀번호를 확인해 주세요"
NO_ACCOUNT = "삭제할 계정이 없어요"
CALL_TIME_RANGE = "안부 전화 시간은 오전 7시부터 오후 9시까지 30분 단위로 고를 수 있어요"
CALL_TIME_JUST_PASSED = (
    "방금 지난 시간이라 곧바로 전화가 걸릴 수 있어요. "
    "지금보다 나중 시간이나 더 일찍 지난 시간(내일부터 걸려요)을 골라 주세요"
)

# 보호자가 고를 수 있는 안부 전화 시간: 07:00 ~ 21:00(둘 다 포함), 30분 단위(형식은 CallTimeRequest가 본다).
EARLIEST_CALL_TIME = time_of_day(7, 0)
LATEST_CALL_TIME = time_of_day(21, 0)

# 한 보호자가 연결할 수 있는 어르신 수. 코드를 가진 사람이 한 보호자에게 어르신을 무한히 붙이지 못하게 한다.
MAX_ELDERS_PER_GUARDIAN = 10
# 연결 코드 지문이 다른 어르신과 겹칠 때 새 코드로 다시 시도하는 횟수(1억 가지라 사실상 한 번이면 된다).
LINK_CODE_RETRIES = 5
# 보호자가 어르신 전화번호를 고친 뒤, 새 폰이 번호만으로 한 번 로그인할 수 있는 시간.
PHONE_CLAIM_SECONDS = 24 * 3600
NEED_WITHDRAW_APPROVAL = "보호자의 승인이 필요해요"
NO_WITHDRAWAL = "탈퇴 요청이 없어요"
WITHDRAWAL_LOCKED = "보호자가 이미 승인해서 곧 탈퇴돼요"
# 틀린 번호, 열리지 않은 번호, 이미 쓴 번호, 만료 모두 같은 문장이다 — 어느 쪽인지 알려 주면 등록된 번호를 찾아내는 데 쓰인다.
BAD_ELDER_LOGIN = "이 폰으로는 로그인할 수 없어요. 보호자에게 어르신 관리에서 번호를 확인해 달라고 부탁해 주세요"

# 한 보호자의 승인 대기 상한. 코드를 찍어 보는 사람이 보호자 화면을 도배하지 못하게 한다.
MAX_PENDING_PER_GUARDIAN = 5

# 한 보호자의 사용 중 앱 열쇠 상한. 로그인을 거듭해도 열쇠가 무한히 쌓이지 않게, 넘으면 가장 오래된 것부터 폐기한다.
MAX_ACTIVE_KEYS_PER_GUARDIAN = 10

# 비밀번호 재설정 증명서는 "방금" 이메일·비밀번호로 Firebase에 로그인해 받은 것이어야 한다(토큰의 auth_time).
# 토큰을 새로 받아도 auth_time은 처음 로그인한 때 그대로라, 오래 열어 둔 Firebase 세션의 증명서는 여기서 걸린다.
# 앞쪽은 구글 시계가 우리 서버보다 조금 빠를 때를 위한 여유다.
RESET_SIGN_IN_MAX_AGE_SECONDS = 300
RESET_SIGN_IN_MAX_AHEAD_SECONDS = 60
# 재설정 동시 확인 자리의 이름. 열쇠가 없어 보호자 번호로 나눌 수 없다 — 요청마다 이 이름에 고유한 표를 붙여
# 자리를 얻으므로 보호자별 하나 제한 없이 서버 전체 수(InFlightLimiter의 limit)만 걸린다.
PASSWORD_RESET_SLOT = "password-reset"


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
    content: CallContentStore = field(default_factory=InMemoryCallContent)
    accounts: GuardianAccounts = field(default_factory=InMemoryGuardianAccounts)
    # 같은 이메일 15분 5회 실패 잠금 / 서버 전체 분당 20회 실패·가입 시도 한도
    login_limiter: KeyedFailureLimiter = field(default_factory=KeyedFailureLimiter)
    account_failures: FailureLimiter = field(default_factory=FailureLimiter)
    signup_attempts: FailureLimiter = field(default_factory=FailureLimiter)
    devices: DeviceStore = field(default_factory=InMemoryDeviceStore)
    # 어르신 먼저 가입: 연결 코드 저장소 / 어르신 가입 시도 한도(성공도 센다) / 보호자의 코드 실패 한도
    links: LinkCodeStore = field(default_factory=InMemoryLinkCodeStore)
    elder_signup_attempts: FailureLimiter = field(default_factory=FailureLimiter)
    link_attempts: FailureLimiter = field(default_factory=FailureLimiter)
    # 새 폰 로그인 시도 한도(실패와 성공 모두 센다 — 인증 없는 주소라 번호를 찍어 보는 것을 늦춘다)
    elder_login_attempts: FailureLimiter = field(default_factory=FailureLimiter)
    # 보호자 이메일 인증: Firebase 증명서 확인기(없으면 인증 주소는 닫힌다) / 서버 전체 분당 20회 실패 한도 /
    # 동시에 확인하는 수(보호자마다 하나, 서버 전체 4개 — 넘으면 기다리지 않고 429)
    email_verifier: EmailVerifier | None = None
    email_verify_failures: FailureLimiter = field(default_factory=FailureLimiter)
    email_verify_slots: InFlightLimiter = field(default_factory=InFlightLimiter)
    # 비밀번호 재설정(열쇠 없이 부른다, 확인기는 위의 것을 같이 쓴다): 서버 전체 분당 20회 실패 한도 /
    # 동시에 확인하는 수(서버 전체 4개 — 넘으면 기다리지 않고 429). 이메일 인증 자리와는 따로 센다 —
    # 열쇠 없는 요청이 몰려도 로그인한 보호자의 이메일 인증 자리를 빼앗지 못하게.
    password_reset_failures: FailureLimiter = field(default_factory=FailureLimiter)
    password_reset_slots: InFlightLimiter = field(default_factory=InFlightLimiter)
    # 어르신 탈퇴 때 S3 녹음을 지운다(RECORDINGS_BUCKET이 없으면 None — 녹음은 버킷의 30일 수명 규칙에 맡긴다).
    recording_deleter: RecordingDeleter | None = None
    # 어르신 탈퇴 요청(보호자 전원이 승인해야 탈퇴된다) / 보호자에게 푸시를 보내는 쪽(없으면 푸시 없이 요청 목록만)
    withdrawals: WithdrawalStore = field(default_factory=InMemoryWithdrawalStore)
    notifier: object | None = None
    # 어르신 탈퇴 때 서버 디스크에 남은 녹음 파일도 지운다(보관기가 쓰는 폴더). None이면 건드리지 않는다.
    recordings_dir: PathType | None = None


def iso_kst(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, KST).isoformat(timespec="seconds")


def days_json(days: list[DayStat]) -> list[dict]:
    return [{"date": d.date, "calls": d.calls, "avg_score": d.avg_score} for d in days]


def hhmm(value: time_of_day) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def just_passed(now_kst: datetime, value: time_of_day) -> bool:
    """오늘의 value가 지금(한국 시간)부터 유예 안쪽으로 막 지났는가 — 지금 그 분도 포함한다.

    그렇다면 스케줄러(app/scheduler.py)가 다음 확인(1분 안)에서 곧바로 건다. 분 단위로 세서 초는 버린다:
    9:30:59에 09:00은 30분 차이로 거절한다(스케줄러는 이미 유예를 넘었다고 볼 때라 조금 더 조심하는 쪽이다).
    더 일찍 지난 시간은 오늘은 건너뛰고 내일부터 걸린다.
    """
    now_m = now_kst.hour * 60 + now_kst.minute
    new_m = value.hour * 60 + value.minute
    return 0 <= now_m - new_m <= DEFAULT_GRACE_SECONDS // 60


def signed_in_just_now(auth_time: int | None, now: float) -> bool:
    """Firebase 로그인 시각이 지금부터 300초 안쪽(앞으로 60초까지)인가. 없거나 정수가 아니면 False."""
    if not isinstance(auth_time, int) or isinstance(auth_time, bool):
        return False
    return now - RESET_SIGN_IN_MAX_AGE_SECONDS <= auth_time <= now + RESET_SIGN_IN_MAX_AHEAD_SECONDS


def mean_of_day_means(days: list[DayStat]) -> float | None:
    """점수가 있는 날들의 평균의 평균. 주간·월간이 같은 식을 쓴다(통화가 많은 날이 기간 평균을 끌고 가지 않게)."""
    scored = [d.avg_score for d in days if d.avg_score is not None]
    return None if not scored else sum(scored) / len(scored)


class SignupRequest(BaseModel):
    code: str = Field(pattern=r"^[0-9]{8}$")
    name: str = Field(min_length=1, max_length=30)
    phone: str = Field(pattern=r"^[0-9+\- ]{9,20}$")
    agreed: bool


class AccountSignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=120)
    phone: str = Field(pattern=r"^[0-9+\- ]{9,20}$")
    password: str = Field(min_length=MIN_PASSWORD, max_length=128)

    @field_validator("name", "email", "phone", mode="before")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=128)


class DeviceRequest(BaseModel):
    # FCM 토큰은 보통 160~200자다. 등록 상한을 두었으니 길이도 넉넉한 만큼만 받는다.
    token: str = Field(min_length=20, max_length=512)


class UnregisterRequest(BaseModel):
    # 해제는 짧은 값에도 같은 204다(설계: 존재 여부를 알려 주지 않는다). 길이 상한만 둔다.
    token: str = Field(min_length=1, max_length=4096)


class PasswordChangeRequest(BaseModel):
    current: str = Field(min_length=1, max_length=128)
    new: str = Field(min_length=MIN_PASSWORD, max_length=128)


class PairRequest(BaseModel):
    code: str = Field(pattern=r"^[0-9]{6}$")
    phone: str = Field(min_length=7, max_length=20)


class ElderSignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    phone: str = Field(pattern=r"^[0-9+\- ]{9,20}$")
    agreed: bool


class WithdrawalDecision(BaseModel):
    # 보호자 화면이 본 요청의 번호. 그 사이 취소되고 다시 요청됐다면 닿지 않는다.
    request_id: int = Field(ge=1, le=MAX_ELDER_ID)


class ElderLoginRequest(BaseModel):
    phone: str = Field(pattern=r"^[0-9+\- ]{9,20}$")


class LinkRequest(BaseModel):
    code: str = Field(pattern=r"^[0-9]{8}$")


class EmailProofRequest(BaseModel):
    id_token: str = Field(min_length=20, max_length=4096)


class PasswordResetRequest(BaseModel):
    id_token: str = Field(min_length=20, max_length=4096)
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=128)


class GuardianWithdrawRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class ElderWithdrawRequest(BaseModel):
    # 실수로 지우지 않게 JSON의 true 그대로만 받는다(1, "true", null은 422).
    confirm: StrictBool

    @field_validator("confirm")
    @classmethod
    def _must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("confirm은 true여야 한다")
        return value


class ContactRequest(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    relation: str = Field(default="", max_length=20)
    phone: str = Field(pattern=r"^[0-9+\- ]{5,20}$")


class PhoneChangeRequest(BaseModel):
    phone: str = Field(pattern=r"^[0-9+\- ]{9,20}$")


class CallTimeRequest(BaseModel):
    # HH:MM, 정각이나 30분. 숫자는 [0-9]만 받는다(\d는 전각·다른 문자의 숫자도 맞는다).
    call_time: str = Field(pattern=r"^([01][0-9]|2[0-3]):(00|30)$")


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

    def active_guardian_id_of(authorization: str | None) -> int:
        """열쇠 + 이메일 인증 + 운영자가 열어 준 보호자일 것. 계정 표에 없는 보호자(운영 도구가 만든 열쇠 전용)는 열린 것으로 본다.

        이메일 인증을 먼저 검사한다 — 보호자가 직접 할 수 있는 일을 먼저 알린다.
        """
        guardian_id = guardian_id_of(authorization)
        account = data.accounts.profile(guardian_id)
        if account is not None and not account.email_verified:
            raise HTTPException(status_code=403, detail=EMAIL_NOT_VERIFIED)
        if account is not None and not account.activated:
            raise HTTPException(status_code=403, detail=NOT_ACTIVATED)
        return guardian_id

    def ready_elder_id_of(authorization: str | None) -> int:
        """어르신 열쇠 + 승인 대기·연결 전이 아닐 것. 아니면 403."""
        elder_id = elder_id_of(authorization)
        access = data.elders.get(elder_id)
        if access is not None and access.status == STATUS_UNLINKED:
            raise HTTPException(status_code=403, detail=LINK_WAITING)
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
        return {
            "week_start": week.isoformat(),
            "days": days_json(days),
            "total_calls": sum(d.calls for d in days),
            "avg_score": mean_of_day_means(days),
            "baseline_calls": baseline_calls_of(elder_id),
        }

    @app.get("/v1/elders/{elder_id}/monthly")
    @guarded
    def elder_monthly(
        elder_id: int = Path(ge=1, le=MAX_ELDER_ID),
        month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
        authorization: str | None = Header(default=None),
    ) -> dict:
        guardian_id = guardian_id_of(authorization)
        owned_elder(guardian_id, elder_id)
        try:
            first = (
                datetime.fromtimestamp(data.wall_clock(), KST).date().replace(day=1)
                if month is None
                else date(int(month[:4]), int(month[5:]), 1)
            )
            weeks = month_week_starts(first)
        except (ValueError, OverflowError):
            # 형식은 맞아도 날짜로 셀 수 없는 달(0000-01, 9999-12)이다.
            raise HTTPException(status_code=422, detail=BAD_MONTH)
        # 서버의 날짜별 통계는 주 단위다. 그 달에 걸친 주들을 읽어 그 달의 날만 모은다(주는 겹치지 않는다).
        prefix = f"{first.year:04d}-{first.month:02d}-"
        days = sorted(
            (d for week in weeks for d in data.reports.weekly(elder_id, week) if d.date.startswith(prefix)),
            key=lambda d: d.date,
        )
        return {
            "month": prefix[:-1],
            "days": days_json(days),
            "total_calls": sum(d.calls for d in days),
            "avg_score": mean_of_day_means(days),
            "baseline_calls": baseline_calls_of(elder_id),
        }

    def baseline_calls_of(elder_id: int) -> int | None:
        """평소 기준에 쓸 수 있는 최근 통화 수. 안내 한 줄용 덤이라 못 읽어도 통계는 막지 않는다(앱은 null이면 안내를 숨긴다)."""
        try:
            return data.reports.baseline_calls(elder_id)
        except Exception:
            logger.exception("평소 기준 통화 수 조회에 실패했다 elder_id=%s", elder_id)
            return None

    # ------------------------------------------------ 안부 전화 시간

    @app.get("/v1/elders/{elder_id}/call-time")
    @guarded
    def elder_call_time(
        elder_id: int = Path(ge=1, le=MAX_ELDER_ID),
        authorization: str | None = Header(default=None),
    ) -> dict:
        guardian_id = guardian_id_of(authorization)
        owned_elder(guardian_id, elder_id)
        value = data.elders.call_time_of(elder_id)
        if value is None:
            raise HTTPException(status_code=404, detail=NO_ELDER)
        return {"call_time": hhmm(value)}

    @app.put("/v1/elders/{elder_id}/call-time")
    @guarded
    def change_elder_call_time(
        body: CallTimeRequest,
        elder_id: int = Path(ge=1, le=MAX_ELDER_ID),
        authorization: str | None = Header(default=None),
    ) -> dict:
        # 형식(HH:MM, 30분 단위)은 본문 모델이 먼저 422로 거른다. 그다음 열쇠·소유, 범위, 방금 지난 시간 순서다.
        guardian_id = active_guardian_id_of(authorization)
        owned_elder(guardian_id, elder_id)
        value = time_of_day(int(body.call_time[:2]), int(body.call_time[3:]))
        if not EARLIEST_CALL_TIME <= value <= LATEST_CALL_TIME:
            raise HTTPException(status_code=422, detail=CALL_TIME_RANGE)
        # 스케줄러는 이 칸을 매분 새로 읽고 유예 안이면 곧바로 건다. 방금 지난 시간으로 바꾸면 예고 없이 전화가 간다.
        if just_passed(datetime.fromtimestamp(data.wall_clock(), KST), value):
            raise HTTPException(status_code=409, detail=CALL_TIME_JUST_PASSED)
        if not data.elders.set_call_time(elder_id, guardian_id, value):
            raise HTTPException(status_code=404, detail=NO_ELDER)
        # 번호·이름은 남기지 않는다.
        logger.info(
            "안부 전화 시간을 바꿨다 elder_id=%s guardian_id=%s 시각=%s", elder_id, guardian_id, hhmm(value)
        )
        return {"call_time": hhmm(value)}

    # ------------------------------------------------ 어르신 전화번호

    @app.get("/v1/elders/{elder_id}/phone")
    @guarded
    def elder_phone(
        elder_id: int = Path(ge=1, le=MAX_ELDER_ID),
        authorization: str | None = Header(default=None),
    ) -> dict:
        guardian_id = guardian_id_of(authorization)
        owned_elder(guardian_id, elder_id)
        phone = data.elders.phone_of(elder_id)
        if phone is None:
            raise HTTPException(status_code=404, detail=NO_ELDER)
        return {"phone": phone}

    @app.put("/v1/elders/{elder_id}/phone")
    @guarded
    def change_elder_phone(
        body: PhoneChangeRequest,
        elder_id: int = Path(ge=1, le=MAX_ELDER_ID),
        authorization: str | None = Header(default=None),
    ) -> dict:
        """어르신이 폰(번호)을 바꿨을 때 보호자가 새 번호로 고친다.

        옛 번호의 폰이 남의 손에 넘어가도 어르신 기록을 못 보도록 어르신 열쇠를 모두 지운다. 어르신은 새 폰에서
        연결 코드로 다시 들어온다(보호자가 코드를 새로 만든다).
        """
        guardian_id = active_guardian_id_of(authorization)
        owned_elder(guardian_id, elder_id)
        phone = body.phone.strip()
        try:
            changed = data.elders.set_phone(elder_id, guardian_id, phone)
        except PhoneTaken:
            raise HTTPException(status_code=409, detail=PHONE_USED)
        if not changed:
            raise HTTPException(status_code=404, detail=NO_ELDER)
        removed = data.elder_keys.remove_for_elder(elder_id)
        # 새 폰은 24시간 안에 번호만으로 한 번 로그인할 수 있다(연결 코드를 따로 받지 않는다).
        until = data.wall_clock() + PHONE_CLAIM_SECONDS
        data.elders.open_new_phone_login(elder_id, guardian_id, until)
        # 번호·이름은 남기지 않는다.
        logger.info("어르신 전화번호를 바꿨다 elder_id=%s guardian_id=%s 지운 열쇠=%s", elder_id, guardian_id, removed)
        return {"phone": phone, "new_phone_login_until": iso_kst(until)}

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

    # ------------------------------------------------ 보호자 계정

    def key_store():
        store = getattr(data.guardian_auth, "store", None)
        if store is None:
            raise RuntimeError("이 인증기는 열쇠 저장소가 없다")
        return store

    def issue_app_key(guardian_id: int) -> str:
        new = generate_key()
        key_store().add(
            guardian_id=guardian_id, label=APP_KEY_LABEL, key_prefix=new.key_prefix, key_hash=new.key_hash
        )
        revoked = key_store().revoke_oldest_beyond(guardian_id, MAX_ACTIVE_KEYS_PER_GUARDIAN)
        if revoked:
            logger.info("열쇠가 상한을 넘어 오래된 것을 폐기했다 guardian_id=%s 수=%s", guardian_id, revoked)
        logger.info("보호자 앱 열쇠를 발급했다 guardian_id=%s key=%s", guardian_id, new.key_prefix)
        return new.key

    # 로그인의 "열쇠 발급"과 비밀번호 변경의 "변경 + 다른 열쇠 폐기"를 한 줄로 세운다.
    # 이게 없으면 옛 비밀번호로 시작한 로그인이 변경이 끝난 뒤에 열쇠를 받아 폐기를 빠져나간다.
    credential_lock = threading.Lock()

    def record_bad_password(email: str, *, known: bool) -> None:
        data.login_limiter.record_failure(email)
        if not known:
            # 없는 이메일 실패만 서버 전체로 센다 — 맞는 계정의 로그인을 남이 막지 못하게.
            data.account_failures.record_failure()

    @app.post("/v1/guardian/signup")
    @guarded
    def guardian_signup(body: AccountSignupRequest) -> dict:
        if data.signup_attempts.blocked():
            raise HTTPException(status_code=429, detail=TRY_LATER)
        data.signup_attempts.record_failure()  # 성공도 센다 — 계정을 마구 만드는 것도 늦춘다
        email = normalize_email(body.email)
        try:
            guardian_id = data.accounts.create(body.name, email, body.phone, hash_password(body.password))
        except EmailTaken:
            raise HTTPException(status_code=409, detail=EMAIL_TAKEN)
        logger.info("보호자가 가입했다 guardian_id=%s", guardian_id)
        return {
            "key": issue_app_key(guardian_id),
            "name": body.name,
            "email": email,
            "phone": body.phone,
            "activated": False,
            "email_verified": False,
        }

    @app.post("/v1/guardian/login")
    @guarded
    def guardian_login(body: LoginRequest) -> dict:
        email = normalize_email(body.email)
        account = data.accounts.find_by_email(email)
        if data.login_limiter.blocked(email) or (account is None and data.account_failures.blocked()):
            # 잠긴 요청은 비밀번호를 검사하지 않는다.
            raise HTTPException(status_code=429, detail=TRY_LATER)
        # 없는 이메일도 같은 시간이 걸리게 가짜 해시와 비교한다.
        ok = verify_password(body.password, account.password_hash if account else DUMMY_HASH)
        if account is None or not ok:
            record_bad_password(email, known=account is not None)
            logger.warning("보호자 로그인 실패")
            raise HTTPException(status_code=401, detail=BAD_LOGIN)
        with credential_lock:
            # 검사하는 사이 비밀번호가 바뀌었으면 이 로그인은 옛 비밀번호로 한 것이다.
            current = data.accounts.profile(account.guardian_id)
            if current is None or current.password_hash != account.password_hash:
                raise HTTPException(status_code=401, detail=BAD_LOGIN)
            key = issue_app_key(account.guardian_id)
        data.login_limiter.clear(email)
        logger.info("보호자가 로그인했다 guardian_id=%s", account.guardian_id)
        return {
            "key": key,
            "name": account.name,
            "email": account.email,
            "phone": account.phone,
            "activated": account.activated,
            "email_verified": account.email_verified,
        }

    @app.post("/v1/guardian/devices")
    @guarded
    def register_device(body: DeviceRequest, authorization: str | None = Header(default=None)) -> Response:
        guardian_id = active_guardian_id_of(authorization)
        previous = data.devices.register(guardian_id, hash_key(parse_bearer(authorization)), body.token)
        moved = f" 이전 보호자={previous}" if previous is not None and previous != guardian_id else ""
        logger.info("보호자 폰을 등록했다 guardian_id=%s token=%s%s", guardian_id, body.token[:8], moved)
        return Response(status_code=204)

    @app.post("/v1/guardian/devices/unregister")
    @guarded
    def unregister_device(body: UnregisterRequest, authorization: str | None = Header(default=None)) -> Response:
        guardian_id = guardian_id_of(authorization)
        # 없는 토큰·남의 토큰도 같은 204다 — 존재 여부를 알려 주지 않는다.
        data.devices.unregister(guardian_id, body.token)
        return Response(status_code=204)

    @app.post("/v1/guardian/logout")
    @guarded
    def guardian_logout(authorization: str | None = Header(default=None)) -> Response:
        guardian_id = guardian_id_of(authorization)
        key_hash = hash_key(parse_bearer(authorization))
        key_store().revoke_hash(key_hash)
        try:
            data.devices.remove_for_key(key_hash)
        except Exception:
            # 폰 등록을 못 지워도 로그아웃은 끝난다. 열쇠가 폐기됐으니 tokens_for가 어차피 걸러낸다.
            logger.exception("로그아웃 중 폰 등록을 지우지 못했다 guardian_id=%s", guardian_id)
        logger.info("보호자가 로그아웃했다 guardian_id=%s", guardian_id)
        return Response(status_code=204)

    @app.get("/v1/guardian/me")
    @guarded
    def guardian_me(authorization: str | None = Header(default=None)) -> dict:
        guardian_id = guardian_id_of(authorization)
        account = data.accounts.profile(guardian_id)
        if account is None:
            raise HTTPException(status_code=404, detail=NEED_KEY)
        return {
            "name": account.name,
            "email": account.email,
            "phone": account.phone,
            "activated": account.activated,
            "email_verified": account.email_verified,
        }

    @app.post("/v1/guardian/email/verify")
    @guarded
    def verify_email(body: EmailProofRequest, authorization: str | None = Header(default=None)) -> dict:
        guardian_id = guardian_id_of(authorization)
        account = data.accounts.profile(guardian_id)
        if account is None or account.email_verified:
            return {"email_verified": True}
        if data.email_verifier is None:
            raise HTTPException(status_code=503, detail=EMAIL_VERIFY_OFF)
        if data.email_verify_failures.blocked():
            raise HTTPException(status_code=429, detail=TRY_LATER)
        # 확인은 작업 스레드 안에서 구글에 닿는 느린 일이다. 자리를 먼저 얻는다 — 못 얻으면 기다리지
        # 않고 바로 429(한꺼번에 보낸 요청이 실패 한도를 지나 스레드를 모두 붙잡지 못하게).
        if not data.email_verify_slots.try_acquire(guardian_id):
            raise HTTPException(status_code=429, detail=TRY_LATER)
        try:
            proof = data.email_verifier.verify(body.id_token)
            # 틀린 증명서, 미인증 이메일, 남의 이메일을 구분해 알려 주지 않는다.
            if proof is None or normalize_email(proof.email) != account.email:
                data.email_verify_failures.record_failure()
                logger.warning("이메일 인증 실패 guardian_id=%s", guardian_id)
                raise HTTPException(status_code=401, detail=BAD_EMAIL_PROOF)
            data.accounts.mark_email_verified(guardian_id)
        finally:
            data.email_verify_slots.release(guardian_id)
        logger.info("이메일 인증을 마쳤다 guardian_id=%s", guardian_id)
        return {"email_verified": True}

    @app.post("/v1/guardian/password")
    @guarded
    def guardian_password(body: PasswordChangeRequest, authorization: str | None = Header(default=None)) -> dict:
        guardian_id = guardian_id_of(authorization)
        account = data.accounts.profile(guardian_id)
        if account is None:
            raise HTTPException(status_code=404, detail=NEED_KEY)
        # 비밀번호 변경은 이미 열쇠가 있는 사람의 일이라 이메일별 한도만 적용한다.
        if data.login_limiter.blocked(account.email):
            raise HTTPException(status_code=429, detail=TRY_LATER)
        if not verify_password(body.current, account.password_hash):
            record_bad_password(account.email, known=True)
            raise HTTPException(status_code=403, detail=BAD_CURRENT)
        new_hash = hash_password(body.new)
        key_hash = hash_key(parse_bearer(authorization))
        with credential_lock:
            # 검사한 뒤 쓰기 전에 비밀번호가 바뀌었거나(재설정·다른 폰의 변경·운영 도구) 이 열쇠가 폐기됐으면, 이 변경은
            # 옛 비밀번호·옛 열쇠로 한 것이다 — 아무것도 쓰지 않는다. 그러지 않으면 새어 나간 비밀번호와 열쇠를 쥔 사람이
            # 메일함 주인의 재설정을 덮어쓴다. 이유는 알리지 않고 열쇠가 틀렸을 때와 같은 401이다(로그인의 다시 보기와 같다).
            current = data.accounts.profile(guardian_id)
            if (
                current is None
                or current.password_hash != account.password_hash
                or not key_store().is_active(key_hash)
            ):
                logger.warning("비밀번호 변경 중 비밀번호나 열쇠가 바뀌어 거절했다 guardian_id=%s", guardian_id)
                raise HTTPException(status_code=401, detail=NEED_KEY)
            data.accounts.set_password(guardian_id, new_hash)
            revoked = key_store().revoke_others(guardian_id, key_hash)
        data.login_limiter.clear(account.email)
        logger.info("보호자가 비밀번호를 바꿨다 guardian_id=%s revoked_others=%s", guardian_id, revoked)
        return {"revoked_others": revoked}

    @app.post("/v1/guardian/password/reset")
    @guarded
    def guardian_password_reset(body: PasswordResetRequest) -> dict:
        """비밀번호를 잊은 보호자 — 열쇠 없이 부른다. 신원은 Firebase 증명서 하나로만 본다.

        우리 프로젝트가 서명했고 이메일이 인증됐고(EmailVerifier), **방금(5분 안) 이메일·비밀번호로 로그인한**
        증명서여야 하고, 그 계정은 **이 서버에서 이미 이메일 인증을 마친** 것이어야 한다. 앱은 이메일 인증이 끝나면
        Firebase 비밀번호를 아무도 모르는 값으로 바꾸므로(EmailProof.rotatePassword), 그 뒤 이 증명서는 재설정 메일의
        링크에서 새 비밀번호를 정한 사람(메일함 주인)만 얻는다. 인증 전 계정은 Firebase 비밀번호가 가입 비밀번호
        그대로라 메일 없이도 증명서를 얻을 수 있다 — 받지 않는다(운영 도구로 되찾는다).
        틀린 증명서, 오래되거나 미래의 로그인, 없는 계정, 인증 전 계정을 구분해 알려 주지 않는다(같은 401, 같은 실패 계수).
        성공하면 그 보호자의 열쇠를 모두 폐기한다 — 남길 "이 폰"의 열쇠가 없다. 이메일·증명서·비밀번호는 기록하지 않는다.
        """
        if data.password_reset_failures.blocked():
            raise HTTPException(status_code=429, detail=TRY_LATER)
        if data.email_verifier is None:
            raise HTTPException(status_code=503, detail=EMAIL_VERIFY_OFF)
        # 확인은 작업 스레드 안에서 구글에 닿는 느린 일이다(이메일 인증과 같은 이유). 자리를 못 얻으면 기다리지 않고 429.
        slot = (PASSWORD_RESET_SLOT, object())
        if not data.password_reset_slots.try_acquire(slot):
            raise HTTPException(status_code=429, detail=TRY_LATER)
        try:
            proof = data.email_verifier.verify(body.id_token)
            account = None
            if proof is not None and signed_in_just_now(proof.auth_time, data.wall_clock()):
                account = data.accounts.find_by_email(normalize_email(proof.email))
            if account is None or account.email_verified is not True:
                data.password_reset_failures.record_failure()
                logger.warning("비밀번호 재설정 확인 실패")
                raise HTTPException(status_code=401, detail=BAD_RESET)
            new_hash = hash_password(body.new_password)  # 느린 해시는 잠금 밖에서 — 다른 로그인을 세우지 않게
            with credential_lock:
                # 로그인의 "열쇠 발급"과 한 줄로 선다: 옛 비밀번호로 시작한 로그인은 이 뒤에 열쇠를 받지 못한다.
                # 열쇠를 먼저 폐기한다 — 비밀번호를 쓰다 실패해도 닫힌 쪽(모든 폰 로그아웃, 비밀번호는 옛 그대로)에 남는다.
                revoked = key_store().revoke_all(account.guardian_id)
                data.accounts.set_password(account.guardian_id, new_hash)
                data.login_limiter.clear(account.email)
        finally:
            data.password_reset_slots.release(slot)
        logger.info("비밀번호를 재설정했다 guardian_id=%s 폐기=%s", account.guardian_id, revoked)
        return {"reset": True}

    # ------------------------------------------------ 탈퇴 (app/api/account_deletion.py)

    @app.delete("/v1/guardian/me")
    @guarded
    def withdraw_guardian_me(
        body: GuardianWithdrawRequest, authorization: str | None = Header(default=None)
    ) -> Response:
        """보호자 탈퇴 — 열쇠와 현재 비밀번호. 어르신은 지우지 않고 연결 전으로 돌린다(안부 전화가 멈춘다).

        비밀번호 검사는 로그인과 같은 규칙이다(같은 이메일 실패 한도, 틀리면 같은 기록). Firebase 계정은 서버가
        지우지 못한다 — 앱이 지운다.
        """
        guardian_id = guardian_id_of(authorization)
        account = data.accounts.profile(guardian_id)
        if account is None:
            # 계정 표에 없는 열쇠 전용 보호자다. Postgres에서는 운영 도구가 만든 보호자도 표에 있지만 비밀번호가 없어
            # (NO_LOGIN) 아래에서 401이다 — 어느 쪽이든 운영 도구(`guardian delete N --yes`)로 지운다.
            raise HTTPException(status_code=404, detail=NO_ACCOUNT)
        if data.login_limiter.blocked(account.email):
            # 잠긴 요청은 비밀번호를 검사하지 않는다.
            raise HTTPException(status_code=429, detail=TRY_LATER)
        if not verify_password(body.password, account.password_hash):  # 느린 해시는 잠금 밖에서
            record_bad_password(account.email, known=True)
            logger.warning("보호자 탈퇴 비밀번호 확인 실패 guardian_id=%s", guardian_id)
            raise HTTPException(status_code=401, detail=BAD_PASSWORD)
        key_hash = hash_key(parse_bearer(authorization))
        with credential_lock:
            # 비밀번호 변경과 같은 다시 보기: 검사한 뒤 비밀번호가 바뀌었거나(재설정·다른 폰·운영 도구) 이 열쇠가
            # 폐기됐으면 옛 비밀번호·옛 열쇠로 한 요청이다 — 아무것도 지우지 않는다. 이유는 알리지 않는다.
            current = data.accounts.profile(guardian_id)
            if (
                current is None
                or current.password_hash != account.password_hash
                or not key_store().is_active(key_hash)
            ):
                logger.warning("보호자 탈퇴 중 비밀번호나 열쇠가 바뀌어 거절했다 guardian_id=%s", guardian_id)
                raise HTTPException(status_code=401, detail=NEED_KEY)
            detached = withdraw_guardian(
                guardian_id,
                elders=data.elders,
                accounts=data.accounts,
                keys=key_store(),
                pairings=data.pairings,
                devices=data.devices,
                invites=data.invites,
                alerts=data.alerts,
            )
        data.login_limiter.clear(account.email)  # 같은 이메일로 다시 가입하면 새로 센다
        logger.info("보호자가 탈퇴했다 guardian_id=%s 어르신 연결 해제=%s", guardian_id, detached)
        return Response(status_code=204)

    def delete_elder_now(elder_id: int) -> None:
        """어르신을 지운다(녹음 포함). 승인이 끝났거나 보호자가 없는 어르신에게만 부른다."""
        result = withdraw_elder(
            elder_id,
            elders=data.elders,
            recording_deleter=data.recording_deleter,
            recordings_dir=data.recordings_dir,
            elder_keys=data.elder_keys,
            contacts=data.contacts,
            content=data.content,
            reports=data.reports,
            alerts=data.alerts,
            withdrawals=data.withdrawals,
        )
        logger.info(
            "어르신이 탈퇴했다 elder_id=%s 녹음=%s개 삭제시도 실패=%s 서버 파일 삭제=%s개",
            elder_id,
            result.recordings,
            result.failed,
            result.local_removed,
        )

    @app.delete("/v1/me")
    @guarded
    def withdraw_elder_me(body: ElderWithdrawRequest, authorization: str | None = Header(default=None)) -> Response:
        """보호자가 없는 어르신(연결 전)의 즉시 탈퇴 — 어르신 열쇠와 {"confirm": true}. 보호자가 있는 어르신은
        승인이 필요해 `POST /v1/me/withdrawal`을 써야 한다(여기서는 409). 녹음(서버 디스크·S3)은 최선으로 지운다."""
        elder_id = elder_id_of(authorization)
        if data.elders.get(elder_id) is None:
            # 지워진 어르신의 열쇠다(Postgres에서는 CASCADE로 열쇠도 지워져 위에서 이미 401이다).
            raise HTTPException(status_code=401, detail=NEED_KEY)
        if data.elders.guardians_of(elder_id):
            raise HTTPException(status_code=409, detail=NEED_WITHDRAW_APPROVAL)
        delete_elder_now(elder_id)
        return Response(status_code=204)

    # ------------------------------------------------ 어르신 탈퇴 요청: 보호자 전원이 승인해야 탈퇴된다

    def live_withdrawal(elder_id: int) -> WithdrawalRequest | None:
        """살아 있는(만료되지 않은) 요청. 만료된 요청은 여기서 지운다."""
        request = data.withdrawals.get(elder_id)
        if request is None:
            return None
        if not request.locked and request.requested_at + WITHDRAWAL_TTL_SECONDS <= data.wall_clock():
            data.withdrawals.cancel(elder_id)
            return None
        guardians = data.elders.guardians_of(elder_id)
        if not request.rejected and guardians and set(guardians) <= request.approved_by:
            # 보호자가 모두 승인했는데 지우다 실패해서 남은 요청이다 — 잠그고(취소·재요청이 끼어들지 못하게) 이어서 지운다.
            # 지우지 못하면 오류가 올라가 503이 되고, 잠긴 요청은 그대로라 다음에 다시 시도한다.
            if not data.withdrawals.lock(elder_id, request.request_id, data.wall_clock()):
                return data.withdrawals.get(elder_id)  # 그 사이 바뀐 요청이다 — 새 요청은 새로 판단한다
            logger.warning("전원 승인된 탈퇴를 이어서 지운다 elder_id=%s", elder_id)
            delete_elder_now(elder_id)
            return None
        return request

    def withdrawal_view(request: WithdrawalRequest, guardians: list[int]) -> dict:
        return {
            "status": "rejected" if request.rejected else "waiting",
            "requested_at": iso_kst(request.requested_at),
            "expires_at": iso_kst(request.requested_at + WITHDRAWAL_TTL_SECONDS),
            "approved": len(request.approved_by & set(guardians)),
            "total": len(guardians),
        }

    @app.post("/v1/me/withdrawal")
    @guarded
    def request_withdrawal(body: ElderWithdrawRequest, authorization: str | None = Header(default=None)) -> JSONResponse:
        """어르신 탈퇴 요청. 보호자가 있으면 요청을 만들고 보호자에게 알린다(202). 보호자가 모두 승인하면 탈퇴된다.
        보호자가 없는 어르신(연결 전)은 바로 탈퇴한다(200). 이미 열린 요청이 있으면 그대로 돌려준다."""
        elder_id = elder_id_of(authorization)
        if data.elders.get(elder_id) is None:
            raise HTTPException(status_code=401, detail=NEED_KEY)
        guardians = data.elders.guardians_of(elder_id)
        if not guardians:
            delete_elder_now(elder_id)
            return JSONResponse(status_code=200, content={"status": "deleted"})
        request = live_withdrawal(elder_id)
        if request is None or request.rejected:
            request = data.withdrawals.open(elder_id, data.wall_clock())
            logger.info("어르신이 탈퇴를 요청했다 elder_id=%s 보호자=%s명", elder_id, len(guardians))
            notify = getattr(data.notifier, "notify_withdrawal", None)
            if notify is not None:
                for guardian_id in guardians:
                    try:
                        notify(guardian_id, elder_id)
                    except Exception:
                        logger.exception("탈퇴 요청 푸시를 보내지 못했다 guardian_id=%s", guardian_id)
        return JSONResponse(status_code=202, content=withdrawal_view(request, guardians))

    @app.get("/v1/me/withdrawal")
    @guarded
    def my_withdrawal(authorization: str | None = Header(default=None)) -> dict:
        elder_id = elder_id_of(authorization)
        request = live_withdrawal(elder_id)
        if request is None:
            return {"status": "none"}
        return withdrawal_view(request, data.elders.guardians_of(elder_id))

    @app.delete("/v1/me/withdrawal")
    @guarded
    def cancel_withdrawal(authorization: str | None = Header(default=None)) -> Response:
        """어르신이 탈퇴 요청을 취소한다(거절된 요청을 치우는 데도 쓴다)."""
        elder_id = elder_id_of(authorization)
        if not data.withdrawals.cancel(elder_id):
            current = data.withdrawals.get(elder_id)
            if current is not None and current.locked:
                # 보호자가 모두 승인했다 — 이제 취소할 수 없고 탈퇴가 이어진다.
                raise HTTPException(status_code=409, detail=WITHDRAWAL_LOCKED)
        return Response(status_code=204)

    @app.get("/v1/guardian/withdrawals")
    @guarded
    def guardian_withdrawals(authorization: str | None = Header(default=None)) -> dict:
        """내 어르신들의 열린 탈퇴 요청(거절된 것은 빼고)."""
        guardian_id = guardian_id_of(authorization)
        items = []
        for ref in data.elders.elders_of(guardian_id):
            request = live_withdrawal(ref.elder_id)
            if request is None or request.rejected:
                continue
            view = withdrawal_view(request, data.elders.guardians_of(ref.elder_id))
            items.append(
                {
                    "elder_id": ref.elder_id,
                    "request_id": request.request_id,
                    "name": ref.name,
                    "requested_at": view["requested_at"],
                    "expires_at": view["expires_at"],
                    "approved": view["approved"],
                    "total": view["total"],
                    "approved_by_me": guardian_id in request.approved_by,
                }
            )
        return {"withdrawals": items}

    @app.post("/v1/elders/{elder_id}/withdrawal/approve")
    @guarded
    def approve_withdrawal(
        body: WithdrawalDecision,
        elder_id: int = Path(ge=1, le=MAX_ELDER_ID),
        authorization: str | None = Header(default=None),
    ) -> dict:
        """탈퇴 요청을 승인한다(보호자가 본 요청의 번호와 함께). 보호자가 모두 승인하면 어르신이 지워진다."""
        guardian_id = active_guardian_id_of(authorization)
        owned_elder(guardian_id, elder_id)
        if live_withdrawal(elder_id) is None:
            raise HTTPException(status_code=404, detail=NO_WITHDRAWAL)
        request = data.withdrawals.approve(elder_id, guardian_id, body.request_id)
        if request is None:
            raise HTTPException(status_code=404, detail=NO_WITHDRAWAL)
        guardians = data.elders.guardians_of(elder_id)
        logger.info(
            "탈퇴 요청을 승인했다 elder_id=%s guardian_id=%s 승인=%s/%s",
            elder_id,
            guardian_id,
            len(request.approved_by & set(guardians)),
            len(guardians),
        )
        if guardians and set(guardians) <= request.approved_by:
            # 마지막 승인이다. 이 번호의 요청을 잠가야만 지운다 — 승인과 삭제 사이에 어르신이 취소하고 다시 요청했다면
            # 잠기지 않고(번호가 다르다), 옛 승인으로 새 요청의 어르신이 지워지지 않는다.
            if not data.withdrawals.lock(elder_id, request.request_id, data.wall_clock()):
                raise HTTPException(status_code=404, detail=NO_WITHDRAWAL)
            delete_elder_now(elder_id)
            return {"status": "deleted"}
        return withdrawal_view(request, guardians)

    @app.post("/v1/elders/{elder_id}/withdrawal/reject")
    @guarded
    def reject_withdrawal(
        body: WithdrawalDecision,
        elder_id: int = Path(ge=1, le=MAX_ELDER_ID),
        authorization: str | None = Header(default=None),
    ) -> Response:
        """탈퇴 요청을 거절한다. 어르신 앱에 거절됐다고 보이고, 어르신은 나중에 다시 요청할 수 있다."""
        guardian_id = active_guardian_id_of(authorization)
        owned_elder(guardian_id, elder_id)
        if live_withdrawal(elder_id) is None or not data.withdrawals.reject(
            elder_id, data.wall_clock(), body.request_id
        ):
            raise HTTPException(status_code=404, detail=NO_WITHDRAWAL)
        logger.info("탈퇴 요청을 거절했다 elder_id=%s guardian_id=%s", elder_id, guardian_id)
        return Response(status_code=204)

    # ------------------------------------------------ 보호자 코드로 어르신 가입

    @app.post("/v1/guardian/invite")
    @guarded
    def issue_invite(authorization: str | None = Header(default=None)) -> dict:
        guardian_id = active_guardian_id_of(authorization)
        code = new_invite_code()
        data.invites.issue(guardian_id, hash_invite_code(code))
        # 코드 원문은 응답에만 있다. 로그에는 발급 사실만 남긴다.
        logger.info("보호자 개인 코드를 발급했다 guardian_id=%s", guardian_id)
        return {"code": code}

    # ------------------------------------------------ 어르신 먼저 가입 + 연결 코드

    @app.post("/v1/elders/signup")
    @guarded
    def elder_signup(body: ElderSignupRequest) -> dict:
        if not body.agreed:
            raise HTTPException(status_code=400, detail=NEEDS_AGREEMENT)
        if data.elder_signup_attempts.blocked():
            raise HTTPException(status_code=429, detail=TRY_LATER)
        data.elder_signup_attempts.record_failure()  # 성공도 센다 — 인증 없는 주소라 행을 마구 만드는 것을 늦춘다
        try:
            elder_id = data.elders.create_unlinked(name=body.name.strip(), phone=body.phone.strip())
        except PhoneTaken:
            # 이 주소는 코드가 없어 번호 중복을 숨길 방법이 없다. 시도 한도가 대량 조회를 늦춘다.
            logger.warning("어르신 가입 실패")
            raise HTTPException(status_code=409, detail=PHONE_USED)
        # 가입 동의 문구 한 줄이 전화와 통화 내용 공유를 함께 담는다. 전화 동의(consent_at)는 연결 때 보호자 확인이 채운다.
        new = generate_elder_key()
        try:
            data.content.agree_share(elder_id)
            data.elder_keys.replace(elder_id=elder_id, key_prefix=new.key_prefix, key_hash=new.key_hash)
            link_code = fresh_link_code(elder_id)
        except Exception:
            # 행만 남고 열쇠가 없으면 번호가 막히고 연결 코드도 못 받는다 — 방금 만든 행을 거둬 다시 가입하게 한다.
            try:
                data.elders.discard_unlinked(elder_id)
            except Exception:
                logger.exception("가입 실패 뒤 정리도 실패했다 elder_id=%s", elder_id)
            else:
                logger.warning("어르신 가입 도중 저장소 오류로 가입을 되돌렸다 elder_id=%s", elder_id)
            raise
        logger.info("연결 전 어르신이 가입했다 elder_id=%s key=%s", elder_id, new.key_prefix)
        return {"elder_key": new.key, "status": STATUS_UNLINKED, "link_code": link_code}

    def fresh_link_code(elder_id: int) -> str:
        """새 고정 코드를 정한다(이전 코드는 무효). 지문이 겹치면 다시 뽑는다."""
        for _ in range(LINK_CODE_RETRIES):
            code = new_invite_code()
            try:
                data.links.issue(elder_id, hash_invite_code(code), code)
            except CodeCollision:
                continue
            return code
        raise HTTPException(status_code=503, detail=UNAVAILABLE)

    @app.get("/v1/me/link-code")
    @guarded
    def show_link_code(authorization: str | None = Header(default=None)) -> dict:
        """내 고정 연결 코드. 언제든 다시 본다(연결된 뒤에도). 아직 없으면 지금 정한다."""
        elder_id = elder_id_of(authorization)
        if data.elders.get(elder_id) is None:
            raise HTTPException(status_code=401, detail=NEED_KEY)
        code = data.links.code_of(elder_id)
        if code is None:
            code = fresh_link_code(elder_id)
            logger.info("연결 코드를 정했다 elder_id=%s", elder_id)
        return {"code": code}

    @app.post("/v1/elders/login")
    @guarded
    def elder_login(body: ElderLoginRequest) -> dict:
        """새 폰의 어르신 로그인. 보호자가 번호를 고쳐 둔 번호만, 24시간 안에, 딱 한 번 열쇠를 받는다."""
        if data.elder_login_attempts.blocked():
            raise HTTPException(status_code=429, detail=TRY_LATER)
        data.elder_login_attempts.record_failure()  # 성공도 센다 — 번호를 찍어 보는 것을 늦춘다
        elder_id = data.elders.claim_new_phone(body.phone.strip(), data.wall_clock())
        if elder_id is None:
            logger.warning("새 폰 로그인 실패")
            raise HTTPException(status_code=401, detail=BAD_ELDER_LOGIN)
        new = generate_elder_key()
        data.elder_keys.replace(elder_id=elder_id, key_prefix=new.key_prefix, key_hash=new.key_hash)
        access = data.elders.get(elder_id)
        logger.info("어르신 새 폰이 로그인했다 elder_id=%s key=%s", elder_id, new.key_prefix)
        return {"elder_key": new.key, "elder_name": "" if access is None else access.name}

    @app.post("/v1/me/link-code")
    @guarded
    def renew_link_code(authorization: str | None = Header(default=None)) -> dict:
        """새 고정 코드를 만든다. 코드가 새어 나갔을 때 쓴다 — 이전 코드는 바로 못 쓰고, 이미 연결된 보호자는 그대로다."""
        elder_id = elder_id_of(authorization)
        if data.elders.get(elder_id) is None:
            raise HTTPException(status_code=401, detail=NEED_KEY)
        code = fresh_link_code(elder_id)
        # 코드 원문은 응답에만 있다. 로그에는 바꾼 사실만 남긴다.
        logger.info("연결 코드를 새로 만들었다 elder_id=%s", elder_id)
        return {"code": code}

    def elder_for_link_code(code: str) -> int:
        """코드의 어르신. 틀린 코드는 401이고 한도로 센다. 고정 코드라 연결에 써도 코드는 그대로다."""
        if data.link_attempts.blocked():
            raise HTTPException(status_code=429, detail=TRY_LATER)
        code_hash = hash_invite_code(code)
        elder_id = data.links.find(code_hash)
        if elder_id is None:
            data.link_attempts.record_failure()
            logger.warning("연결 실패")
            raise HTTPException(status_code=401, detail=BAD_LINK)
        return elder_id

    @app.post("/v1/guardian/link/preview")
    @guarded
    def preview_link(body: LinkRequest, authorization: str | None = Header(default=None)) -> dict:
        active_guardian_id_of(authorization)
        elder_id = elder_for_link_code(body.code)
        access = data.elders.get(elder_id)
        phone = data.elders.phone_of(elder_id)
        if access is None or phone is None or access.guardian_id is not None:
            data.link_attempts.record_failure()
            logger.warning("연결 실패")
            raise HTTPException(status_code=401, detail=BAD_LINK)
        return {"name": access.name, "phone_masked": mask_phone(phone)}

    @app.post("/v1/guardian/link")
    @guarded
    def link_elder(body: LinkRequest, authorization: str | None = Header(default=None)) -> dict:
        guardian_id = active_guardian_id_of(authorization)
        # 코드를 쓰기 전에 확인한다 — 한도에 걸린 보호자가 코드를 태우지 않게.
        if len(data.elders.elders_of(guardian_id)) >= MAX_ELDERS_PER_GUARDIAN:
            raise HTTPException(status_code=409, detail=TOO_MANY_ELDERS)
        elder_id = elder_for_link_code(body.code)
        # 보호자가 이 확인을 누르는 것이 승인이다: 연결과 전화 동의(consent_at)가 함께 기록된다.
        if not data.elders.link(elder_id, guardian_id):
            # 그 사이 다른 경로로 이미 연결된 어르신이다.
            data.link_attempts.record_failure()
            logger.warning("연결 실패")
            raise HTTPException(status_code=401, detail=BAD_LINK)
        access = data.elders.get(elder_id)
        logger.info("어르신을 연결했다 elder_id=%s guardian_id=%s", elder_id, guardian_id)
        return {"elder_id": elder_id, "name": "" if access is None else access.name, "status": "active"}

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
        except (PhoneTaken, PendingLimit):
            # 등록된 번호인지, 대기 한도인지 알려 주지 않는다 — 틀린 코드와 같은 응답이고 같은 한도로 센다.
            # 구분해 주면 코드를 가진 사람이 어르신 번호가 등록돼 있는지 무제한으로 알아낼 수 있다.
            data.signup_limiter.record_failure()
            logger.warning("가입 실패")
            raise HTTPException(status_code=401, detail=BAD_SIGNUP)
        # 가입 동의 문구 한 줄이 전화와 통화 내용 공유를 함께 담는다.
        data.content.agree_share(elder_id)
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
        guardian_id = active_guardian_id_of(authorization)
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
        return {
            "status": access.status,
            "name": access.name,
            "share_agreed": data.content.share_agreed(elder_id),
        }

    # ------------------------------------------------ 통화 요약·원문 (어르신이 공유에 동의한 경우만)

    @app.post("/v1/me/share-consent")
    @guarded
    def share_consent(authorization: str | None = Header(default=None)) -> dict:
        elder_id = elder_id_of(authorization)
        data.content.agree_share(elder_id)
        logger.info("통화 내용 공유에 동의했다 elder_id=%s", elder_id)
        return {"share_agreed": True}

    @app.get("/v1/elders/{elder_id}/calls")
    @guarded
    def elder_calls(
        elder_id: int = Path(ge=1, le=MAX_ELDER_ID),
        limit: int = Query(default=30, ge=1, le=100),
        authorization: str | None = Header(default=None),
    ) -> dict:
        guardian_id = guardian_id_of(authorization)
        owned_elder(guardian_id, elder_id)
        if not data.content.share_agreed(elder_id):
            return {"share_agreed": False, "calls": []}
        lines = data.reports.call_lines(elder_id, limit)
        ids = [line.call_id for line in lines]
        summaries = data.content.summaries(ids)
        with_turns = data.content.calls_with_turns(ids)
        try:
            medication = data.content.medication(ids)
        except Exception:
            # 약 복용 값은 덤이다. 조회가 터져도 요약·원문 목록은 막지 않는다.
            logger.exception("약 복용 확인 조회에 실패했다")
            medication = {}
        return {
            "share_agreed": True,
            "calls": [
                {
                    "call_id": line.call_id,
                    "started_at": iso_kst(line.started_at),
                    "duration_s": line.duration_s,
                    "status": line.status,
                    "summary": summaries.get(line.call_id),
                    "has_turns": line.call_id in with_turns,
                    "medication": medication.get(line.call_id),
                }
                for line in lines
            ],
        }

    @app.get("/v1/elders/{elder_id}/mentions")
    @guarded
    def elder_mentions(
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
        if not data.content.share_agreed(elder_id):
            return {"share_agreed": False, "week_start": week.isoformat(), "categories": []}
        lo, hi = week_bounds(week)
        lines = sorted(
            (l for l in data.reports.call_lines(elder_id, MENTION_CALL_FETCH_LIMIT) if lo <= l.started_at < hi),
            key=lambda l: l.started_at,
            reverse=True,
        )
        try:
            found = data.content.mentions([line.call_id for line in lines])
        except Exception:
            # 언급은 덤이다. 조회가 터져도 화면은 막지 않는다(표가 아직 없는 배포 순서 포함).
            logger.exception("건강·기분 언급 조회에 실패했다")
            found = {}
        categories = []
        for category in MENTION_CATEGORIES:
            counts = {"bad": 0, "ok": 0, "good": 0}
            items = []
            for line in lines:  # 최신 통화부터
                for mention in found.get(line.call_id, []):
                    if mention.category != category:
                        continue
                    counts[mention.said] += 1
                    items.append(
                        {
                            "call_id": line.call_id,
                            "date": iso_kst(line.started_at),
                            "said": mention.said,
                            "quote": mention.quote,
                        }
                    )
            categories.append(
                {
                    "category": category,
                    "negative": counts["bad"],
                    "neutral": counts["ok"],
                    "positive": counts["good"],
                    "items": items,
                }
            )
        return {"share_agreed": True, "week_start": week.isoformat(), "categories": categories}

    @app.get("/v1/calls/{call_id}/turns")
    @guarded
    def call_turns(
        call_id: int = Path(ge=1, le=MAX_ELDER_ID),
        authorization: str | None = Header(default=None),
    ) -> dict:
        guardian_id = guardian_id_of(authorization)
        elder_id = data.content.elder_of_call(call_id)
        access = None if elder_id is None else data.elders.get(elder_id)
        # 없는 통화, 남의 통화, 동의 전은 모두 같은 404다 — 존재 여부를 알려 주지 않는다.
        if (
            access is None
            or access.guardian_id != guardian_id
            or not data.content.share_agreed(elder_id)
        ):
            raise HTTPException(status_code=404, detail=NO_CALL)
        data.content.record_view(call_id, guardian_id)
        # 내용은 로그에 남기지 않는다. 열람 사실만.
        logger.info("원문을 열람했다 call_id=%s guardian_id=%s", call_id, guardian_id)
        return {
            "call_id": call_id,
            "turns": [{"speaker": t.speaker, "text": t.text} for t in data.content.turns(call_id)],
        }
