"""통화가 끝난 뒤 도는 전사 워커.

이 테스트에는 CLOVA가 없다. 워커는 "녹음을 주면 글을 준다"는 호출 가능한
것만 알기 때문이다.
"""

import logging
import threading
from dataclasses import replace
from pathlib import Path

from app.analysis.call_analysis import DEGRADED_NO_TRANSCRIPT, CallAnalysis
from app.analysis.metrics_calculator import CallMetrics
from app.transcription import (
    TranscriptionFailed,
    TranscriptionUnavailable,
    TranscriptionWorker,
)


def _analysis(**over) -> CallAnalysis:
    base = CallAnalysis(
        metrics=CallMetrics(
            speech_ratio=0.4,
            silence_ratio=0.6,
            turn_count=7,
            negative_word_count=0,
            avg_response_delay_ms=1200,
        ),
        clipped_ms=0,
        filled_gap_ms=0,
        call_duration_ms=120_000,
    )
    return replace(base, **over)


class Recorder:
    """sink 대역. 결과가 다 들어올 때까지 기다릴 수 있다."""

    def __init__(self, expected: int = 1):
        self.results: list[tuple[int, CallAnalysis]] = []
        self._done = threading.Event()
        self._expected = expected

    def __call__(self, call_id: int, analysis: CallAnalysis) -> None:
        self.results.append((call_id, analysis))
        if len(self.results) >= self._expected:
            self._done.set()

    def wait(self, timeout: float = 5.0) -> None:
        assert self._done.wait(timeout), f"결과가 오지 않았다 — {self.results}"


def run_worker(transcribe, expected=1, **kwargs):
    sink = Recorder(expected)
    worker = TranscriptionWorker(transcribe=transcribe, sink=sink, **kwargs)
    worker.start()
    return worker, sink


def test_submit_does_not_wait_for_the_transcription():
    """submit이 전사를 기다리면 통화가 '끝남'으로 넘어가지 못하고, 그
    어르신은 그동안 다시 전화를 요청할 수 없다(409 영구 잠금).

    이 테스트가 이 설계 전체의 이유다.
    """
    started = threading.Event()
    release = threading.Event()

    def slow(wav_path):
        started.set()
        release.wait(5.0)
        return "안녕하세요"

    worker, sink = run_worker(slow)
    try:
        worker.submit(1, _analysis(), Path("call.wav"))
        assert started.wait(2.0), "워커가 일을 시작하지 않았다"
        # 전사가 아직 끝나지 않았는데 submit은 이미 돌아와 있다.
        assert sink.results == []
    finally:
        release.set()
        worker.stop()


def test_the_transcript_becomes_the_negative_word_count():
    worker, sink = run_worker(lambda wav_path: "무릎이 아파요")
    try:
        worker.submit(7, _analysis(), Path("call.wav"))
        sink.wait()
    finally:
        worker.stop()

    call_id, analysis = sink.results[0]
    assert call_id == 7
    assert analysis.metrics.negative_word_count > 0
    assert analysis.degraded is False


def test_calls_are_processed_in_the_order_they_arrived():
    """순서가 뒤집히면 나중 통화가 앞 통화를 기준선에서 보지 못한다 —
    B안을 기각한 바로 그 결함이 뒷문으로 돌아온다(설계 6장).
    """
    worker, sink = run_worker(lambda wav_path: "괜찮아요", expected=3)
    try:
        for call_id in (1, 2, 3):
            worker.submit(call_id, _analysis(), Path(f"{call_id}.wav"))
        sink.wait()
    finally:
        worker.stop()

    assert [call_id for call_id, _ in sink.results] == [1, 2, 3]


def test_a_connection_failure_is_retried_twice():
    """잠깐 끊긴 네트워크 때문에 통화 하나를 버리는 건 아깝다(설계 5장)."""
    attempts = []

    def flaky(wav_path):
        attempts.append(wav_path)
        if len(attempts) < 3:
            raise TranscriptionUnavailable("연결 실패")
        return "무릎이 아파요"

    worker, sink = run_worker(flaky)
    try:
        worker.submit(1, _analysis(), Path("call.wav"))
        sink.wait()
    finally:
        worker.stop()

    assert len(attempts) == 3  # 최초 1회 + 재시도 2회
    assert sink.results[0][1].degraded is False


def test_giving_up_records_the_call_without_a_score():
    """점수를 안 낸다고 통화를 통째로 버리면 멀쩡히 측정된 지표 셋이 함께
    사라진다. 나중에 실제 분포를 보고 기준을 정할 때 이 통화도 재료다.
    """

    def never(wav_path):
        raise TranscriptionUnavailable("연결 실패")

    worker, sink = run_worker(never)
    try:
        worker.submit(1, _analysis(), Path("call.wav"))
        sink.wait()
    finally:
        worker.stop()

    _, analysis = sink.results[0]
    assert DEGRADED_NO_TRANSCRIPT in analysis.degraded_reasons
    assert analysis.degraded is True
    assert analysis.metrics.speech_ratio == 0.4  # 지표는 그대로 남았다


