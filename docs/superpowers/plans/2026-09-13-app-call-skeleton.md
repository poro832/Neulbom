# 앱 채널 통화 골격 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 늘봄 앱에서 "AI 친구"를 누르면 말이 오가는 골격을 만든다 — 앱이 PCM을 보내면 서버가 발화 종료를 감지하고 응답 오디오를 되돌려준다.

**Architecture:** WebSocket 한 소켓에서 바이너리는 오디오, 텍스트는 제어 신호를 나른다. `StreamingVad`가 프레임을 받아 발화 종료를 알리고, `CallSession`이 그걸 구동하며 응답을 요청하고 원본을 누적한다. `CallSession`은 WebSocket을 모르므로 소켓 없이 테스트되고, 나중에 전화망(Asterisk AudioSocket)이 붙을 때 그대로 재사용된다.

**Tech Stack:** Python 3.11+ · numpy · FastAPI · uvicorn · pytest · 표준 라이브러리 `wave`

**Spec:** `docs/superpowers/specs/2026-09-13-app-call-design.md`

## Global Constraints

- **기존 테스트 34개가 매 태스크 후에도 통과해야 한다.** `python -m pytest -q` → `34 passed` 이상.
- 오디오 포맷은 **PCM16 mono 16000Hz little-endian**. 프레임은 20ms = 320샘플 = **640바이트**.
- 스트리밍 VAD 결과를 **위험 지표에 쓰지 않는다.** 지표는 통화 종료 후 녹음 전체에 기존 `segment_audio`를 돌려 낸다 (설계 3.2 재현성).
- 임계값 공식은 **하나만 존재한다.** `adaptive_threshold`를 배치와 스트리밍이 공유한다. 복사 금지.
- 새 코드는 `app/media/` 아래. 기존 `app/analysis/`는 Task 1의 이름 변경 외에 건드리지 않는다.
- 주석과 docstring은 한국어로, **무엇이 아니라 왜**를 적는다 (기존 코드 관례).

---

## File Structure

| 파일 | 책임 |
|---|---|
| `app/media/__init__.py` | 패키지 선언 |
| `app/media/streaming_vad.py` | 프레임 → 발화 종료 이벤트. 순수, 외부 의존 없음 |
| `app/media/responder.py` | `Responder` 규약 + `CannedResponder` + `beep` 헬퍼 |
| `app/media/session.py` | 한 통화의 상태 — 바이트 버퍼링, VAD 구동, 응답 요청, 원본 누적, wav 저장 |
| `app/media/ws_server.py` | FastAPI WebSocket 엔드포인트. 세션에 바이트만 옮김 |
| `tests/test_streaming_vad.py` | 합성 오디오로 VAD 검증 |
| `tests/test_call_session.py` | 가짜 Responder로 세션 검증 |
| `tests/test_ws_server.py` | TestClient 통합 |

### 스펙과 달라지는 점 하나

스펙 6장은 *"프레임이 쪼개져 와도 결과가 같다"* 테스트를 `StreamingVad` 항목에 넣어 뒀지만, **바이트 버퍼링은 `CallSession`의 책임**입니다. `StreamingVad`는 "프레임 하나 받아 판정" 한 가지만 합니다. 따라서 그 테스트는 Task 4(`CallSession`)에 둡니다. 검증 내용은 동일합니다.

---

### Task 0: 저장소 초기화와 의존성

지금 이 프로젝트는 git 저장소가 아니다. TDD는 단계마다 커밋해 되돌릴 수 있어야 하므로 먼저 초기화한다. `.gitignore`는 이미 있다.

**Files:**
- Create: (없음 — `git init`이 `.git/`을 만든다)
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: 없음
- Produces: `fastapi`, `uvicorn`, `httpx`가 설치된 환경. 이후 모든 태스크가 `git commit`을 쓸 수 있다.

- [ ] **Step 1: git 저장소인지 확인**

Run: `git rev-parse --show-toplevel`
Expected: `fatal: not a git repository` — 아니라면 이미 저장소이므로 Step 2~3을 건너뛴다.

- [ ] **Step 2: 초기화**

```bash
git init
git add -A
git status --short | head -20
```

`.gitignore`가 `__pycache__/`, `client/build/`, `client/android/app/google-services.json`을 막고 있는지 확인한다. `client/build/`의 150MB APK가 스테이징에 올라와 있으면 `.gitignore`가 안 먹은 것이므로 멈추고 원인을 찾는다.

- [ ] **Step 3: 첫 커밋**

```bash
git commit -m "chore: 저장소 초기화 — 안심케어 (분석 코어 34개 통과, 늘봄 앱)"
git branch -M main
git remote add origin https://github.com/poro832/Nulbom.git
```

리모트에 이미 커밋이 있으면 `git push`가 거부된다. 그때는 팀과 상의해 결정한다 — 빈 저장소라면 `git push -u origin main`.

- [ ] **Step 4: 서버 의존성 추가**

`pyproject.toml`을 이렇게 만든다.

