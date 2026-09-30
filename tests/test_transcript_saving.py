"""전사 워커가 원문을 남기는가.

부정어 사전을 고쳤을 때 과거 통화를 다시 셀 원본이 이것뿐이다. 녹음은 30일
뒤 지워진다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.analysis.call_analysis import DEGRADED_NO_TRANSCRIPT
from app.api.transcript_store import InMemoryTranscriptStore
from app.transcription import TranscriptionFailed
from tests.test_transcription_worker import _analysis, run_worker

WAV = Path("1-a.wav")
PRIVATE = "요즘 밤마다 너무 외롭고 아파요"


def test_a_successful_transcription_is_kept():
    store = InMemoryTranscriptStore()
    worker, sink = run_worker(lambda _: PRIVATE, transcripts=store)
    try:
        worker.submit(10, _analysis(), WAV)
        sink.wait()
    finally:
        worker.stop()

    assert store.get(10) == PRIVATE


def test_silence_is_kept_as_an_empty_transcript():
    """'말을 안 했다'는 데이터다. 행이 없으면 '전사를 안 했다'와 구분이 안 된다."""
    store = InMemoryTranscriptStore()
    worker, sink = run_worker(lambda _: "", transcripts=store)
    try:
        worker.submit(10, _analysis(), WAV)
        sink.wait()
    finally:
        worker.stop()

    assert store.get(10) == ""


def test_a_failed_transcription_leaves_no_row():
    def fail(_):
        raise TranscriptionFailed("영구 실패")

    store = InMemoryTranscriptStore()
    worker, sink = run_worker(fail, transcripts=store)
    try:
        worker.submit(10, _analysis(), WAV)
        sink.wait()
    finally:
        worker.stop()

    assert store.get(10) is None


def test_a_storage_failure_does_not_cost_the_score(caplog):
    """전사는 성공했고 보관만 못 했다. 그걸 '전사 실패'로 접으면 멀쩡한
    통화가 점수를 잃는다 — 원문 보관은 점수보다 뒤에 있는 일이다."""

    class Broken(InMemoryTranscriptStore):
        def save(self, call_id, text):
            raise RuntimeError("DB 끊김")

    with caplog.at_level(logging.ERROR, logger="app.transcription"):
        worker, sink = run_worker(lambda _: "아파요", transcripts=Broken())
        try:
            worker.submit(10, _analysis(), WAV)
            sink.wait()
        finally:
            worker.stop()

    (_, analysis), = sink.results
    assert DEGRADED_NO_TRANSCRIPT not in analysis.degraded_reasons
    assert analysis.metrics.negative_word_count == 1
    assert "원문을 남기지 못했다" in caplog.text


def test_the_transcript_never_reaches_the_log(caplog):
    """어르신의 사적인 대화 전문이다. 로그는 원문보다 오래, 넓게 남는다."""

    class Broken(InMemoryTranscriptStore):
        def save(self, call_id, text):
            raise RuntimeError("DB 끊김")

    with caplog.at_level(logging.DEBUG):
        worker, sink = run_worker(lambda _: PRIVATE, transcripts=Broken())
        try:
            worker.submit(10, _analysis(), WAV)
            sink.wait()
        finally:
            worker.stop()

    assert PRIVATE not in caplog.text


def test_without_a_store_the_worker_still_scores():
    """저장소를 안 주는 기존 조립도 그대로 돈다."""
    worker, sink = run_worker(lambda _: "아파요")
    try:
        worker.submit(10, _analysis(), WAV)
        sink.wait()
    finally:
        worker.stop()

    (_, analysis), = sink.results
    assert analysis.metrics.negative_word_count == 1