def test_a_timeout_is_not_retried():
    """사업자가 10분을 쓰고도 못 끝냈다면 다시 보내도 같다. 그리고 줄이
    직렬이라 붙들고 있으면 그날 아침 전체가 밀린다(설계 5장).
    """
    attempts = []

    def timing_out(wav_path):
        attempts.append(wav_path)
        raise TranscriptionFailed("시간 초과")

    worker, sink = run_worker(timing_out)
    try:
        worker.submit(1, _analysis(), Path("call.wav"))
        sink.wait()
    finally:
        worker.stop()

    assert len(attempts) == 1
    assert DEGRADED_NO_TRANSCRIPT in sink.results[0][1].degraded_reasons


def test_an_existing_degraded_reason_is_kept_when_transcription_fails():
    """에코 때문에 이미 근거가 부족한 통화에 전사까지 실패했다면 사유가
    둘이다. 하나로 덮으면 어디를 고쳐야 하는지 알 수 없게 된다.
    """
    from app.analysis.call_analysis import DEGRADED_ECHO_CLIP

    def never(wav_path):
        raise TranscriptionFailed("실패")

    worker, sink = run_worker(never)
    try:
        worker.submit(1, _analysis(degraded_reasons=(DEGRADED_ECHO_CLIP,)), Path("c.wav"))
        sink.wait()
    finally:
        worker.stop()

    reasons = sink.results[0][1].degraded_reasons
    assert DEGRADED_ECHO_CLIP in reasons and DEGRADED_NO_TRANSCRIPT in reasons


def test_a_broken_sink_does_not_kill_the_worker():
    """sink가 터졌다고 워커가 죽으면 그 뒤 모든 통화가 조용히 점수를 잃는다.
    아침에 30통이 들어오는데 아무도 모른다.
    """
    seen = []
    both = threading.Event()

    def sink(call_id, analysis):
        seen.append(call_id)
        if call_id == 1:
            raise RuntimeError("저장소가 터졌다")
        both.set()

    worker = TranscriptionWorker(transcribe=lambda p: "괜찮아요", sink=sink)
    worker.start()
    try:
        worker.submit(1, _analysis(), Path("1.wav"))
        worker.submit(2, _analysis(), Path("2.wav"))
        assert both.wait(5.0), f"두 번째 통화가 처리되지 않았다 — {seen}"
    finally:
        worker.stop()

    assert seen == [1, 2]


def test_shutdown_drops_the_queue_and_names_what_it_dropped(caplog):
    """큐에 10건이 남았는데 전부 처리하려 들면 종료가 10분 넘게 걸리고,
    배포할 때마다 그만큼 기다리게 된다(설계 6장).

    버린 목록이 없으면 무엇을 잃었는지조차 모른다. call_id만으로는 부족하다
    — 녹음 파일 이름은 call_id만이 아니라 UTC 시각과 난수까지 들어가고
    (app/media/session.py), 프로세스가 재시작하면 call_id가 1로 돌아가
    같은 번호가 여러 날의 녹음을 가리킬 수 있다. wav 파일 이름까지 있어야
    나중에 손으로 다시 돌릴 수 있다.
    """
    busy = threading.Event()
    release = threading.Event()

    def slow(wav_path):
        busy.set()
        release.wait(5.0)
        return "괜찮아요"

    worker = TranscriptionWorker(transcribe=slow, sink=lambda *a: None)
    worker.start()
    worker.submit(1, _analysis(), Path("1.wav"))
    # 워커가 1번을 붙들고 멈춰 있는 동안 2·3번을 넣는다. 그래야 둘이
    # 확실히 큐에 남아 있는 상태에서 종료를 부를 수 있다.
    assert busy.wait(5.0), "워커가 일을 시작하지 않았다"
    worker.submit(2, _analysis(), Path("2.wav"))
    worker.submit(3, _analysis(), Path("3.wav"))

    with caplog.at_level(logging.WARNING, logger="app.transcription"):
        release.set()
        worker.stop()

    assert worker.dropped == [(2, "2.wav"), (3, "3.wav")]
    message = " ".join(record.getMessage() for record in caplog.records)
    assert "2.wav" in message and "3.wav" in message


def test_draining_is_opt_in():
    """기본값은 버리는 쪽이다 — 운영에서 부르는 것이 그쪽이기 때문이다.
    기본값과 실제 사용이 다르면 테스트가 통과해도 운영이 다르게 돈다.
    """
    worker, sink = run_worker(lambda wav_path: "괜찮아요", expected=2)
    try:
        worker.submit(1, _analysis(), Path("1.wav"))
        worker.submit(2, _analysis(), Path("2.wav"))
        worker.stop(drain=True)
    finally:
        worker.stop()

    assert [call_id for call_id, _ in sink.results] == [1, 2]
    assert worker.dropped == []


