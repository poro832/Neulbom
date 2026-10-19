"""탈퇴·내 정보 삭제 — 보호자와 어르신의 계정과 딸린 데이터를 지운다 (설계: 탈퇴·내 정보 삭제).

앱 주소(`DELETE /v1/guardian/me`, `DELETE /v1/me` — app_data.py)와 운영 도구(`guardian delete`,
`elder delete` — app/admin.py)가 **같은 순서**로 지우도록 순서를 여기 한 곳에 둔다.

**보호자가 탈퇴해도 어르신은 지우지 않는다.** DB의 `elders.guardian_id`가 `ON DELETE CASCADE`라 보호자 행을
그냥 지우면 연결된 어르신과 그 통화·연락처까지 지워진다. 그래서 먼저 어르신을 연결 전(보호자 없음, 전화 동의
없음 — 안부 전화가 멈춘다)으로 돌리고, 열쇠·폰 등록·개인 코드·알림을 지운 뒤 계정을 지운다. Postgres의 계정
삭제는 어르신이 하나라도 남아 있으면 지우지 않는다 — 그 사이 다른 요청이 어르신을 붙였으면 한 번 더 풀고 지운다.

**어르신 탈퇴는 녹음 키부터 읽는다.** 통화 행이 지워지면 S3 녹음의 키를 다시 찾을 수 없다. 키를 읽어 S3에서
최선으로 지우고(실패해도 계속한다 — 남은 녹음은 버킷의 30일 수명 규칙이 지운다), 그다음 어르신 행을 지운다.
통화·점수·요약·언급·연락처·열쇠·코드는 Postgres의 CASCADE가 같이 지운다.

**메모리 저장소에는 CASCADE가 없다.** 메모리 모드와 시험에서도 결과가 같도록 저장소마다 지우는 메서드를
명시적으로 부른다. Postgres에서는 DB가 이미 지운 뒤라 아무것도 지우지 않는다.

로그에는 번호와 개수만 남긴다. 이름·전화번호·이메일·비밀번호·녹음 키는 남기지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.api.elder_directory import ElderDirectory
from app.api.guardian_accounts import GuardianAccounts
from app.api.guardian_auth import GuardianKeyStore
from app.recordings import RecordingDeleter

logger = logging.getLogger(__name__)


def withdraw_guardian(
    guardian_id: int,
    *,
    elders: ElderDirectory,
    accounts: GuardianAccounts,
    keys: GuardianKeyStore,
    devices: Any = None,
    invites: Any = None,
    alerts: Any = None,
) -> int:
    """보호자를 지운다: 어르신 연결 해제 → 열쇠 폐기 → 폰 등록 → 개인 코드 → 알림 → 계정. 연결을 푼 어르신 수.

    계정이 끝내 지워지지 않으면(어르신이 계속 붙어 있으면) RuntimeError — 성공으로 답하지 않는다.
    devices·invites·alerts는 메모리 저장소의 CASCADE 대신이다(Postgres에서는 계정 삭제가 같이 지운다).
    """
    detached = elders.detach_all_from(guardian_id)  # 이게 먼저다 — 계정 삭제의 CASCADE가 어르신을 지우지 않게
    keys.revoke_all(guardian_id)
    if devices is not None:
        devices.remove_for_guardian(guardian_id)
    if invites is not None:
        invites.remove_for_guardian(guardian_id)
    if alerts is not None:
        alerts.remove_for_guardian(guardian_id)
    if not accounts.delete(guardian_id):
        # Postgres는 어르신이 남아 있으면 지우지 않는다. 열쇠와 코드가 막히기 전에 들어온 요청이 그 사이 어르신을
        # 붙였을 수 있다 — 한 번 더 풀고 다시 지운다.
        detached += elders.detach_all_from(guardian_id)
        if not accounts.delete(guardian_id) and accounts.profile(guardian_id) is not None:
            raise RuntimeError("보호자 계정을 지우지 못했다 — 연결된 어르신이 남아 있다")
    return detached


@dataclass(frozen=True)
class ElderWithdrawal:
    deleted: bool  # 어르신 행을 지웠는가(그 사이 이미 지워졌으면 False)
    recordings: int  # 지우려 한 녹음 수
    failed: int  # 지우지 못한 녹음 수(삭제기가 없거나 오류면 전부)


def withdraw_elder(
    elder_id: int,
    *,
    elders: ElderDirectory,
    recording_deleter: RecordingDeleter | None,
    elder_keys: Any = None,
    contacts: Any = None,
    content: Any = None,
    reports: Any = None,
    alerts: Any = None,
) -> ElderWithdrawal:
    """어르신을 지운다: 녹음 키 읽기 → S3 녹음 최선 삭제 → 어르신 행 삭제 → (메모리 저장소 정리).

    elder_keys·contacts·content·reports·alerts는 메모리 저장소의 CASCADE 대신이다. 어르신 행이 지워진 뒤라
    실패해도 탈퇴를 되돌리지 않고 남기기만 한다(Postgres에서는 이미 비어 있다).
    """
    keys = elders.audio_keys_of(elder_id)
    failed = _delete_recordings(elder_id, keys, recording_deleter)
    deleted = elders.delete_elder(elder_id)
    for name, store in (
        ("열쇠", elder_keys),
        ("연락처", contacts),
        ("통화 내용", content),
        ("통화", reports),
        ("알림", alerts),
    ):
        if store is None:
            continue
        try:
            store.remove_for_elder(elder_id)
        except Exception:
            logger.exception("탈퇴한 어르신의 %s 정리에 실패했다 elder_id=%s", name, elder_id)
    return ElderWithdrawal(deleted=deleted, recordings=len(keys), failed=failed)


def _delete_recordings(elder_id: int, keys: list[str], deleter: RecordingDeleter | None) -> int:
    """지우지 못한 수. 예외를 내지 않는다 — 녹음 때문에 탈퇴가 멈추면 안 된다."""
    if not keys:
        return 0
    if deleter is None:
        logger.warning(
            "녹음 버킷 설정(RECORDINGS_BUCKET)이 없어 S3 녹음을 지우지 않았다 elder_id=%s 녹음=%d개 "
            "— 버킷의 30일 수명 규칙에 맡긴다",
            elder_id,
            len(keys),
        )
        return len(keys)
    try:
        failed = deleter.delete_many(keys)
    except Exception as exc:
        # 오류 내용에 키가 들어 있을 수 있어 종류만 남긴다.
        logger.error(
            "S3 녹음 삭제 중 오류 — 탈퇴는 계속한다 elder_id=%s 녹음=%d개 오류=%s", elder_id, len(keys), type(exc).__name__
        )
        return len(keys)
    if failed:
        logger.warning(
            "S3 녹음 일부를 지우지 못했다 elder_id=%s 실패=%d개 — 버킷의 30일 수명 규칙에 맡긴다", elder_id, failed
        )
    return failed