```toml
[project]
name = "ansimcare"
version = "0.1.0"
description = "독거노인 AI 친구 전화 (안심케어) — 팀 공명"
requires-python = ">=3.11"
# VadSegmenter가 numpy를 쓰는데 선언이 빠져 있었다. 새로 받은 사람은 실행이 안 된다.
dependencies = [
    "numpy>=2.0",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    # TestClient의 WebSocket 지원이 httpx를 요구한다.
    "httpx>=0.27",
]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 5: 설치**

Run: `python -m pip install "fastapi>=0.115" "uvicorn[standard]>=0.30" "httpx>=0.27"`
Expected: 설치 성공. `python -c "import fastapi, httpx; print('ok')"` → `ok`

- [ ] **Step 6: 기존 테스트가 그대로인지 확인**

Run: `python -m pytest -q`
Expected: `34 passed`

- [ ] **Step 7: 커밋**

```bash
git add pyproject.toml
git commit -m "chore: 서버 의존성 선언 (numpy 누락 수정 + fastapi/uvicorn/httpx)"
```

---

### Task 1: `adaptive_threshold`를 공개로 올린다

`StreamingVad`가 같은 공식을 써야 한다. 복사하면 두 벌이 갈라지므로 이름만 바꿔 공유한다. 동작은 한 글자도 바뀌지 않는다.

**Files:**
- Modify: `app/analysis/vad_segmenter.py`
- Test: `tests/test_vad_segmenter.py` (기존 — 수정 없이 통과해야 함)

**Interfaces:**
- Consumes: 없음
- Produces: `app.analysis.vad_segmenter.adaptive_threshold(frame_rms: np.ndarray) -> float`

- [ ] **Step 1: 이름 변경**

`app/analysis/vad_segmenter.py`에서 `_adaptive_threshold`를 `adaptive_threshold`로 바꾼다. **정의부와 호출부 두 곳** 모두.

정의부 docstring에 공유 사실을 남긴다.

```python
def adaptive_threshold(frame_rms: np.ndarray) -> float:
    """잡음 바닥을 추정해 임계값을 정한다.

    하위 백분위를 잡음으로 보되, 통화 전체가 발화인 경우 잡음 추정이
    발화 수준까지 올라가 스스로를 지우므로 피크 대비 상한을 씌운다.

    배치(segment_audio)와 스트리밍(StreamingVad)이 이 함수를 공유한다.
    공식이 두 벌로 갈라지면 같은 오디오에 다른 판정이 나온다.
    """
    if frame_rms.size == 0:
        return DEFAULT_NOISE_FLOOR
    quiet = float(np.percentile(frame_rms, 10))
    peak = float(np.percentile(frame_rms, 95))
    noise = min(quiet, peak * _NOISE_PEAK_CAP)
    return max(DEFAULT_NOISE_FLOOR, noise * DEFAULT_NOISE_FACTOR)
```

호출부(`_speech_segments` 안):

```python
    threshold = (
        adaptive_threshold(frame_rms) if rms_threshold is None else rms_threshold
    )
```

- [ ] **Step 2: 옛 이름이 남아 있지 않은지 확인**

Run: `grep -rn "_adaptive_threshold" app/ tests/`
Expected: 출력 없음

- [ ] **Step 3: 기존 테스트가 전부 통과하는지 확인**

Run: `python -m pytest -q`
Expected: `34 passed`

- [ ] **Step 4: 커밋**

```bash
git add app/analysis/vad_segmenter.py
git commit -m "refactor: adaptive_threshold 공개 — 배치와 스트리밍이 공식을 공유한다"
```

---

### Task 2: StreamingVad

프레임을 순서대로 받아 발화 종료를 알린다. 외부 의존이 없어 합성 오디오만으로 전부 검증된다.

**Files:**
- Create: `app/media/__init__.py`, `app/media/streaming_vad.py`
- Test: `tests/test_streaming_vad.py`

**Interfaces:**
- Consumes: `app.analysis.vad_segmenter.adaptive_threshold` (Task 1)
- Produces:
  - `app.media.streaming_vad.SpeechEnded` — frozen dataclass, 필드 `start_ms: int`, `end_ms: int`
  - `app.media.streaming_vad.StreamingVad(sample_rate: int, frame_ms: int = 20, window_ms: int = 3000, end_of_turn_ms: int = 800, min_speech_ms: int = 100)`
  - `StreamingVad.frame_length: int` — 프레임당 샘플 수 (읽기 전용 속성)
  - `StreamingVad.push(frame: np.ndarray) -> SpeechEnded | None`
  - 상수 `DEFAULT_WINDOW_MS = 3000`, `DEFAULT_END_OF_TURN_MS = 800`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_streaming_vad.py`:

```python
"""StreamingVad — 프레임을 순서대로 받아 발화 종료를 알린다 (앱 통화 설계 2장).

배치 VadSegmenter와 목적이 다르다. 이쪽은 "지금 말이 끝났나?"만 빠르게
답하면 되고, 정확한 구간은 통화가 끝난 뒤 배치가 다시 낸다. 그래서
근사여도 되지만, 대신 아직 도착하지 않은 오디오의 백분위를 쓸 수 없다.
최근 3초만 들고 같은 공식을 다시 계산한다.
"""

import numpy as np

from app.media.streaming_vad import SpeechEnded, StreamingVad

SAMPLE_RATE = 16000
FRAME_MS = 20

# 회선 잡음 수준. 이건 발화가 아니다.
NOISE_RMS = 0.005
# 목소리가 작은 어르신. 잡음의 3배지만 절대값은 작다.
QUIET_SPEECH_RMS = 0.015


def build_audio(*spans, sample_rate=SAMPLE_RATE, noise_rms=0.0, seed=0):
    """('speech', 500, 0.3), ('silence', 1000) → float32 샘플.

    speech 항목의 세 번째 값은 진폭(= RMS, 교번 신호이므로).
    """
    rng = np.random.default_rng(seed)
    chunks = []
    for span in spans:
        kind, duration_ms = span[0], span[1]
        amplitude = span[2] if len(span) > 2 else 0.3
        count = int(sample_rate * duration_ms / 1000)
        chunk = np.zeros(count, dtype=np.float32)
        if kind == "speech":
            chunk[0::2] = amplitude
            chunk[1::2] = -amplitude
        chunks.append(chunk)
    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    if noise_rms > 0:
        audio = audio + rng.normal(0.0, noise_rms, len(audio)).astype(np.float32)
    return audio


def feed(vad, audio):
    """오디오를 프레임 단위로 밀어넣고 나온 이벤트를 모은다."""
    events = []
    length = vad.frame_length
    for start in range(0, len(audio) - length + 1, length):
        event = vad.push(audio[start : start + length])
        if event is not None:
            events.append(event)
    return events


def test_silence_only_yields_no_event():
    vad = StreamingVad(SAMPLE_RATE)

    assert feed(vad, build_audio(("silence", 2000))) == []


def test_line_noise_alone_is_not_speech():
    """잡음만 흐르는데 응답하면 어르신은 혼자 떠드는 AI를 듣게 된다."""
    vad = StreamingVad(SAMPLE_RATE)
    audio = build_audio(("silence", 3000), noise_rms=NOISE_RMS)

    assert feed(vad, audio) == []


def test_speech_then_long_silence_ends_the_turn():
    vad = StreamingVad(SAMPLE_RATE)
    audio = build_audio(("speech", 1000), ("silence", 1000))

    assert feed(vad, audio) == [SpeechEnded(start_ms=0, end_ms=1000)]


def test_short_gap_inside_speech_does_not_end_the_turn():
    """음절 사이 300ms 공백에서 끊고 들어가면 말을 자르게 된다."""
    vad = StreamingVad(SAMPLE_RATE)
    audio = build_audio(
        ("speech", 500), ("silence", 300), ("speech", 500), ("silence", 1000)
    )

    assert feed(vad, audio) == [SpeechEnded(start_ms=0, end_ms=1300)]


def test_quiet_elderly_voice_is_detected():
    """8kHz에서 찾은 그 버그의 16kHz 형제.

    고정 임계값이면 잡음의 3배인 작은 목소리를 통째로 놓친다.
    """
    vad = StreamingVad(SAMPLE_RATE)
    audio = build_audio(
        ("silence", 600),
        ("speech", 1000, QUIET_SPEECH_RMS),
        ("silence", 1000),
        noise_rms=NOISE_RMS,
    )

    events = feed(vad, audio)

    assert len(events) == 1
    assert events[0].start_ms == 600
    assert events[0].end_ms == 1600


def test_continuous_speech_does_not_erase_itself():
    """윈도우가 발화로 가득 차도 잡음 추정이 발화까지 올라가면 안 된다.

    _NOISE_PEAK_CAP이 스트리밍에서도 도는지 확인한다.
    """
    vad = StreamingVad(SAMPLE_RATE)
    audio = build_audio(("speech", 6000), ("silence", 1000))

    assert feed(vad, audio) == [SpeechEnded(start_ms=0, end_ms=6000)]


def test_click_shorter_than_min_speech_is_discarded():
    """60ms짜리 클릭음에 AI가 대꾸하면 안 된다."""
    vad = StreamingVad(SAMPLE_RATE)
    audio = build_audio(("silence", 200), ("speech", 60), ("silence", 1000))

    assert feed(vad, audio) == []


def test_two_turns_are_reported_separately():
    vad = StreamingVad(SAMPLE_RATE)
    audio = build_audio(
        ("speech", 500),
        ("silence", 1000),
        ("speech", 500),
        ("silence", 1000),
    )

    assert feed(vad, audio) == [
        SpeechEnded(start_ms=0, end_ms=500),
        SpeechEnded(start_ms=1500, end_ms=2000),
    ]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_streaming_vad.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.media'`

- [ ] **Step 3: 최소 구현을 쓴다**

`app/media/__init__.py`: 빈 파일.

`app/media/streaming_vad.py`:

```python
"""통화 중 "지금 말이 끝났나?"만 답하는 VAD (앱 통화 설계 2장).

배치 VadSegmenter와 나눠 둔 이유가 있다. 스트리밍 판정은 프레임 도착
타이밍에 따라 달라지므로, 이 결과를 위험 지표에 쓰면 설계 3.2의 재현성이
깨진다. 지표는 통화가 끝난 뒤 녹음 전체에 segment_audio를 다시 돌려 낸다.

임계값 공식은 배치와 공유한다(adaptive_threshold). 다만 배치는 전체 신호의
백분위를 쓰는데 스트리밍에는 아직 오지 않은 오디오가 있으므로, 최근
window_ms만 들고 매 프레임 다시 계산한다.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from app.analysis.vad_segmenter import (
    DEFAULT_FRAME_MS,
    DEFAULT_MIN_SPEECH_MS,
    adaptive_threshold,
)

# 잡음 바닥을 추정할 구간. 짧으면 발화 한 번에 윈도우가 가득 차고,
# 길면 환경 변화(TV가 켜짐)를 늦게 따라간다.
DEFAULT_WINDOW_MS = 3000

# 음절 사이 공백(300ms)보다 충분히 길어야 말을 자르지 않는다.
# 어르신은 천천히, 중간에 쉬면서 말씀하신다.
DEFAULT_END_OF_TURN_MS = 800


@dataclass(frozen=True)
class SpeechEnded:
    """한 턴의 발화가 끝났다. 시각은 통화 시작을 0으로 한다."""

    start_ms: int
    end_ms: int


class StreamingVad:
    def __init__(
        self,
        sample_rate: int,
        frame_ms: int = DEFAULT_FRAME_MS,
        window_ms: int = DEFAULT_WINDOW_MS,
        end_of_turn_ms: int = DEFAULT_END_OF_TURN_MS,
        min_speech_ms: int = DEFAULT_MIN_SPEECH_MS,
    ) -> None:
        self._frame_ms = frame_ms
        self._frame_length = int(sample_rate * frame_ms / 1000)
        self._end_of_turn_frames = max(1, end_of_turn_ms // frame_ms)
        self._min_speech_ms = min_speech_ms
        self._rms_window: deque[float] = deque(maxlen=max(1, window_ms // frame_ms))

        self._frame_index = 0
        self._speech_start: int | None = None
        self._last_voiced: int | None = None
        self._silence_run = 0

    @property
    def frame_length(self) -> int:
        return self._frame_length

    def push(self, frame: np.ndarray) -> SpeechEnded | None:
        rms = float(np.sqrt(np.mean(np.asarray(frame, dtype=np.float32) ** 2)))
        self._rms_window.append(rms)
        threshold = adaptive_threshold(
            np.asarray(self._rms_window, dtype=np.float32)
        )

        ended: SpeechEnded | None = None
        if rms >= threshold:
            if self._speech_start is None:
                self._speech_start = self._frame_index
            self._last_voiced = self._frame_index
            self._silence_run = 0
        elif self._speech_start is not None:
            self._silence_run += 1
            if self._silence_run >= self._end_of_turn_frames:
                ended = self._close_turn()

        self._frame_index += 1
        return ended

    def _close_turn(self) -> SpeechEnded | None:
        """턴을 닫는다. 너무 짧으면 클릭음으로 보고 버린다.

        end_of_turn_ms보다 짧은 정적은 애초에 여기 오지 않으므로, 배치가
        _bridge_short_gaps로 먼저 잇고 나서 거르는 순서가 여기서도 지켜진다.
        """
        assert self._speech_start is not None and self._last_voiced is not None
        start_ms = self._speech_start * self._frame_ms
        end_ms = (self._last_voiced + 1) * self._frame_ms

        self._speech_start = None
        self._last_voiced = None
        self._silence_run = 0

        if end_ms - start_ms < self._min_speech_ms:
            return None
        return SpeechEnded(start_ms=start_ms, end_ms=end_ms)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_streaming_vad.py -q`
Expected: `8 passed`

- [ ] **Step 5: 기존 테스트도 그대로인지 확인**

Run: `python -m pytest -q`
Expected: `42 passed` (기존 34 + 신규 8)

- [ ] **Step 6: 커밋**

```bash
git add app/media/__init__.py app/media/streaming_vad.py tests/test_streaming_vad.py
git commit -m "feat: StreamingVad — 롤링 윈도우로 발화 종료를 감지한다"
```

---

### Task 3: Responder 규약과 CannedResponder

CLOVA 자리를 규약으로 먼저 세운다. 골격에서는 고정 응답을 돌려주고, 나중에 `ClovaResponder`로 교체한다.

**Files:**
- Create: `app/media/responder.py`
- Test: `tests/test_responder.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `app.media.responder.Responder` — `Protocol`, 메서드 `respond(self, audio: np.ndarray, sample_rate: int) -> bytes`
  - `app.media.responder.CannedResponder(clips: Sequence[bytes])` — `respond`가 clips를 순환하며 돌려준다
  - `app.media.responder.beep(duration_ms: int, sample_rate: int, frequency_hz: int = 660) -> bytes` — PCM16 LE 바이트

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_responder.py`:

```python
"""Responder — 발화를 받아 응답 오디오를 돌려주는 자리.

골격에서는 고정 응답이다. CLOVA는 NCP 이용 신청이 끝나면 같은 규약으로
갈아끼운다. 규약을 먼저 세워 두는 이유가 그것이다.
"""

import numpy as np

from app.media.responder import CannedResponder, beep

SAMPLE_RATE = 16000


def test_beep_length_matches_duration():
    """PCM16 mono이므로 샘플당 2바이트."""
    pcm = beep(duration_ms=100, sample_rate=SAMPLE_RATE)

    assert len(pcm) == int(SAMPLE_RATE * 0.1) * 2


def test_beep_is_not_silence():
    pcm = beep(duration_ms=100, sample_rate=SAMPLE_RATE)
    samples = np.frombuffer(pcm, dtype="<i2")

    assert np.abs(samples).max() > 0


def test_canned_responder_cycles_through_clips():
    """응답이 매번 같으면 통화가 기계처럼 들린다."""
    responder = CannedResponder([b"\x01\x00", b"\x02\x00"])
    audio = np.zeros(320, dtype=np.float32)

    first = responder.respond(audio, SAMPLE_RATE)
    second = responder.respond(audio, SAMPLE_RATE)
    third = responder.respond(audio, SAMPLE_RATE)

    assert (first, second, third) == (b"\x01\x00", b"\x02\x00", b"\x01\x00")


def test_canned_responder_without_clips_returns_nothing():
    responder = CannedResponder([])
    audio = np.zeros(320, dtype=np.float32)

    assert responder.respond(audio, SAMPLE_RATE) == b""
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_responder.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.media.responder'`

- [ ] **Step 3: 최소 구현을 쓴다**

`app/media/responder.py`:

```python
"""어르신의 발화를 받아 들려줄 오디오를 돌려주는 자리.

골격에서는 고정 응답(beep)이다. CLOVA Speech → Studio → Voice로 가는
ClovaResponder가 같은 규약을 구현하면 CallSession은 한 글자도 안 바뀐다.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from typing import Protocol

import numpy as np


class Responder(Protocol):
    def respond(self, audio: np.ndarray, sample_rate: int) -> bytes:
        """한 턴의 발화를 받아 재생할 PCM16 LE 바이트를 돌려준다.

        빈 바이트는 "들려줄 것이 없음"을 뜻하며 오류가 아니다.
        """
        ...


def beep(duration_ms: int, sample_rate: int, frequency_hz: int = 660) -> bytes:
    """골격이 소리를 내는지 귀로 확인하기 위한 톤.

    실제 응답 음성은 ClovaResponder가 만든다. 여기서 wav 자산을 준비하면
    골격 단계에 불필요한 파일 의존이 생긴다.
    """
    count = int(sample_rate * duration_ms / 1000)
    amplitude = 8000  # 최대치(32767)의 약 1/4 — 놀라지 않을 크기
    samples = [
        int(amplitude * math.sin(2 * math.pi * frequency_hz * i / sample_rate))
        for i in range(count)
    ]
    return struct.pack(f"<{count}h", *samples)


class CannedResponder:
    """clips를 순환하며 돌려준다. 매번 같은 소리면 기계처럼 들린다."""

    def __init__(self, clips: Sequence[bytes]) -> None:
        self._clips = list(clips)
        self._index = 0

    def respond(self, audio: np.ndarray, sample_rate: int) -> bytes:
        if not self._clips:
            return b""
        clip = self._clips[self._index % len(self._clips)]
        self._index += 1
        return clip
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_responder.py -q`
Expected: `4 passed`

- [ ] **Step 5: 전체 확인**

Run: `python -m pytest -q`
Expected: `46 passed`

- [ ] **Step 6: 커밋**

```bash
git add app/media/responder.py tests/test_responder.py
git commit -m "feat: Responder 규약과 CannedResponder — CLOVA 자리를 먼저 세운다"
```

---

### Task 4: CallSession

한 통화의 상태를 갖는다. 바이트를 받아 프레임으로 잘라 VAD에 먹이고, 발화가 끝나면 응답을 요청하고, 원본을 누적했다가 wav로 저장한다. **WebSocket을 모른다.**

**Files:**
- Create: `app/media/session.py`
- Test: `tests/test_call_session.py`

**Interfaces:**
- Consumes: `StreamingVad`, `SpeechEnded` (Task 2) · `Responder` (Task 3)
- Produces:
  - `app.media.session.TextMessage` — frozen dataclass, 필드 `payload: dict`
  - `app.media.session.AudioMessage` — frozen dataclass, 필드 `pcm: bytes`
  - `app.media.session.Outgoing = TextMessage | AudioMessage`
  - `app.media.session.CallSession(call_id: str, sample_rate: int, responder: Responder, frame_ms: int = 20)`
  - `CallSession.push_audio(data: bytes) -> list[Outgoing]`
  - `CallSession.finish(directory: Path) -> Path` — wav를 쓰고 그 경로를 돌려준다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_call_session.py`:

```python
"""CallSession — 한 통화의 상태 (앱 통화 설계 3장).

WebSocket을 모른다. 바이트를 밀어넣고 나가야 할 메시지를 돌려받는 구조라
소켓 없이 전부 검증된다. 나중에 전화망(Asterisk AudioSocket)이 붙어도
프레임 출처만 다르고 이 클래스는 그대로 재사용된다.
"""

