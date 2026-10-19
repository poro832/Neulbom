"""녹음 삭제기 — 탈퇴한 어르신의 녹음을 S3에서 지운다 (설계: 탈퇴·내 정보 삭제).

녹음을 올리는 쪽은 보관기(app/archiver.py)다. S3 키는 파일 이름 그대로이고 `calls.audio_key`에 남는다 —
그래서 어르신 행을 지우기 **전에** 키를 읽어 여기로 넘긴다(app/api/account_deletion.py).

**최선으로만 지운다.** S3가 거절하거나 연결이 끊겨도 탈퇴는 멈추지 않는다. 남은 녹음은 버킷의 30일 수명
규칙이 결국 지운다. 그래서 예외를 밖으로 내지 않고 **지우지 못한 수**를 돌려준다(0이면 모두 지웠다).

**키는 로그에 남기지 않는다.** 파일 이름에 어르신 번호와 통화 시각이 들어 있다. 실패도 개수와 오류 종류만 남긴다.

**S3에는 지울 때 처음 닿는다.** 서버가 켜지거나 운영 도구가 뜰 때 클라이언트를 만들지 않는다. 권한은 서버의
인스턴스 역할에 `s3:DeleteObject`(그 버킷의 객체만)가 있어야 한다 — 없으면 전부 실패로 세고 탈퇴는 계속된다.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Protocol

from app.archiver import DEFAULT_REGION

logger = logging.getLogger(__name__)

# S3 DeleteObjects 한 번에 지울 수 있는 최대 키 수.
MAX_KEYS_PER_REQUEST = 1000


class RecordingDeleter(Protocol):
    def delete_many(self, keys: Sequence[str]) -> int:
        """키들을 지운다. **지우지 못한 수**를 돌려준다(0이면 모두 지웠다). 예외를 내지 않는다.

        같은 키가 여러 번 있으면 한 번만 센다. 없는 키를 지우는 것은 성공이다(S3가 그렇게 답한다).
        """
        ...


class S3RecordingDeleter:
    """S3에서 지운다. 자격 증명은 인스턴스 프로파일에서 boto3가 찾는다(S3Uploader와 같다)."""

    def __init__(self, bucket: str, client=None, *, region: str = DEFAULT_REGION) -> None:
        self.bucket = bucket
        self.region = region
        self._client = client

    def _s3(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    def delete_many(self, keys: Sequence[str]) -> int:
        unique = list(dict.fromkeys(key for key in keys if key))
        failed = 0
        for start in range(0, len(unique), MAX_KEYS_PER_REQUEST):
            batch = unique[start : start + MAX_KEYS_PER_REQUEST]
            try:
                response = self._s3().delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
                )
            except Exception as exc:
                # 이 묶음은 모두 실패로 센다. 다음 묶음은 계속 보낸다. 오류 내용(키가 들어 있을 수 있다)은 남기지 않는다.
                failed += len(batch)
                logger.warning(
                    "S3 녹음 삭제 요청이 실패했다 — 다음 묶음은 계속한다 수=%d 오류=%s", len(batch), type(exc).__name__
                )
                continue
            errors = (response or {}).get("Errors") or []
            if errors:
                failed += min(len(errors), len(batch))
                codes = sorted({str(e.get("Code", "?")) for e in errors})
                logger.warning("S3가 녹음 일부를 지우지 않았다 수=%d 코드=%s", len(errors), ",".join(codes))
        return failed


def recording_deleter_from_env(env: Mapping[str, str] | None = None) -> S3RecordingDeleter | None:
    """RECORDINGS_BUCKET이 있으면 그 버킷의 삭제기, 없으면 None(보관기의 archiver_from_env와 같은 규칙).

    리전은 AWS_REGION, 없으면 서울. 여기서는 S3에 닿지 않는다.
    """
    env = os.environ if env is None else env
    bucket = env.get("RECORDINGS_BUCKET", "").strip()
    if not bucket:
        return None
    region = env.get("AWS_REGION", "").strip() or DEFAULT_REGION
    return S3RecordingDeleter(bucket, region=region)
