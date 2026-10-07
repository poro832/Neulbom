"""Prosody(휴멜로) DIVE TTS 어댑터 — 기본으로 쓰는 음성 합성.

ClovaVoice와 같은 VoiceSynthesizer 규약을 구현한다. 전송 계층을 주입받으므로
키 없이도 규약 전체가 테스트로 검증된다.

**왜 이쪽인가.** 2026-09-25에 수업 계정의 Polly 권한 신청이 거부됐고, 학교가
대안으로 권한 프레소디가 이것이다. 따져 보니 대안이 아니라 더 나은 선택이다.

비용 — CLOVA Voice는 월 정액 약 ₩99,000이다. 프레소디는 Free ₩0(DIVE
10,000자), Starter ₩19,800(DIVE 66,666자)이다. Starter로 가도 5분의 1이다.
그리고 한도를 넘으면 **과금이 아니라 정지**다(종량제는 Enterprise만) — 공유
수업 계정에서 사고로 요금이 튈 길이 구조적으로 없다.

형식 — `outputFormat="pcm_8000"`은 헤더 없는 PCM16 LE 8kHz다. 규약이 요구하는
것과 정확히 같아서 wav 헤더를 풀 일이 없다. 전화망이 8kHz라 리샘플링도 없다.
`ulaw_8000`도 있지만 쓰지 않는다 — μ-law 인코딩은 이 규약 **밖**의 공용
경로에서 하고, 여기서 μ-law를 돌려주면 어댑터마다 형식이 달라진다.

목소리 — 화자가 114명이고 연령대(노년 포함)로 고를 수 있다. 어르신께 들려줄
목소리를 고를 수 있다는 뜻인데, 어느 목소리인지는 **들어 봐야** 안다. 그래서
기본값을 두지 않고 voice_name을 반드시 받는다.

**이 어댑터가 특별히 조심하는 것.** DIVE는 `outputFormat`에 모르는 값이 오면
거절하는 대신 조용히 `wav_48000`으로 바꾼다(API 문서에 그렇게 적혀 있다).
오타 하나로 48kHz wav가 PCM16 8kHz인 척 들어오고, 어르신은 잡음을 듣는데
우리 로그에는 아무것도 안 남는다. 그래서 응답 헤더로 실제 적용된 포맷을
확인한다 — 이 경로에서 조용히 틀리는 걸 막는 유일한 장치다.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Protocol

import httpx

from app.media.clova_voice import split_for_tts
from app.media.spoken_text import strip_unspoken

logger = logging.getLogger(__name__)

DIVE_URL = "https://api-console.humelo.net/api/v1/dive"

# 요청당 상한. 계정별로 다르게 걸 수 있고 별도 설정이 없으면 500 UTF-16
# code unit이다(API 문서). 넘기면 그 요청이 통째로 실패한다.
TTS_MAX_PIECE_CHARS = 500

# 한 턴 전체의 상한. 업체가 거는 값이 아니라 우리가 거는 값이다 — DIVE는
# 1자에 3크레딧이라 Free 한도가 월 10,000자다. LLM이 폭주해서 한 턴에
# 수천 자를 뱉으면 그 달 남은 통화가 통째로 조용해진다.
TTS_MAX_CHARS = 2_000

# pcm_* 로 고를 수 있는 값들. 여기 없는 값을 보내면 조용히 wav_48000이
# 되므로 호출 전에 막는다.
SUPPORTED_SAMPLE_RATES = frozenset({8000, 16000, 24000, 48000})

# 실제 적용된 포맷이 돌아오는 헤더. 우리가 보낸 것과 다르면 응답을 버린다.
OUTPUT_FORMAT_HEADER = "x-prosody-output-format"

DEFAULT_EMOTION = "neutral"

# 같은 문장을 다시 합성하지 않으려고 기억하는 개수. 고정 문구(되묻기 등)가
# 대부분이라 작아도 충분하다.
CACHE_MAX_ENTRIES = 64

# 무료 플랜의 월 글자 수(DIVE 1자 = 3크레딧, 월 30,000크레딧). 환경 변수
# PROSODY_MONTHLY_CHARS로 바꾼다(Starter는 66,666).
DEFAULT_MONTHLY_CHARS = 10_000

# 이 비율을 넘으면 경고한다. 넘기면 과금이 아니라 **정지**라서, 시연 날
# 갑자기 AI가 말을 못 하게 되는 걸 미리 알려야 한다.
USAGE_WARN_RATIO = 0.8


class _Shared:
    """프로세스 전체가 나눠 쓰는 기억과 사용량.

    **통화마다 새로 만들어지는 객체에 두면 안 된다.** 응답기와 이 어댑터는
    통화 하나마다 만들어지므로(stream_server가 통화마다 factory를 부른다),
    객체 안에 두면 통화가 끝날 때 기억도 사용량도 사라진다. 되묻기 같은
    고정 문구는 통화마다 같은 요청을 다시 보내고, 사용량은 한 통화 분만
    보인다.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cache: OrderedDict[tuple, bytes] = OrderedDict()
        self.chars_used = 0
        self.warned = False