import struct
import wave

import numpy as np

from app.media.session import AudioMessage, CallSession, TextMessage

SAMPLE_RATE = 16000
FRAME_BYTES = 640  # 20ms × 16000Hz × 2bytes


class FakeResponder:
    """무엇이 언제 요청됐는지 기록한다."""

    def __init__(self, reply: bytes = b"\x10\x00") -> None:
        self.reply = reply
        self.calls: list[int] = []

    def respond(self, audio: np.ndarray, sample_rate: int) -> bytes:
        self.calls.append(len(audio))
        return self.reply


class BrokenResponder:
    def respond(self, audio: np.ndarray, sample_rate: int) -> bytes:
        raise RuntimeError("CLOVA가 죽었다")


def pcm16(*spans, sample_rate=SAMPLE_RATE):
    """('speech', 500), ('silence', 1000) → PCM16 LE 바이트."""
    values: list[int] = []
    for kind, duration_ms in spans:
        count = int(sample_rate * duration_ms / 1000)
        if kind == "speech":
            values.extend(9000 if i % 2 == 0 else -9000 for i in range(count))
        else:
            values.extend(0 for _ in range(count))
    return struct.pack(f"<{len(values)}h", *values)


def drain(session, data, chunk_bytes=FRAME_BYTES):
    """바이트를 chunk_bytes씩 나눠 밀어넣고 나온 메시지를 모은다."""
    out = []
    for start in range(0, len(data), chunk_bytes):
        out.extend(session.push_audio(data[start : start + chunk_bytes]))
    return out


def test_speech_end_produces_signal_then_audio():
    responder = FakeResponder()
    session = CallSession("c1", SAMPLE_RATE, responder)

    messages = drain(session, pcm16(("speech", 500), ("silence", 1000)))

    assert messages == [
        TextMessage({"type": "speech_end"}),
        AudioMessage(responder.reply),
    ]
    assert len(responder.calls) == 1


def test_silence_only_produces_nothing():
    session = CallSession("c1", SAMPLE_RATE, FakeResponder())

    assert drain(session, pcm16(("silence", 2000))) == []


def test_result_is_same_when_bytes_arrive_split_oddly():
    """WebSocket은 보낸 단위로 도착한다는 보장이 없다.

    버퍼링이 깨지면 조용히 어긋나므로 여기서 못 박는다.
    """
    audio = pcm16(("speech", 500), ("silence", 1000))

    aligned = drain(CallSession("c1", SAMPLE_RATE, FakeResponder()), audio)
    ragged = drain(CallSession("c2", SAMPLE_RATE, FakeResponder()), audio, 137)

    assert aligned == ragged


def test_responder_failure_does_not_kill_the_call():
    """응답 하나 실패했다고 통화를 끊으면 어르신은 영문을 모른다."""
    session = CallSession("c1", SAMPLE_RATE, BrokenResponder())

    messages = drain(session, pcm16(("speech", 500), ("silence", 1000)))

    assert messages == [TextMessage({"type": "speech_end"})]


def test_finish_writes_the_whole_call_as_wav(tmp_path):
    session = CallSession("c1", SAMPLE_RATE, FakeResponder())
    audio = pcm16(("speech", 500), ("silence", 1000))
    drain(session, audio)

    path = session.finish(tmp_path)

    assert path == tmp_path / "c1.wav"
    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == SAMPLE_RATE
        assert wav.readframes(wav.getnframes()) == audio


def test_finish_without_audio_still_writes_a_file(tmp_path):
    """앱이 곧바로 끊겨도 통화 기록이 사라지면 안 된다."""
    session = CallSession("c1", SAMPLE_RATE, FakeResponder())

    path = session.finish(tmp_path)

    assert path.exists()
    with wave.open(str(path), "rb") as wav:
        assert wav.getnframes() == 0


def test_incomplete_trailing_bytes_are_kept_for_the_next_push(tmp_path):
    """640바이트에 못 미치는 꼬리를 버리면 오디오에 구멍이 생긴다."""
    session = CallSession("c1", SAMPLE_RATE, FakeResponder())
    audio = pcm16(("speech", 500), ("silence", 1000))

    session.push_audio(audio[:100])
    session.push_audio(audio[100:])
    path = session.finish(tmp_path)

    with wave.open(str(path), "rb") as wav:
        assert wav.readframes(wav.getnframes()) == audio
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_call_session.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.media.session'`

- [ ] **Step 3: 최소 구현을 쓴다**

`app/media/session.py`:

```python
"""한 통화의 상태. 전송 수단을 모른다 (앱 통화 설계 3장).

바이트를 받아 나가야 할 메시지를 돌려주는 구조라 소켓 없이 테스트된다.
전화망 채널(Asterisk AudioSocket)이 붙을 때도 프레임 출처만 다르고
이 클래스는 그대로 재사용된다.
"""

from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.analysis.vad_segmenter import DEFAULT_FRAME_MS
from app.media.responder import Responder
from app.media.streaming_vad import StreamingVad

logger = logging.getLogger(__name__)

_BYTES_PER_SAMPLE = 2
_INT16_FULL_SCALE = 32768.0


@dataclass(frozen=True)
class TextMessage:
    """제어 신호. 소켓에서는 텍스트 프레임으로 나간다."""

    payload: dict


@dataclass(frozen=True)
class AudioMessage:
    """재생할 오디오. 소켓에서는 바이너리 프레임으로 나간다."""

    pcm: bytes


Outgoing = TextMessage | AudioMessage


class CallSession:
    def __init__(
        self,
        call_id: str,
        sample_rate: int,
        responder: Responder,
        frame_ms: int = DEFAULT_FRAME_MS,
    ) -> None:
        self._call_id = call_id
        self._sample_rate = sample_rate
        self._responder = responder
        self._vad = StreamingVad(sample_rate, frame_ms=frame_ms)
        self._frame_bytes = self._vad.frame_length * _BYTES_PER_SAMPLE

        # 640바이트에 못 미치는 꼬리. 버리면 오디오에 구멍이 생긴다.
        self._pending = b""
        self._recorded = bytearray()

    @property
    def call_id(self) -> str:
        return self._call_id

    def push_audio(self, data: bytes) -> list[Outgoing]:
        self._recorded.extend(data)
        self._pending += data

        outgoing: list[Outgoing] = []
        while len(self._pending) >= self._frame_bytes:
            chunk = self._pending[: self._frame_bytes]
            self._pending = self._pending[self._frame_bytes :]
            ended = self._vad.push(_to_float32(chunk))
            if ended is not None:
                outgoing.extend(self._on_speech_end(ended.start_ms, ended.end_ms))
        return outgoing

    def finish(self, directory: Path) -> Path:
        """누적한 원본을 wav로 남긴다.

        앱이 갑자기 끊겨도 호출된다. 통화 기록이 사라지면 안 된다.
        """
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self._call_id}.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(_BYTES_PER_SAMPLE)
            wav.setframerate(self._sample_rate)
            wav.writeframes(bytes(self._recorded))
        return path

    def _on_speech_end(self, start_ms: int, end_ms: int) -> list[Outgoing]:
        outgoing: list[Outgoing] = [TextMessage({"type": "speech_end"})]

        start = int(start_ms * self._sample_rate / 1000) * _BYTES_PER_SAMPLE
        end = int(end_ms * self._sample_rate / 1000) * _BYTES_PER_SAMPLE
        turn = _to_float32(bytes(self._recorded[start:end]))

        try:
            reply = self._responder.respond(turn, self._sample_rate)
        except Exception:
            # 응답 하나 실패했다고 통화를 끊으면 어르신은 영문을 모른다.
            logger.exception("응답 생성 실패 — 통화는 유지한다 call_id=%s", self._call_id)
            return outgoing

        if reply:
            outgoing.append(AudioMessage(reply))
        return outgoing


def _to_float32(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / _INT16_FULL_SCALE
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_call_session.py -q`
Expected: `7 passed`

- [ ] **Step 5: 전체 확인**

Run: `python -m pytest -q`
Expected: `53 passed`

- [ ] **Step 6: 커밋**

```bash
git add app/media/session.py tests/test_call_session.py
git commit -m "feat: CallSession — 바이트 버퍼링·응답 요청·원본 누적. 전송 수단을 모른다"
```

---

### Task 5: WebSocket 어댑터

소켓과 세션 사이에서 바이트만 옮긴다. 로직은 전부 `CallSession`에 있으므로 이 파일은 얇다.

**Files:**
- Create: `app/media/ws_server.py`
- Test: `tests/test_ws_server.py`

**Interfaces:**
- Consumes: `CallSession`, `TextMessage`, `AudioMessage` (Task 4) · `CannedResponder`, `beep` (Task 3)
- Produces:
  - `app.media.ws_server.app` — `FastAPI` 인스턴스
  - WebSocket 엔드포인트 `/v1/app-call`
  - `app.media.ws_server.RECORDINGS_DIR: Path` — 기본 `Path("recordings")`
  - `app.media.ws_server.EXPECTED_SAMPLE_RATE: int = 16000`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_ws_server.py`:

```python
"""WebSocket 어댑터 — 소켓과 CallSession 사이에서 바이트만 옮긴다.

바이너리는 소리, 텍스트는 신호. 로직은 CallSession에 있으므로
여기서는 배관이 맞물리는지만 본다.
"""

import struct

import pytest
from fastapi.testclient import TestClient

from app.media import ws_server

SAMPLE_RATE = 16000


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_server, "RECORDINGS_DIR", tmp_path)
    return TestClient(ws_server.app)


def pcm16(*spans, sample_rate=SAMPLE_RATE):
    values: list[int] = []
    for kind, duration_ms in spans:
        count = int(sample_rate * duration_ms / 1000)
        if kind == "speech":
            values.extend(9000 if i % 2 == 0 else -9000 for i in range(count))
        else:
            values.extend(0 for _ in range(count))
    return struct.pack(f"<{len(values)}h", *values)