def test_the_same_call_is_only_submitted_once_on_the_normal_path():
    """현재 규약: 한 call_id는 기준선에서 최대 한 번의 통화로 취급한다.

    지금 중복 방지를 만들지는 않는다 — 중복을 만드는 경로가 아직 없기
    때문이다. 백필이나 수동 재처리가 생기면 이 테스트가 먼저 깨져서
    "표본 식별 규칙을 정하라"고 알려 준다(설계 13장).
    """
    worker, sink = run_worker(lambda wav_path: "괜찮아요", expected=2)
    try:
        worker.submit(1, _analysis(), Path("1.wav"))
        worker.submit(1, _analysis(), Path("1.wav"))
        sink.wait()
    finally:
        worker.stop()

    # 지금은 두 번 다 통과한다. 이 사실을 적어 둔다.
    assert [call_id for call_id, _ in sink.results] == [1, 1]


def test_an_undeclared_exception_still_records_the_call():
    """전사 호출이 우리가 선언한 두 예외(TranscriptionUnavailable,
    TranscriptionFailed) 중 어느 쪽도 아닌 예외를 던지면, 예전에는
    _run의 except Exception이 그것을 삼켜 sink가 아예 안 불렸다 — 그 통화는
    CallOutcome을 하나도 못 받았다. 설계 5장의 "기록은 반드시 한다"는
    예외 종류와 무관한 약속이다.
    """

    def buggy(wav_path):
        raise ValueError("예상 못 한 배선 결함")

    worker, sink = run_worker(buggy)
    try:
        worker.submit(1, _analysis(), Path("call.wav"))
        sink.wait()
    finally:
        worker.stop()

    call_id, analysis = sink.results[0]
    assert call_id == 1
    assert DEGRADED_NO_TRANSCRIPT in analysis.degraded_reasons
    assert analysis.metrics.speech_ratio == 0.4  # 지표는 그대로 남았다


def test_a_stop_that_times_out_names_the_call_it_is_still_holding(caplog):
    """예전에는 이 로그에 call_id가 없었다. 서버가 종료되고 데몬 스레드가
    요청 도중 죽으면, 그 통화는 dropped 목록에도 메모리 저장소에도 없는
    유일한 통화가 된다 — 이 로그가 그 통화를 아는 마지막 기회다.
    """
    busy = threading.Event()
    release = threading.Event()

    def slow(wav_path):
        busy.set()
        assert release.wait(5.0), "테스트가 전사를 놓아주지 않았다"
        return "괜찮아요"

    worker = TranscriptionWorker(transcribe=slow, sink=lambda *a: None)
    worker.start()
    try:
        worker.submit(7, _analysis(), Path("7.wav"))
        assert busy.wait(5.0), "워커가 일을 시작하지 않았다"

        with caplog.at_level(logging.ERROR, logger="app.transcription"):
            worker.stop(timeout=0.1)

        message = " ".join(record.getMessage() for record in caplog.records)
        assert "call_id=7" in message
        assert "7.wav" in message
    finally:
        release.set()
        worker.stop(timeout=5.0)


def test_a_stop_that_times_out_does_not_let_a_second_worker_start():
    """전사는 최대 10분까지 걸릴 수 있는데 종료 대기는 30초다. 그래서 전사가
    도는 중에 서버를 내리면 join은 거의 매번 시간 초과한다.

    그때 스레드 참조를 지우면 다음 start()가 같은 큐에 두 번째 워커를 붙이고,
    "워커는 하나, 처리는 직렬"이라는 이 클래스의 존재 이유가 사라진다. 같은
    어르신의 통화 순서가 뒤집혀도 아무 오류가 나지 않는다.
    """
    busy = threading.Event()
    release = threading.Event()

    def slow(wav_path):
        busy.set()
        assert release.wait(5.0), "테스트가 전사를 놓아주지 않았다"
        return "괜찮아요"

    worker = TranscriptionWorker(transcribe=slow, sink=lambda *a: None)
    worker.start()
    first = worker._thread
    try:
        worker.submit(1, _analysis(), Path("1.wav"))
        assert busy.wait(5.0), "워커가 일을 시작하지 않았다"

        # 전사가 아직 안 끝났으므로 join이 시간 초과한다.
        worker.stop(timeout=0.1)

        # 여기서 새 워커가 생기면 큐 하나에 스레드 둘이 붙는다.
        worker.start()
        assert worker._thread is first, "두 번째 워커가 생겼다"
    finally:
        release.set()
        worker.stop(timeout=5.0)


def test_a_call_with_nothing_recognised_still_gets_a_score():
    """인식은 성공했는데 알아들은 말이 없는 통화(빈 전사)는 실패가 아니다.

    이 경로가 막히면 어르신이 거의 말을 안 한 통화가 degraded로 빠져 점수가
    아예 안 나온다. 그런데 그 통화가 바로 가장 위험한 통화다 — 발화 비율
    35점과 침묵 25점이 동시에 치솟는 상황이라, 보호자가 가장 알아야 할 때
    아무 숫자도 못 보게 된다.

    부정어가 0인 것은 맞다. 말을 안 했으니 부정적인 말도 없었다.
    """
    worker, sink = run_worker(lambda wav_path: "")
    try:
        worker.submit(1, _analysis(), Path("1.wav"))
        sink.wait()
    finally:
        worker.stop()

    _, analysis = sink.results[0]
    assert analysis.degraded is False, analysis.degraded_reasons
    assert analysis.metrics.negative_word_count == 0