_SHARED = _Shared()


def reset_shared_state() -> None:
    """테스트가 서로 새지 않게 비운다."""
    global _SHARED
    _SHARED = _Shared()

# 문장 사이에 업체가 넣는 무음(초). 기본값과 같은 값이지만 **명시적으로
# 보낸다** — 이 무음은 AI 오디오 안에 들어가고, AI 발화 길이는 지표의
# 분모다(통화 전체 − AI 발화). 업체 기본값에 맡기면 그쪽이 기본값을 바꾸는
# 날 우리 점수가 아무 배포 없이 움직인다. CALCULATOR_VERSION과 같은 성질이다.
DEFAULT_SENTENCE_SILENCE_SECONDS = 0.4


class Transport(Protocol):
    def __call__(
        self, url: str, *, headers: dict, json: dict, timeout: float
    ) -> tuple[bytes, dict]: ...


def _http_post(
    url: str, *, headers: dict, json: dict, timeout: float
) -> tuple[bytes, dict]:
    response = httpx.post(url, headers=headers, json=json, timeout=timeout)
    if response.status_code >= 400:
        # 본문에 E4201 같은 코드가 들어 있다. 이걸 버리면 로그에 400만 남아서
        # 목소리 이름이 틀린 건지 크레딧이 떨어진 건지(E4601/402) 알 수 없다.
        # 크레딧 소진은 특히 조용한 실패다 — 그날부터 AI가 말을 안 한다.
        logger.error(
            "Prosody 요청 실패 status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
    response.raise_for_status()
    return response.content, dict(response.headers)


class ProsodyVoice:
    """실제 합성. 자격 증명은 생성자로만 받는다 — 코드에 박지 않는다."""

    def __init__(
        self,
        api_key: str,
        *,
        voice_name: str,
        emotion: str = DEFAULT_EMOTION,
        # CLOVA와 부호 규약이 **반대**다. 헷갈리면 어르신께 이상한 속도로
        # 말하게 되므로 적어 둔다.
        #   CLOVA   speed  0=원음, 양수가 '느리게' (정수)
        #   Prosody speed  1.0=원음, 1보다 작으면 '느리게' (배율, 0.5~2.0)
        # 어르신께는 천천히 말하는 쪽이지만 얼마가 적당한지는 실제 통화를
        # 들어 봐야 안다. 지금은 중립(1.0)으로 둔다.
        speed: float = 1.0,
        pitch: int = 0,          # -6 ~ 6
        volume: int = 50,        # 1 ~ 100
        sentence_silence_seconds: float = DEFAULT_SENTENCE_SILENCE_SECONDS,
        transport: Transport = _http_post,
        timeout_seconds: float = 10.0,
        monthly_chars: int = DEFAULT_MONTHLY_CHARS,
    ) -> None:
        self._api_key = api_key
        self._monthly_chars = monthly_chars
        self._voice_name = voice_name
        self._emotion = emotion
        self._speed = speed
        self._pitch = pitch
        self._volume = volume
        self._sentence_silence = sentence_silence_seconds
        self._transport = transport
        self._timeout = timeout_seconds

    @property
    def voice_name(self) -> str:
        return self._voice_name

    def synthesize(self, text: str, sample_rate: int) -> bytes:
        if sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(
                f"지원하지 않는 샘플레이트다 — {sample_rate}. "
                f"가능한 값: {sorted(SUPPORTED_SAMPLE_RATES)}"
            )

        spoken = strip_unspoken(text)
        if not spoken:
            # 읽을 게 안 남았다. 불러 봐야 빈 소리를 받고 크레딧만 쓴다.
            logger.info("읽을 내용이 없어 합성을 건너뛴다 원문=%r", text)
            return b""

        if len(spoken) > TTS_MAX_CHARS:
            # 잘라서라도 말하는 편이 낫다. 다만 잘랐다는 사실을 남기지 않으면
            # 어르신이 문장 중간에서 끊기는 이유를 아무도 알 수 없다.
            logger.warning(
                "응답이 상한을 넘어 자른다 — %d자 → %d자", len(spoken), TTS_MAX_CHARS
            )
            spoken = spoken[:TTS_MAX_CHARS]

        # 같은 문장을 같은 설정으로 다시 합성하지 않는다. 되묻는 말이나 인사처럼
        # 고정된 문구가 통화마다, 턴마다 같은 요청을 만들고 글자 수도 그만큼
        # 쓴다. 무료 한도가 월 10,000자, 분당 5건이다.
        # 목소리, 감정, 속도 같은 설정이 다르면 다른 소리다 — 키에 넣지 않으면
        # 설정을 바꾼 뒤에도 예전 소리가 나온다.
        key = (
            self._voice_name, self._emotion, self._speed, self._pitch,
            self._volume, self._sentence_silence, sample_rate, spoken,
        )
        with _SHARED.lock:
            cached = _SHARED.cache.get(key)
            if cached is not None:
                _SHARED.cache.move_to_end(key)
                return cached

        # **문장마다 요청을 보내지 않는다.** 처음에는 CLOVA Voice 어댑터처럼
        # 문장 단위로 쪼개 보냈는데, 2026-10-06 첫 AI 대화 통화에서 한 턴이
        # 두세 요청이 되어 두 번째 턴에서 429(분당 5건)로 막혔다. DIVE는 문장
        # 사이 무음을 스스로 넣으므로(sentenceSilenceSec) 요청당 상한까지는
        # 한 번에 보낸다.
        pieces = _pack(split_for_tts(spoken, TTS_MAX_PIECE_CHARS), TTS_MAX_PIECE_CHARS)
        audio = b"".join(self._synthesize_one(piece, sample_rate) for piece in pieces)

        with _SHARED.lock:
            _SHARED.cache[key] = audio
            if len(_SHARED.cache) > CACHE_MAX_ENTRIES:
                _SHARED.cache.popitem(last=False)
        self._note_usage(sum(len(piece) for piece in pieces))
        return audio

    def _note_usage(self, chars: int) -> None:
        """이번에 실제로 요청한 글자 수와 서버 시작 후 누적을 남긴다.

        무료 한도가 월 10,000자이고 넘으면 정지다. 청구서나 콘솔을 보고서야
        알게 되면 늦으므로 통화마다 로그에 남긴다. 누적은 **서버를 켠 뒤**의
        값이다(재시작하면 0부터). 월 합계는 로그의 이 줄들을 더해 구한다.
        """
        with _SHARED.lock:
            _SHARED.chars_used += chars
            used = _SHARED.chars_used
            warn = (
                not _SHARED.warned
                and used >= self._monthly_chars * USAGE_WARN_RATIO
            )
            if warn:
                _SHARED.warned = True
        logger.info(
            "Prosody 합성 %d자 — 서버 시작 후 누적 %d자 (월 한도 %d자의 %d%%)",
            chars,
            used,
            self._monthly_chars,
            used * 100 // self._monthly_chars,
        )
        if warn:
            logger.warning(
                "Prosody 사용량이 월 한도의 %d%%를 넘었다 — 넘기면 다음 달까지 "
                "AI가 말을 못 한다. 플랜을 올리거나 시험을 줄일 것",
                int(USAGE_WARN_RATIO * 100),
            )

    def _synthesize_one(self, spoken: str, sample_rate: int) -> bytes:
        wanted = f"pcm_{sample_rate}"
        raw, headers = self._transport(
            DIVE_URL,
            headers={
                "X-API-Key": self._api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": spoken,
                "mode": "preset",
                "voiceName": self._voice_name,
                "emotion": self._emotion,
                "lang": "ko",
                "outputFormat": wanted,
                "rawData": True,
                "speed": self._speed,
                "pitch": self._pitch,
                "volume": self._volume,
                "sentenceSilenceSec": self._sentence_silence,
            },
            timeout=self._timeout,
        )
        _check_format(headers, wanted)
        return raw


def _pack(pieces: list[str], limit: int) -> list[str]:
    """문장 조각을 요청당 상한까지 이어 붙인다. 순서는 그대로다."""
    packed: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + 1 + len(piece) <= limit:
            current = f"{current} {piece}"
        else:
            if current:
                packed.append(current)
            current = piece
    if current:
        packed.append(current)
    return packed


def _check_format(headers: dict, wanted: str) -> None:
    """업체가 실제로 적용한 포맷이 우리가 요청한 것과 같은지 본다.

    DIVE는 모르는 outputFormat을 거절하지 않고 wav_48000으로 바꾼다. 그대로
    받아 들이면 48kHz wav가 PCM16 8kHz인 척 파이프라인에 들어가서, 어르신은
    잡음을 듣고 우리 지표에는 멀쩡한 숫자가 남는다. 헤더 대조가 그걸 막는
    유일한 장치다.

    헤더 이름은 대소문자를 가리지 않는다. 여기서 깐깐하게 굴면 사업자가
    소문자로 보내는 날 멀쩡한 응답이 전부 실패한다.
    """
    applied = None
    for name, value in headers.items():
        if name.lower() == OUTPUT_FORMAT_HEADER:
            applied = value.strip().lower()
            break

    if applied is None:
        raise ValueError(
            f"응답에 적용된 포맷이 없다 — {OUTPUT_FORMAT_HEADER} 헤더가 비었다. "
            f"{wanted}를 받았는지 확인할 수 없어 소리로 내보내지 않는다"
        )
    if applied != wanted:
        raise ValueError(
            f"요청과 다른 포맷이 왔다 — 요청 {wanted}, 응답 {applied}. "
            "DIVE는 모르는 포맷을 거절하지 않고 wav_48000으로 바꾼다"
        )
