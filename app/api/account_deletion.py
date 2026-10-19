"""탈퇴·내 정보 삭제 — 보호자와 어르신의 계정과 딸린 데이터를 지운다 (설계: 탈퇴·내 정보 삭제).

앱 주소(`DELETE /v1/guardian/me`, `DELETE /v1/me` — app_data.py)와 운영 도구(`guardian delete`,
`elder delete` — app/admin.py)가 **같은 순서**로 지우도록 순서를 여기 한 곳에 둔다.

**보호자가 탈퇴해도 어르신은 지우지 않는다.** DB의 `elders.guardian_id`가 `ON DELETE CASCADE`라 보호자 행을
그냥 지우면 연결된 어르신과 그 통화·연락처까지 지워진다. 그래서 먼저 어르신을 연결 전(보호자 없음, 전화 동의
없음 — 안부 전화가 멈춘다)으로 돌리고, 그 보호자가 내준 안 쓴 연결 코드(어르신 폰 잇기)를 지우고, 열쇠·폰 등록·
개인 코드·알림을 지운 뒤 계정을 지운다. Postgres의 계정 삭제는 어르신이 하나라도 남아 있으면 지우지 않는다 —
그 사이 다른 요청이 어르신을 붙였으면 한 번 더 풀고(연결 코드도 지우고) 지운다.

**어르신 탈퇴는 녹음 키부터 읽는다.** 통화 행이 지워지면 녹음의 키를 다시 찾을 수 없다. 키를 읽어 서버 디스크
(recordings/)의 파일을 지우고, S3에서 최선으로 지우고(실패해도 계속한다 — 남은 녹음은 버킷의 30일 수명 규칙이
지운다), 그다음 어르신 행을 지운다. 통화·점수·요약·언급·연락처·열쇠·코드는 Postgres의 CASCADE가 같이 지운다.

**메모리 저장소에는 CASCADE가 없다.** 메모리 모드와 시험에서도 결과가 같도록 저장소마다 지우는 메서드를
명시적으로 부른다. Postgres에서는 DB가 이미 지운 뒤라 아무것도 지우지 않는다.

로그에는 번호와 개수만 남긴다. 이름·전화번호·이메일·비밀번호·녹음 키는 남기지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.api.elder_directory import ElderDirectory
from app.api.guardian_accounts import GuardianAccounts
from app.api.guardian_auth import GuardianKeyStore
from app.api.pairing import PairingStore
from app.archiver import MARKER_SUFFIX
from app.recordings import RecordingDeleter

logger = logging.getLogger(__name__)


def withdraw_guardian(
    guardian_id: int,
    *,
    elders: ElderDirectory,
    accounts: GuardianAccounts,
    keys: GuardianKeyStore,
    pairings: PairingStore | None,
    devices: Any = None,
    invites: Any = None,
    alerts: Any = None,
) -> int:
    """보호자를 지운다: 어르신 연결 해제(+ 그 어르신들의 안 쓴 연결 코드) → 열쇠 폐기 → 폰 등록 → 개인 코드 → 알림
    → 계정. 연결을 푼 어르신 수.

    계정이 끝내 지워지지 않으면(어르신이 계속 붙어 있으면) RuntimeError — 성공으로 답하지 않는다.
    연결 코드(6자리)는 그 보호자가 어르신 폰을 잇게 내준 것이라 남겨 두면 탈퇴 뒤에도 코드를 가진 사람이 어르신
    열쇠를 받는다 — 어르신이 남으므로 CASCADE도 지우지 않는다. pairings는 그래서 늘 넘긴다(None은 시험용).
    devices·invites·alerts는 메모리 저장소의 CASCADE 대신이다(Postgres에서는 계정 삭제가 같이 지운다).
    """
    # 연결 해제가 먼저다 — 계정 삭제의 CASCADE가 어르신을 지우지 않게.
    detached = _detach(guardian_id, elders, pairings)
    keys.revoke_all(guardian_id)
    if devices is not None:
        devices.remove_for_guardian(guardian_id)
    if invites is not None:
        invites.remove_for_guardian(guardian_id)
    if alerts is not None:
        alerts.remove_for_guardian(guardian_id)
    if not accounts.delete(guardian_id):
        # Postgres는 어르신이 남아 있으면 지우지 않는다. 열쇠와 코드가 막히기 전에 들어온 요청이 그 사이 어르신을
        # 붙였을 수 있다 — 한 번 더 풀고(그 어르신들의 연결 코드도 지우고) 다시 지운다.
        detached += _detach(guardian_id, elders, pairings)
        if not accounts.delete(guardian_id) and accounts.profile(guardian_id) is not None:
            raise RuntimeError("보호자 계정을 지우지 못했다 — 연결된 어르신이 남아 있다")
    return detached


def _detach(guardian_id: int, elders: ElderDirectory, pairings: PairingStore | None) -> int:
    elder_ids = elders.detach_all_from(guardian_id)
    if pairings is not None and elder_ids:
        pairings.remove_unused_for(elder_ids)
    return len(elder_ids)


@dataclass(frozen=True)
class ElderWithdrawal:
    deleted: bool  # 어르신 행을 지웠는가(그 사이 이미 지워졌으면 False)
    recordings: int  # 지우려 한 녹음 수
    failed: int  # S3에서 지우지 못한 녹음 수(삭제기가 없거나 오류면 전부)
    local_removed: int = 0  # 서버 디스크(recordings/)에서 지운 녹음 파일 수


def withdraw_elder(
    elder_id: int,
    *,
    elders: ElderDirectory,
    recording_deleter: RecordingDeleter | None,
    recordings_dir: Path | None = None,
    elder_keys: Any = None,
    contacts: Any = None,
    content: Any = None,
    reports: Any = None,
    alerts: Any = None,
) -> ElderWithdrawal:
    """어르신을 지운다: 녹음 키 읽기 → 서버 디스크의 녹음 파일 → S3 녹음 최선 삭제 → 어르신 행 삭제 → (메모리 저장소 정리).

    보관기(app/archiver.py)는 올린 녹음을 24시간, 못 올린 녹음을 최대 30일 recordings/에 둔다. 디스크를 S3보다 먼저
    지운다 — 남겨 두면 아직 안 올린 녹음을 보관기가 탈퇴 뒤에 S3로 올린다.
    elder_keys·contacts·content·reports·alerts는 메모리 저장소의 CASCADE 대신이다. 어르신 행이 지워진 뒤라
    실패해도 탈퇴를 되돌리지 않고 남기기만 한다(Postgres에서는 이미 비어 있다).
    """
    keys = elders.audio_keys_of(elder_id)
    local_removed = _delete_local_recordings(elder_id, keys, recordings_dir)
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
    return ElderWithdrawal(deleted=deleted, recordings=len(keys), failed=failed, local_removed=local_removed)


def _is_plain_file_name(key: str) -> bool:
    """폴더 밖이나 하위 폴더를 가리키지 않는 파일 이름 하나인가. 녹음 키는 보관기가 쓴 파일 이름 그대로다."""
    return bool(key) and key not in (".", "..") and Path(key).name == key


def _delete_local_recordings(elder_id: int, keys: list[str], directory: Path | None) -> int:
    """recordings/<키>와 그 '올림' 표시(<키>.uploaded)를 최선으로 지운다. 지운 녹음 파일 수. 예외를 내지 않는다."""
    if directory is None or not keys:
        return 0
    removed = skipped = 0
    for key in keys:
        if not _is_plain_file_name(key):
            skipped += 1
            continue
        for path in (directory / key, directory / (key + MARKER_SUFFIX)):
            try:
                if path.is_file():
                    path.unlink()
                    removed += path.name == key
            except Exception as exc:
                # 파일 이름(키)은 남기지 않는다 — 어르신 번호와 통화 시각이 들어 있다.
                logger.warning(
                    "서버의 녹음 파일을 지우지 못했다 elder_id=%s 오류=%s — 보관기의 30일 삭제에 맡긴다",
                    elder_id,
                    type(exc).__name__,
                )
    if skipped:
        logger.warning("파일 이름이 아닌 녹음 키는 서버 디스크에서 건너뛰었다 elder_id=%s 수=%d", elder_id, skipped)
    return removed


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
