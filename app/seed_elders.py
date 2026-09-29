"""어르신 명부를 DB에 채운다 — `python -m app.seed_elders`

**왜 서버가 아니라 스크립트인가.** `main.py`는 이미 조립 책임을 넷 지고 있고
(배치 전사 최종 검토가 지적했다), import만으로 DB에 쓰는 것은 숨은 동작이다.
서버를 띄우는 것과 명부를 바꾸는 것은 다른 일이므로 다른 명령으로 둔다.

**이건 임시 다리다.** 지금 명부는 `ELDER_PHONES` 환경 변수에 있다. 보호자
화면이 생기면 거기서 등록·수정하게 되고 이 스크립트는 사라진다. 그때까지
전화번호를 바꾸려면 환경 변수를 고치고 이걸 다시 돌린다.

**여러 번 돌려도 안전하다.** 같은 어르신을 다시 넣지 않고 전화번호만 맞춘다.

**동의는 여기서 주지 않는다.** `elders.consent_at`이 NULL이면 발신 대상에서
빠진다(`elders_due_idx`가 그 조건으로 걸려 있다). 동의는 사람이 받는 것이지
스크립트가 채울 값이 아니다 — 여기서 now()를 넣으면 아무도 동의하지 않은
어르신께 전화가 나간다.
"""

from __future__ import annotations

import logging
import os
import sys

from app.api.db import connect, database_url

logger = logging.getLogger(__name__)

# 보호자 화면이 없는 동안 모든 어르신이 매달릴 자리. elders.guardian_id가
# NOT NULL이라 행 하나는 있어야 한다.
PLACEHOLDER_GUARDIAN = 1


def parse_phones(raw: str) -> dict[int, str]:
    """ELDER_PHONES="1:070-1111-2222,2:070-3333-4444"

    형식이 깨진 항목은 건너뛰고 크게 남긴다. 조용히 지나가면 그 어르신께만
    전화가 안 가는 것을 한참 뒤에 안다.
    """
    phones: dict[int, str] = {}
    for entry in raw.split(","):
        if not entry.strip():
            continue
        elder_id, _, phone = entry.partition(":")
        try:
            phones[int(elder_id.strip())] = phone.strip()
        except ValueError:
            logger.error(
                "ELDER_PHONES 항목을 읽을 수 없다 — 건너뛴다 entry=%s."
                ' 형식은 "어르신번호:전화번호"다 (예: 1:070-1111-2222)',
                entry,
            )
    return phones


def seed(pool, phones: dict[int, str]) -> int:
    """명부를 맞춘다. 넣은/고친 어르신 수를 돌려준다."""
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO guardians "
            "  (guardian_id, name, email, password_hash, phone_number) "
            "VALUES (%s, '임시 보호자', 'placeholder@example.invalid', "
            "        'not-a-login', '000-0000-0000') "
            "ON CONFLICT (guardian_id) DO NOTHING",
            (PLACEHOLDER_GUARDIAN,),
        )
        for elder_id, phone in sorted(phones.items()):
            conn.execute(
                "INSERT INTO elders (elder_id, guardian_id, name, phone_number) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (elder_id) DO UPDATE SET phone_number = EXCLUDED.phone_number",
                (elder_id, PLACEHOLDER_GUARDIAN, f"어르신 {elder_id}", phone),
            )
        # 다음 어르신이 손으로 준 번호와 겹치지 않게 시퀀스를 밀어 둔다.
        # 안 하면 보호자 화면이 생겨 처음 등록할 때 중복 키로 실패한다.
        conn.execute(
            "SELECT setval('elders_elder_id_seq', "
            "  GREATEST((SELECT COALESCE(MAX(elder_id), 0) FROM elders), 1))"
        )
    return len(phones)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    url = database_url()
    if url is None:
        print("DATABASE_URL이 없다 — 채울 DB가 없다.", file=sys.stderr)
        return 1

    raw = os.getenv("ELDER_PHONES", "").strip()
    if not raw:
        print("ELDER_PHONES가 비어 있다 — 넣을 어르신이 없다.", file=sys.stderr)
        return 1

    # 값은 있는데 하나도 못 읽은 경우를 따로 말한다. 예전에는 둘 다 "비어
    # 있다"로 나가서, 형식을 틀린 사람이 변수를 안 채운 줄 알고 한참 헤맸다.
    phones = parse_phones(raw)
    if not phones:
        print("ELDER_PHONES에서 읽어낸 어르신이 없다 — 형식을 확인하라.", file=sys.stderr)
        print('  형식: "어르신번호:전화번호", 여럿이면 쉼표로 잇는다', file=sys.stderr)
        print('  예시: ELDER_PHONES="1:070-1111-2222,2:070-3333-4444"', file=sys.stderr)
        return 1

    pool = connect(url)
    try:
        count = seed(pool, phones)
    finally:
        pool.close()

    print(f"어르신 {count}명을 맞췄다: {sorted(phones)}")
    print("동의(consent_at)는 비어 있다 — 채워야 발신 대상이 된다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
