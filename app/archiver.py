"""녹음 보관기 — 로컬 녹음을 S3로 올리고, 로컬은 정해진 때에 지운다.

**왜 필요했나.** 30일 삭제 정책은 S3 버킷의 수명주기 규칙에만 걸려 있었다.
그런데 녹음은 서버 디스크(`recordings/`)에만 쌓이고 아무도 지우지 않았다.
어르신 육성이 영원히 남는 상태였고, 인스턴스가 죽으면 그때까지의 녹음이
전부 사라지는 상태이기도 했다. 둘 다 나쁘다.

**규칙 셋.** 1분마다 폴더를 훑는다.

1. 아직 안 올린 녹음은 S3에 올린다. 통화가 끝나면 `notify()`로 바로 깨워서
   다음 틱을 기다리지 않는다 — 그 사이 인스턴스가 죽으면 녹음이 사라진다.
2. 올린 녹음은 **24시간 뒤** 로컬에서 지운다. 전사 워커가 이 파일을 읽는데,
   아침에 어르신이 몰리면 줄이 몇 시간 길어질 수 있다.
3. **30일이 지난 로컬 녹음은 올렸든 못 올렸든 지운다.** 30일은 어르신께 드린
   약속이고, "S3가 고장 나서 못 지켰다"는 변명이 안 된다. 못 올린 채
   지울 때는 크게 남긴다. 이 규칙은 버킷 설정과 무관하게 항상 돈다 —
   약속이 환경 변수 하나에 달려 있으면 안 된다.

**전사 원문도 여기서 30일에 지운다.** 원문은 녹음을 글로 옮긴 것이라 같은
약속이 걸린다. 약속을 지키는 곳을 한 군데로 모은다.

**통화 끝 경로에서 올리지 않는다.** 거기서 네트워크를 기다리면 그 어르신이
409로 잠긴다. 배치 전사를 통화 밖으로 뺀 것과 같은 이유다.

**올렸다는 표시는 옆에 빈 파일로 남긴다**(`<이름>.wav.uploaded`). 메모리에만
두면 재시작할 때마다 전부 다시 올린다. S3 PUT은 같은 키로 덮어쓰니 다시
올려도 틀리지는 않지만, 24시간 규칙이 표시에 기대므로 재시작을 넘어 남아야 한다.

**S3 키는 파일 이름 그대로다.** `calls.audio_key`가 이미 파일 이름이라,
그 값의 의미가 "S3 객체 키"가 될 뿐 DB도 통화 기록도 안 바뀐다.

**서버가 켜질 때 S3에 실제로 한 번 써 본다.** 권한이나 버킷 이름이 틀렸을 때
30일 뒤가 아니라 배포하는 그 순간 알아야 한다. 실패해도 서버는 멈추지
않는다 — 통화는 녹음 보관과 별개다.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Protocol

from app.api.transcript_store import TranscriptStore

logger = logging.getLogger(__name__)

DEFAULT_KEEP_LOCAL_SECONDS = 24 * 3600
DEFAULT_MAX_AGE_SECONDS = 30 * 24 * 3600
DEFAULT_TICK_SECONDS = 60.0

MARKER_SUFFIX = ".uploaded"

# 리전을 환경에 맡기면 boto3가 ~/.aws/config를 뒤진다. 개발 PC에는 있고
# EC2에는 없어서, 09-29에 테스트가 로컬 통과·서버 실패로 갈렸다.
DEFAULT_REGION = "ap-northeast-2"


class Uploader(Protocol):
    def put(self, key: str, path: Path) -> None: ...

    def check(self) -> None:
        """실제로 쓸 수 있는지 확인한다. 안 되면 예외."""
        ...


class S3Uploader:
    """S3에 올린다. 자격 증명은 인스턴스 프로파일에서 boto3가 찾는다."""

    def __init__(self, *, bucket: str, client=None, region: str = DEFAULT_REGION) -> None:
        self.bucket = bucket
        self.region = region
        if client is None:
            import boto3

            client = boto3.client("s3", region_name=region)
        self._client = client

    def put(self, key: str, path: Path) -> None:
        with path.open("rb") as body:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType="audio/wav",
                # 어르신 육성이다. 버킷 기본값에 기대지 않고 명시한다.
                ServerSideEncryption="AES256",
            )

    def check(self) -> None:
        # 읽기만 되고 쓰기가 막힌 경우를 잡으려면 쓰기를 해 봐야 한다.
        # 지우기가 실패해도 버킷의 30일 규칙이 치운다.
        key = f"_selfcheck/archiver-{int(time.time())}.txt"
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=b"ok",
            ContentType="text/plain",
            ServerSideEncryption="AES256",
        )
        self._client.delete_object(Bucket=self.bucket, Key=key)


class RecordingArchiver:
    def __init__(
        self,
        *,
        directory: Path,
        uploader: Uploader | None,
        clock: Callable[[], float] = time.time,
        keep_local_seconds: float = DEFAULT_KEEP_LOCAL_SECONDS,
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
        tick_seconds: float = DEFAULT_TICK_SECONDS,
        transcripts: TranscriptStore | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.uploader = uploader
        self.transcripts = transcripts
        self._clock = clock
        self._keep_local = keep_local_seconds
        self._max_age = max_age_seconds
        self._tick_seconds = tick_seconds
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ 한 번 훑기

    def sweep(self) -> None:
        now = self._clock()
        # 녹음 폴더가 없어도(새 서버) 원문 30일은 지킨다. 그래서 폴더 확인보다 먼저.
        self._purge_transcripts(now)

        if not self.directory.is_dir():
            return

        for wav in sorted(self.directory.glob("*.wav")):
            try:
                self._handle(wav, now)
            except Exception:
                # 한 파일 때문에 나머지가 멈추면 안 된다. 특히 30일 삭제가.
                logger.exception("녹음 보관 중 예상 못 한 오류 file=%s", wav.name)

        # 녹음은 없는데 표시만 남은 것. 손으로 지웠거나 앞 단계가 중간에
        # 끊긴 흔적이다.
        for marker in self.directory.glob("*.wav" + MARKER_SUFFIX):
            recording = marker.with_name(marker.name[: -len(MARKER_SUFFIX)])
            if not recording.exists():
                marker.unlink(missing_ok=True)

    def _purge_transcripts(self, now: float) -> None:
        if self.transcripts is None:
            return
        try:
            removed = self.transcripts.purge_older_than(now - self._max_age)
        except Exception:
            # 녹음 쪽 30일까지 멈추면 안 된다. 다음 틱에 다시 한다.
            logger.exception("30일 지난 전사 원문을 지우지 못했다 — 다음에 다시 한다")
            return
        if removed:
            logger.info("30일 지난 전사 원문 %d건을 지웠다", removed)

    def _handle(self, wav: Path, now: float) -> None:
        marker = wav.with_name(wav.name + MARKER_SUFFIX)
        uploaded = marker.exists()
        age = now - wav.stat().st_mtime

        if age > self._max_age:
            if not uploaded:
                logger.error(
                    "S3에 못 간 채 %d일이 지나 녹음을 지운다 — 30일 삭제 약속이다. "
                    "이 녹음은 이제 어디에도 없다 file=%s",
                    int(age // 86400),
                    wav.name,
                )
            wav.unlink(missing_ok=True)
            marker.unlink(missing_ok=True)
            return

        if not uploaded and self.uploader is not None:
            try:
                self.uploader.put(wav.name, wav)
            except Exception:
                logger.exception(
                    "녹음을 S3에 올리지 못했다 — 로컬에 두고 다음에 다시 한다 file=%s",
                    wav.name,
                )
                return
            marker.touch()
            uploaded = True
            logger.info("녹음을 S3에 올렸다 file=%s", wav.name)

        if uploaded and age > self._keep_local:
            wav.unlink(missing_ok=True)
            marker.unlink(missing_ok=True)

    # ------------------------------------------------------------ 루프

    def notify(self) -> None:
        """통화가 끝났다. 다음 틱을 기다리지 말고 지금 훑는다."""
        self._wake.set()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        if self.uploader is None:
            logger.warning(
                "녹음 버킷이 없다(RECORDINGS_BUCKET) — S3에 올리지 않는다. "
                "로컬 녹음은 30일 뒤 지운다"
            )
        else:
            try:
                self.uploader.check()
                logger.info("녹음 보관기를 켠다 — S3 쓰기 확인됨")
            except Exception:
                logger.exception(
                    "S3에 쓸 수 없다 — 녹음이 로컬에만 쌓인다. 권한과 버킷 이름을 "
                    "확인할 것. 30일이 지나면 올리지 못한 녹음도 지워진다"
                )

        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="archiver", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stopping.set()
        self._wake.set()
        thread = self._thread
        if thread is None:
            return
        thread.join(timeout=timeout)
        # 살아 있으면 참조를 지우지 않는다. 지우면 다음 start()가 같은 폴더를
        # 훑는 두 번째 스레드를 만든다.
        if not thread.is_alive():
            self._thread = None

    def _run(self) -> None:
        while not self._stopping.is_set():
            self.sweep()
            self._wake.wait(self._tick_seconds)
            self._wake.clear()


def archiver_from_env(
    directory: Path, transcripts: TranscriptStore | None = None
) -> RecordingArchiver:
    """RECORDINGS_BUCKET이 있으면 S3에 올리고, 없으면 로컬 30일 삭제만 한다.

    어느 쪽이든 보관기는 만든다. 30일 삭제가 설정에 달려 있으면 안 된다.
    """
    bucket = os.getenv("RECORDINGS_BUCKET", "").strip()
    if not bucket:
        return RecordingArchiver(
            directory=directory, uploader=None, transcripts=transcripts
        )

    region = os.getenv("AWS_REGION", "").strip() or DEFAULT_REGION
    return RecordingArchiver(
        directory=directory,
        uploader=S3Uploader(bucket=bucket, region=region),
        transcripts=transcripts,
    )
