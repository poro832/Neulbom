"""운영 도구 — `python -m app.admin ...` (서버에서 사람이 실행한다).

보호자 앱 화면이 생기기 전까지 보호자와 열쇠를 사람이 만든다.

    key issue --guardian-id N --label "시연 폰"   열쇠를 만들고 **한 번만** 보여 준다
    key list                                      앞 12글자, 이름표, 날짜 (열쇠와 지문은 안 나온다)
    key revoke --prefix nlb_xxxxxxxx              열쇠를 폐기한다 (다음 요청부터 막힌다)
    guardian add --name ... --phone ...           열쇠 전용 보호자를 만든다
    elder assign --elder-id N --guardian-id M     어르신을 그 보호자에게 옮긴다

**동의(`consent_at`)는 여기서 채우지 않는다.** 동의는 사람이 받는 것이다.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from datetime import datetime

from app.api.db import connect, database_url
from app.api.elder_directory import DirectoryAdmin
from app.api.guardian_auth import AmbiguousPrefix, GuardianKeyStore, generate_key
from app.scheduler import KST


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

    elder = groups.add_parser("elder", help="어르신").add_subparsers(dest="action", required=True)
    assign = elder.add_parser("assign", help="어르신을 보호자에게 옮긴다")
    assign.add_argument("--elder-id", type=int, required=True)
    assign.add_argument("--guardian-id", type=int, required=True)
    return parser


def run(
    argv: list[str],
    *,
    keys: GuardianKeyStore,
    directory: DirectoryAdmin,
    out: Callable[..., None] = print,
    err: Callable[..., None] | None = None,
) -> int:
    err = err or (lambda text="": print(text, file=sys.stderr))
    args = build_parser().parse_args(argv)

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

    if (args.group, args.action) == ("elder", "assign"):
        if not directory.assign_elder(args.elder_id, args.guardian_id):
            err("옮기지 못했다 — 어르신이나 보호자가 없다.")
            return 1
        out(f"어르신 {args.elder_id}번을 보호자 {args.guardian_id}번에게 옮겼다.")
        out("동의(consent_at)는 바뀌지 않았다. 동의는 사람이 받아서 직접 찍는다.")
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

    from app.api.postgres_elder_directory import PostgresElderDirectory
    from app.api.postgres_guardian_keys import PostgresGuardianKeyStore

    pool = connect(url)
    try:
        return run(
            sys.argv[1:] if argv is None else argv,
            keys=PostgresGuardianKeyStore(pool=pool),
            directory=PostgresElderDirectory(pool=pool),
        )
    finally:
        pool.close()


if __name__ == "__main__":
    raise SystemExit(main())
