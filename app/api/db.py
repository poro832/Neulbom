"""Postgres 연결 (설계 5장).

**왜 풀인가.** 연결을 매번 새로 열면 통화 한 통에 handshake를 수십 번 한다.
그리고 우리는 두 곳에서 저장소를 부른다 — FastAPI 스레드풀과 전사 워커
스레드다. 풀이 그 둘을 안전하게 나눠 준다.

**왜 동기인가.** 저장소를 부르는 자리가 둘 다 동기다. 비동기로 가면 호출부를
전부 고쳐야 하는데, 전사 워커는 설계상 스레드라 얻는 것이 없다.

**왜 여기서 import하지 않는가.** psycopg는 런타임 의존성이지만, DATABASE_URL이
없으면 이 모듈은 아예 불리지 않는다. 함수 안에서 import하면 psycopg가 깔려
있지 않은 환경에서도 나머지 테스트가 돈다.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# 풀 크기. FastAPI 스레드풀과 전사 워커 하나가 쓰는 규모다. 어르신 30명이
# 아침에 몰려도 통화는 직렬로 처리되므로 동시 연결이 이보다 늘 이유가 없다.
MIN_POOL = 1
MAX_POOL = 5


def database_url() -> str | None:
    """환경에서 접속 문자열을 읽는다. 없으면 None — 메모리 저장소로 간다.

    DATABASE_URL이 있고 없고가 저장소를 고르는 유일한 기준이다. "키가 있으면
    자동으로" 같은 추론을 두지 않는다 — 어느 저장소로 돌고 있는지가 조용히
    바뀌면, 재시작해도 데이터가 남는다고 믿다가 아닌 것을 나중에 안다.
    """
    url = os.getenv("DATABASE_URL", "").strip()
    return url or None


def connect(url: str):
    """연결 풀을 연다. 호출부가 close할 책임을 진다."""
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        url,
        min_size=MIN_POOL,
        max_size=MAX_POOL,
        # 여기서 막히면 서버가 뜨자마자 죽는 대신 조용히 매달린다. DB가
        # 아직 안 떴을 때 원인을 빨리 알려면 짧게 끊는 편이 낫다.
        timeout=10.0,
        open=True,
    )
    logger.info("Postgres 연결 풀을 열었다 — 최대 %d", MAX_POOL)
    return pool


# 로컬 개발 DB로 인정하는 호스트. 여기 없으면 파괴적인 작업을 거부한다.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})


def assert_local(url: str | None = None) -> None:
    """이 DB가 로컬 개발용인지 확인한다. 아니면 그 자리에서 멈춘다.

    **왜 필요했나.** 테스트용 초기화 함수들이 `TRUNCATE ... CASCADE`로
    시작한다. 2026-09-29에 그 테스트를 실제 RDS를 대상으로 돌리라고 안내한
    적이 있고, 실제로 명부가 날아갔다. 그때는 실통화 전이라 seed를 다시
    돌리면 끝이었지만, 첫 통화가 들어온 뒤였다면 **통화 이력과 위험 점수가
    전부 사라졌을 것이다.** 녹음은 30일 뒤 지워지므로 복구할 방법도 없다.

    이름에 `for_tests`를 붙이는 것만으로는 부족했다. 사람이 읽고 조심할
    것을 기대하는 대신, 대상이 로컬이 아니면 코드가 거부하게 한다.
    """
    from urllib.parse import urlparse

    target = url if url is not None else database_url()
    if target is None:
        raise RuntimeError("DATABASE_URL이 없다 — 지울 DB가 없다")

    host = (urlparse(target).hostname or "").lower()
    if host not in LOCAL_HOSTS:
        raise RuntimeError(
            f"로컬 DB가 아니라 거부한다 — host={host!r}. "
            "이 작업은 테이블을 통째로 비운다. 원격 DB(RDS 등)에서는 "
            "실통화 기록과 위험 점수가 전부 사라지고 되돌릴 수 없다."
        )