def test_speech_round_trip_returns_signal_and_audio(client):
    with client.websocket_connect("/v1/app-call") as ws:
        ws.send_json({"type": "start", "sample_rate": SAMPLE_RATE})
        ws.send_bytes(pcm16(("speech", 500), ("silence", 1000)))

        assert ws.receive_json() == {"type": "speech_end"}
        assert len(ws.receive_bytes()) > 0

        ws.send_json({"type": "end"})


def test_call_is_saved_as_wav(client, tmp_path):
    with client.websocket_connect("/v1/app-call") as ws:
        ws.send_json({"type": "start", "sample_rate": SAMPLE_RATE})
        ws.send_bytes(pcm16(("silence", 100)))
        ws.send_json({"type": "end"})

    assert list(tmp_path.glob("*.wav"))


def test_wrong_sample_rate_is_rejected(client):
    """조용히 틀린 결과를 내느니 연결을 거부한다."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/v1/app-call") as ws:
            ws.send_json({"type": "start", "sample_rate": 8000})
            ws.receive_bytes()
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_ws_server.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.media.ws_server'`

- [ ] **Step 3: 최소 구현을 쓴다**

`app/media/ws_server.py`:

```python
"""앱 채널 WebSocket 엔드포인트 (앱 통화 설계 4장).

한 소켓에서 바이너리는 소리, 텍스트는 신호를 나른다. 로직은 전부
CallSession에 있으므로 이 파일은 배관만 한다.

실행: uvicorn app.media.ws_server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.media.responder import CannedResponder, beep
from app.media.session import AudioMessage, CallSession, TextMessage

logger = logging.getLogger(__name__)

app = FastAPI(title="늘봄 앱 채널")

RECORDINGS_DIR = Path("recordings")
EXPECTED_SAMPLE_RATE = 16000

# 정책 위반이 아니라 프로토콜 불일치이므로 1003(Unsupported Data).
_UNSUPPORTED_DATA = 1003


def _build_responder() -> CannedResponder:
    """골격의 고정 응답. CLOVA가 붙으면 이 함수만 바뀐다."""
    return CannedResponder(
        [
            beep(duration_ms=200, sample_rate=EXPECTED_SAMPLE_RATE, frequency_hz=660),
            beep(duration_ms=200, sample_rate=EXPECTED_SAMPLE_RATE, frequency_hz=880),
        ]
    )


@app.websocket("/v1/app-call")
async def app_call(websocket: WebSocket) -> None:
    await websocket.accept()

    # start가 올 때까지 오디오는 버린다. 순서가 뒤집혀 도착하면
    # 샘플레이트를 모르는 채로 바이트를 해석하게 된다.
    while True:
        first = await websocket.receive()
        if first["type"] == "websocket.disconnect":
            return
        if (text := first.get("text")) is not None:
            break

    if json.loads(text).get("sample_rate") != EXPECTED_SAMPLE_RATE:
        # 조용히 틀린 결과를 내느니 거부한다.
        await websocket.close(code=_UNSUPPORTED_DATA)
        return

    session = CallSession(uuid.uuid4().hex, EXPECTED_SAMPLE_RATE, _build_responder())
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if (payload := message.get("bytes")) is not None:
                for outgoing in session.push_audio(payload):
                    if isinstance(outgoing, TextMessage):
                        await websocket.send_json(outgoing.payload)
                    elif isinstance(outgoing, AudioMessage):
                        await websocket.send_bytes(outgoing.pcm)
            elif (text := message.get("text")) is not None and '"end"' in text:
                break
    except WebSocketDisconnect:
        # 앱이 갑자기 끊겼다. 아래 finally에서 녹음을 남긴다.
        logger.info("앱이 연결을 끊었다 call_id=%s", session.call_id)
    finally:
        session.finish(RECORDINGS_DIR)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_ws_server.py -q`
Expected: `3 passed`

- [ ] **Step 5: 전체 확인**

Run: `python -m pytest -q`
Expected: `56 passed`

- [ ] **Step 6: 손으로 한 번 띄워 본다**

Run: `python -m uvicorn app.media.ws_server:app --port 8000`
Expected: `Uvicorn running on http://127.0.0.1:8000` — 확인 후 Ctrl+C

- [ ] **Step 7: 커밋**

```bash
git add app/media/ws_server.py tests/test_ws_server.py
git commit -m "feat: 앱 채널 WebSocket 엔드포인트 — 골격 완성"
```

---

## 완료 기준

- `python -m pytest -q` → **56 passed** (기존 34 + 신규 22)
- `uvicorn app.media.ws_server:app`로 서버가 뜬다
- 앱이 `start` → PCM → `end`를 보내면 `speech_end`와 응답 오디오가 돌아오고, `recordings/*.wav`에 통화 원본이 남는다

## 이번 계획 밖 (설계 8장)

- 앱 `calling_screen.dart`에 마이크 캡처 붙이기 — 서버가 선 다음
- 저장된 wav → 배치 VAD → `MetricsCalculator` → DB
- `ClovaResponder`
- barge-in (`stop_playback` 송신)
