"""통화가 끝난 뒤 도는 전사 처리 (설계 3장).

여기에는 CLOVA가 없다. 워커는 "녹음을 주면 글을 준다"는 호출 가능한 것을
주입받을 뿐이라, 사업자를 바꿔도 이 파일은 바뀌지 않는다.
"""

from __future__ import annotations


class TranscriptionUnavailable(Exception):
    """전사를 부르지 못했다 — 연결 실패, 인증 실패처럼 요청이 닿지 않은 경우.

    빠르게 돌아오고, 잠깐 끊긴 네트워크가 원인일 수 있으므로 다시 해볼
    값어치가 있다(설계 5장 ①).
    """


class TranscriptionFailed(Exception):
    """전사가 실패로 끝났다 — 시간이 다 됐거나 사업자가 실패라고 답했다.

    다시 보내도 같은 답이 오리라고 볼 근거가 있으므로 재시도하지 않는다
    (설계 5장 ②③). 줄이 직렬이라 붙들고 있으면 뒤에 선 통화가 전부 밀린다.
    """


import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from app.analysis.call_analysis import (
    DEGRADED_NO_TRANSCRIPT,
    CallAnalysis,
    with_transcript,
)

logger = logging.getLogger(__name__)

# 연결 실패만 다시 해본다. 세 번째도 실패하면 포기한다(설계 5장).
MAX_RETRIES = 2


@dataclass(frozen=True)
class PendingTranscription:
    """줄에 서 있는 일감. 불변이고 작다 — 나중에 디스크에 남기기 쉽도록."""

    call_id: int
    analysis: CallAnalysis
    wav_path: Path


class TranscriptionWorker:
    """전사를 통화 종료 경로 밖에서 돌린다 (설계 3장).

    **왜 워커가 하나인가.** 병렬로 돌리면 같은 어르신의 통화 두 건이 순서를
    바꿔 기록될 수 있고, 그러면 나중 통화가 앞 통화를 기준선에서 보지 못한다.
    직렬이면 그 일이 생기지 않는다. 같은 어르신은 하루 한 통이라 줄이 하나여도
    밀리지 않는다(설계 6장).

    **여기에 CLOVA가 없다.** transcribe를 주입받으므로 사업자를 바꿔도 이
    클래스는 바뀌지 않고, 테스트는 즉시 문자열을 돌려주는 가짜로 돈다.
    """

    def __init__(
        self,
        *,
        transcribe: Callable[[Path], str],
        sink: Callable[[int, CallAnalysis], None],
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._transcribe = transcribe
        self._sink = sink
        self._max_retries = max_retries
        self._queue: queue.Queue[PendingTranscription | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        # 종료할 때 버린 통화들. 녹음은 30일 남으므로 이 목록이 곧 복구 단서다.
        self.dropped: list[int] = []

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="transcription-worker", daemon=True
        )
        self._thread.start()

    def submit(self, call_id: int, analysis: CallAnalysis, wav_path: Path) -> None:
        """줄에 세우고 바로 돌아온다.

        여기서 기다리면 통화가 '끝남'으로 넘어가지 못하고, 그 어르신은
        그동안 다시 전화를 요청할 수 없다(409 영구 잠금).
        """
        self._queue.put(PendingTranscription(call_id, analysis, wav_path))

    def stop(self, timeout: float = 30.0, *, drain: bool = False) -> None:
        """진행 중인 한 건만 마치고 나머지는 버린다.

        큐에 10건이 남았는데 전부 처리하려 들면 종료가 10분 넘게 걸리고,
        배포할 때마다 그만큼 기다리게 된다(설계 6장).

        기본값이 "버린다"인 이유는 운영에서 부르는 것이 그쪽이기 때문이다.
        기본값과 실제 사용이 다르면 테스트가 통과해도 운영이 다르게 돈다.
        drain=True는 남은 것까지 처리하고 끝내며, 테스트가 쓴다.
        """
        if self._thread is None:
            return
        if not drain:
            self._drain_pending()
        self._queue.put(None)
        self._thread.join(timeout)
        self._thread = None

    def _drain_pending(self) -> None:
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                break
            if job is None:
                continue
            self.dropped.append(job.call_id)
        if self.dropped:
            logger.warning(
                "종료하면서 전사 대기 %d건을 버린다 — 녹음은 30일 남으므로 "
                "다시 돌릴 수 있다 call_id=%s",
                len(self.dropped),
                self.dropped,
            )

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            try:
                self._handle(job)
            except Exception:
                # 여기서 새어 나가면 워커 스레드가 죽고, 그 뒤 모든 통화가
                # 조용히 점수를 잃는다. 아침에 30통이 들어오는데 아무도 모른다.
                logger.exception("전사 처리가 실패했다 call_id=%s", job.call_id)

    def _handle(self, job: PendingTranscription) -> None:
        transcript = self._transcribe_with_retries(job)
        if transcript is None:
            analysis = replace(
                job.analysis,
                degraded_reasons=job.analysis.degraded_reasons
                + (DEGRADED_NO_TRANSCRIPT,),
            )
        else:
            analysis = with_transcript(job.analysis, transcript)
        self._sink(job.call_id, analysis)

    def _transcribe_with_retries(self, job: PendingTranscription) -> str | None:
        for attempt in range(self._max_retries + 1):
            try:
                return self._transcribe(job.wav_path)
            except TranscriptionUnavailable as exc:
                # 요청이 닿지 않았다. 빠르게 돌아오므로 다시 해볼 값어치가 있다.
                logger.warning(
                    "전사를 부르지 못했다 (%d/%d) call_id=%s — %s",
                    attempt + 1,
                    self._max_retries + 1,
                    job.call_id,
                    exc,
                )
            except TranscriptionFailed as exc:
                # 사업자가 실패라고 답했거나 시간이 다 됐다. 다시 보내도 같고,
                # 줄이 직렬이라 붙들면 뒤에 선 통화가 전부 밀린다.
                logger.error("전사가 실패했다 call_id=%s — %s", job.call_id, exc)
                return None
        logger.error(
            "전사를 끝내 받지 못했다 — 점수 없이 지표만 남긴다 call_id=%s", job.call_id
        )
        return None
