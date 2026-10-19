"""운영 도구 — `python -m app.admin ...` (서버에서 사람이 실행한다).

보호자 앱 화면이 생기기 전까지 보호자와 열쇠를 사람이 만든다.

    key issue --guardian-id N --label "시연 폰"   열쇠를 만들고 **한 번만** 보여 준다
    key list                                      앞 12글자, 이름표, 날짜 (열쇠와 지문은 안 나온다)
    key revoke --prefix nlb_xxxxxxxx              열쇠를 폐기한다 (다음 요청부터 막힌다)
    guardian add --name ... --phone ...           열쇠 전용 보호자를 만든다
    guardian pending                              운영자 확인을 기다리는 가입자 목록
    guardian activate N                           가입자를 연다 (어르신 등록·승인이 가능해진다)
    guardian verify N   보호자의 이메일을 수동으로 인증한 것으로 기록한다 (Firebase를 못 쓰는 사람용)
    check                                         서버 반영 점검 — DB 표·칸, 설정, 푸시 열쇠(비밀 값은 출력하지 않는다)
    guardian set-login N --email ...              보호자 N에게 이메일과 비밀번호를 붙인다 (비밀번호는 입력창에서)
    guardian delete N --yes                       보호자 N을 지운다 — 어르신은 연결 전으로 돌리고(지우지 않는다) 계정·열쇠·폰 등록·개인 코드·알림을 지운다
    elder assign --elder-id N --guardian-id M     어르신을 그 보호자에게 옮긴다
    elder delete N --yes                          어르신 N을 지운다 — 녹음(S3)을 최선으로 지우고 통화·점수·요약·언급·연락처·열쇠·코드를 지운다

**동의(`consent_at`)는 여기서 채우지 않는다.** 동의는 사람이 받는 것이다.
**지우기(`delete`)는 `--yes`가 있어야 한다.** 없으면 무엇이 지워지는지 보여 주기만 하고 아무것도 지우지 않는다.
되돌릴 수 없다. 앱의 탈퇴(app/api/account_deletion.py)와 같은 순서로 지운다.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from app.api.account_deletion import withdraw_elder, withdraw_guardian
from app.api.db import connect, database_url
from app.api.devices import DeviceStore
from app.api.elder_directory import DirectoryAdmin
from app.api.guardian_accounts import EmailTaken, GuardianAccounts
from app.api.guardian_auth import AmbiguousPrefix, GuardianKeyStore, generate_key
from app.api.invites import InviteStore
from app.api.pairing import PairingStore
from app.api.passwords import hash_password
from app.recordings import RecordingDeleter, recording_deleter_from_env
from app.scheduler import KST

MIN_PASSWORD = 8


def _when(epoch: float | None) -> str:
    if epoch is None:
        return "-"
    return datetime.fromtimestamp(epoch, KST).strftime("%Y-%m-%d %H:%M")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.admin", description=__doc__)
    groups = parser.add_subparsers(dest="group", required=True)

    key = groups.add_parser("key", help="보호자 열쇠").add_subparsers(dest="action", required=True)
    issue = key.add_parser("issue", help="열쇠를 만든다 (전체 열쇠는 이때 한 번만 보인다)")
    issue.add_argument("--guardian-id", type=int, required=True)
    issue.add_argument("--label", required=True)
    key.add_parser("list", help="열쇠 목록")
    revoke = key.add_parser("revoke", help="열쇠를 폐기한다")
    revoke.add_argument("--prefix", required=True, help="예: nlb_Kf3a9b2c")

    guardian = groups.add_parser("guardian", help="보호자").add_subparsers(dest="action", required=True)
    add = guardian.add_parser("add", help="열쇠 전용 보호자를 만든다")
    add.add_argument("--name", required=True)
    add.add_argument("--phone", required=True)

    guardian.add_parser("pending", help="운영자 확인을 기다리는 보호자")
    activate = guardian.add_parser("activate", help="보호자를 연다")
    activate.add_argument("guardian_id", type=int)
    verify = guardian.add_parser("verify", help="보호자의 이메일 인증을 수동으로 기록한다")
    verify.add_argument("guardian_id", type=int)
    set_login = guardian.add_parser("set-login", help="보호자에게 이메일 로그인을 붙인다")
    set_login.add_argument("guardian_id", type=int)
    set_login.add_argument("--email", required=True)
    delete_guardian = guardian.add_parser(
        "delete", help="보호자를 지운다(어르신은 연결 전으로 돌린다, --yes가 있어야 지운다)"
    )
    delete_guardian.add_argument("guardian_id", type=int)
    delete_guardian.add_argument("--yes", action="store_true", help="정말 지운다(되돌릴 수 없다)")

    groups.add_parser("check", help="서버 반영 점검(DB 표·칸, 설정, 푸시 열쇠)")

    elder = groups.add_parser("elder", help="어르신").add_subparsers(dest="action", required=True)
    assign = elder.add_parser("assign", help="어르신을 보호자에게 옮긴다")
    assign.add_argument("--elder-id", type=int, required=True)
    assign.add_argument("--guardian-id", type=int, required=True)
    delete_elder = elder.add_parser(
        "delete", help="어르신과 그 통화·연락처·녹음을 지운다(--yes가 있어야 지운다)"
    )
    delete_elder.add_argument("elder_id", type=int)
    delete_elder.add_argument("--yes", action="store_true", help="정말 지운다(되돌릴 수 없다)")
    return parser


def run(
    argv: list[str],
    *,
    keys: GuardianKeyStore,
    directory: DirectoryAdmin,
    out: Callable[..., None] = print,
    err: Callable[..., None] | None = None,
    accounts: GuardianAccounts | None = None,
    read_password: Callable[[str], str] = getpass.getpass,
    pool=None,
    devices: DeviceStore | None = None,
    invites: InviteStore | None = None,
    recording_deleter: RecordingDeleter | None = None,
    pairings: PairingStore | None = None,
    recordings_dir: Path | None = None,
) -> int:
    err = err or (lambda text="": print(text, file=sys.stderr))
    args = build_parser().parse_args(argv)

    if args.group == "check":
        from app.ops_check import format_checks, run_checks

        lines, failed = format_checks(run_checks(pool))
        for line in lines:
            out(line)
        return 1 if failed else 0

    if (args.group, args.action) == ("key", "issue"):
        if not directory.guardian_exists(args.guardian_id):
            err(f"그런 보호자가 없다 — 보호자 번호 {args.guardian_id}. 먼저 `guardian add`로 만든다.")
            return 1
        new = generate_key()
        keys.add(
            guardian_id=args.guardian_id,
            label=args.label,
            key_prefix=new.key_prefix,
            key_hash=new.key_hash,
        )
        out("열쇠가 만들어졌다. 이 화면에서 한 번만 보인다 — 지금 복사할 것.")
        out("")
        out(f"  {new.key}")
        out("")
        out(f'보호자 {args.guardian_id} · 앞부분 {new.key_prefix} · 이름표 "{args.label}"')
        out("보호자에게는 메신저로 직접 전달한다. 공개 채널과 문서에는 올리지 않는다.")
        return 0

    if (args.group, args.action) == ("key", "list"):
        rows = keys.list_keys()
        if not rows:
            out("열쇠가 없다.")
            return 0
        out("앞부분        보호자  이름표              만든 날            마지막 사용        상태")
        for info in rows:
            state = "폐기됨 " + _when(info.revoked_at) if info.revoked_at else "사용 중"
            out(
                f"{info.key_prefix:<13} {info.guardian_id:<6} {info.label:<18} "
                f"{_when(info.created_at):<17} {_when(info.last_used_at):<17} {state}"
            )
        return 0

    if (args.group, args.action) == ("key", "revoke"):
        try:
            revoked = keys.revoke(args.prefix)
        except ValueError as exc:
            err(str(exc))
            return 1
        except AmbiguousPrefix:
            err(f"앞부분 {args.prefix}가 여러 열쇠와 겹친다 — 더 길게 써서 하나만 가리키게 한다.")
            return 1
        if revoked == 0:
            err(f"폐기할 열쇠가 없다 — {args.prefix}로 시작하는 사용 중인 열쇠가 없다.")
            return 1
        out(f"{args.prefix} 열쇠를 폐기했다. 다음 요청부터 막힌다.")
        return 0

    if (args.group, args.action) == ("guardian", "add"):
        guardian_id = directory.add_guardian(args.name, args.phone)
        out(f"보호자를 만들었다. 보호자 번호 {guardian_id}")
        out("이 보호자는 비밀번호 로그인이 되지 않는다(열쇠 전용). 열쇠는 `key issue`로 만든다.")
        return 0

    if (args.group, args.action) == ("guardian", "pending"):
        if accounts is None:
            err("계정 저장소가 없다.")
            return 1
        rows = accounts.pending()
        if not rows:
            out("확인을 기다리는 가입자가 없다.")
            return 0
        out("보호자  이름        이메일                         전화번호        이메일 인증")
        for a in rows:
            state = "이메일 인증됨" if a.email_verified else "이메일 인증 대기"
            out(f"{a.guardian_id:<7} {a.name:<10} {a.email:<30} {a.phone:<15} {state}")
        out("전화번호로 본인을 확인한 뒤 `guardian activate <번호>`로 연다.")
        out("이메일 인증이 대기면 `guardian verify <번호>`로 수동 인증을 기록할 수 있다.")
        return 0

    if (args.group, args.action) == ("guardian", "activate"):
        if accounts is None:
            err("계정 저장소가 없다.")
            return 1
        if not accounts.activate(args.guardian_id):
            err(f"그런 보호자가 없다 — 보호자 번호 {args.guardian_id}.")
            return 1
        out(f"보호자 {args.guardian_id}번을 열었다. 이제 어르신을 등록하고 승인할 수 있다.")
        return 0

    if (args.group, args.action) == ("guardian", "verify"):
        if accounts is None:
            err("계정 저장소가 없다.")
            return 1
        if not accounts.mark_email_verified(args.guardian_id):
            err(f"그런 보호자가 없다 — 보호자 번호 {args.guardian_id}.")
            return 1
        out(f"보호자 {args.guardian_id}번의 이메일을 인증된 것으로 기록했다.")
        return 0

    if (args.group, args.action) == ("guardian", "set-login"):
        if accounts is None:
            err("계정 저장소가 없다.")
            return 1
        # 비밀번호는 인자로 받지 않는다 — 셸 기록과 프로세스 목록에 남기 때문이다.
        password = read_password("새 비밀번호: ")
        if len(password) < MIN_PASSWORD:
            err(f"비밀번호는 {MIN_PASSWORD}자 이상이어야 한다.")
            return 1
        if read_password("한 번 더: ") != password:
            err("두 번 입력한 비밀번호가 다르다.")
            return 1
        try:
            found = accounts.set_login(args.guardian_id, args.email, hash_password(password))
        except EmailTaken:
            err("이미 다른 보호자가 쓰는 이메일이다.")
            return 1
        if not found:
            err(f"그런 보호자가 없다 — 보호자 번호 {args.guardian_id}.")
            return 1
        out(f"보호자 {args.guardian_id}번에게 이메일 로그인을 붙였다. 연결된 어르신과 열쇠는 그대로다.")
        return 0

    if (args.group, args.action) == ("guardian", "delete"):
        if accounts is None:
            err("계정 저장소가 없다.")
            return 1
        account = accounts.profile(args.guardian_id)
        if account is None:
            err(f"그런 보호자가 없다 — 보호자 번호 {args.guardian_id}.")
            return 1
        linked = len(directory.elders_of(args.guardian_id))
        if not args.yes:
            # 번호를 잘못 쳤는지 이름으로 확인하게 한다. 이름은 이 화면(stderr)에만 — 로그에는 남기지 않는다.
            err(
                f"보호자 {args.guardian_id}번({account.name})을 지우면 계정·열쇠·폰 등록·개인 코드·알림이 지워지고 "
                f"되돌릴 수 없다. 연결된 어르신 {linked}명은 지우지 않고 연결 전으로 돌린다(안부 전화가 멈추고, "
                "아직 안 쓴 연결 코드는 지워진다)."
            )
            err(f"정말 지우려면 `guardian delete {args.guardian_id} --yes`로 다시 실행한다.")
            return 1
        detached = withdraw_guardian(
            args.guardian_id,
            elders=directory,
            accounts=accounts,
            keys=keys,
            pairings=pairings,
            devices=devices,
            invites=invites,
        )
        out(f"보호자 {args.guardian_id}번을 지웠다 — 어르신 {detached}명은 지우지 않고 연결 전으로 돌렸다.")
        return 0

    if (args.group, args.action) == ("elder", "assign"):
        if not directory.assign_elder(args.elder_id, args.guardian_id):
            err("옮기지 못했다 — 어르신이나 보호자가 없다.")
            return 1
        out(f"어르신 {args.elder_id}번을 보호자 {args.guardian_id}번에게 옮겼다.")
        out("동의(consent_at)는 바뀌지 않았다. 동의는 사람이 받아서 직접 찍는다.")
        return 0

    if (args.group, args.action) == ("elder", "delete"):
        access = directory.get(args.elder_id)
        if access is None:
            err(f"그런 어르신이 없다 — 어르신 번호 {args.elder_id}.")
            return 1
        recordings = len(directory.audio_keys_of(args.elder_id))
        if not args.yes:
            # 번호를 잘못 쳤는지 이름으로 확인하게 한다. 이름은 이 화면(stderr)에만 — 로그에는 남기지 않는다.
            err(
                f"어르신 {args.elder_id}번({access.name})을 지우면 통화·점수·요약·언급·연락처·열쇠·코드가 지워지고 "
                f"되돌릴 수 없다. 녹음 {recordings}개는 서버 디스크와 S3에서 지운다(S3에서 실패하면 버킷의 30일 규칙이 지운다)."
            )
            err(f"정말 지우려면 `elder delete {args.elder_id} --yes`로 다시 실행한다.")
            return 1
        result = withdraw_elder(
            args.elder_id, elders=directory, recording_deleter=recording_deleter, recordings_dir=recordings_dir
        )
        out(
            f"어르신 {args.elder_id}번을 지웠다 — 녹음 {result.recordings}개 삭제 시도, 실패 {result.failed}개"
            + ("(버킷의 30일 규칙이 지운다)" if result.failed else "")
            + f", 서버 파일 {result.local_removed}개 삭제."
        )
        return 0

    raise AssertionError("도달할 수 없다 — argparse가 걸러야 한다")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        from dotenv import load_dotenv

        load_dotenv(".env")  # 이미 내보낸 DATABASE_URL이 이긴다 — 실수로 다른 DB를 건드리지 않게
    except ImportError:  # pragma: no cover
        pass

    url = database_url()
    if url is None:
        print("DATABASE_URL이 없다 — 열쇠를 만들 DB가 없다.", file=sys.stderr)
        return 1

    from app.api.postgres_devices import PostgresDeviceStore
    from app.api.postgres_elder_directory import PostgresElderDirectory
    from app.api.postgres_guardian_accounts import PostgresGuardianAccounts
    from app.api.postgres_guardian_keys import PostgresGuardianKeyStore
    from app.api.postgres_invites import PostgresInviteStore
    from app.api.postgres_pairing import PostgresPairingStore
    from app.media.stream_server import RECORDINGS_DIR

    pool = connect(url)
    try:
        return run(
            sys.argv[1:] if argv is None else argv,
            keys=PostgresGuardianKeyStore(pool=pool),
            directory=PostgresElderDirectory(pool=pool),
            accounts=PostgresGuardianAccounts(pool=pool),
            pool=pool,
            devices=PostgresDeviceStore(pool=pool),
            invites=PostgresInviteStore(pool=pool),
            pairings=PostgresPairingStore(pool=pool),
            # 서버와 같은 버킷 설정(.env의 RECORDINGS_BUCKET). 여기서는 S3에 닿지 않고 `elder delete --yes`에서만 닿는다.
            recording_deleter=recording_deleter_from_env(),
            # 서버(app.serve)와 같은 상대 경로다 — 프로젝트 폴더에서 실행한다(.env를 읽는 것과 같은 전제).
            recordings_dir=RECORDINGS_DIR,
        )
    finally:
        pool.close()


if __name__ == "__main__":
    raise SystemExit(main())
