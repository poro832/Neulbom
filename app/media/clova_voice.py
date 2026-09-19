"""CLOVA Voice TTS 어댑터 — 텍스트를 통화에 실을 PCM으로 바꾼다.

Telephony/Responder와 같은 패턴이다. 전송 계층을 주입받으므로 NCP 키가
없어도 규약 전체가 테스트로 검증된다.

전화망이 8kHz라서 운이 좋았다. CLOVA Voice는 `format=wav`일 때
`sampling-rate=8000`을 직접 지원하므로 리샘플링이 한 번도 필요 없다 —
받은 PCM을 ulaw 인코더에 그대로 먹이면 된다. (STT 쪽은 반대로 16kHz만
받아서 업샘플링이 필요하다.)

**TTS 설정은 점수에 영향을 준다.** speed를 바꾸면 AI 발화 길이가 바뀌고,
그러면 지표의 분모(통화 전체 − AI 발화)가 바뀌어 발화 비율이 달라진다.
CALCULATOR_VERSION과 같은 성질이라, 실통화를 시작하기 전에 정하고 결과에
함께 기록해야 한다. 지금 튜닝하지 않고 중립값으로 둔다 — 근거가 될 통화가
아직 하나도 없다.
"""

from __future__ import annotations

import io
import logging
import re
import wave
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

TTS_URL = "https://naveropenapi.apigw.ntruss.com/tts-premium/v1/tts"

# 한국어 기준 상한. 넘기면 요청이 통째로 실패한다.
TTS_MAX_CHARS = 2_000

# 전체 길이와 **별개로** 문장당 상한이 있다(오류 VS18). 총 길이가 상한 안이어도
# 한 문장이 여기를 넘으면 요청 전체가 실패하고, 그 턴은 소리가 안 나서
# 어르신은 침묵을 듣는다. LLM이 쉼표로 길게 이어 붙인 문장을 뱉으면 바로
# 걸리는 자리다.
TTS_MAX_SENTENCE_CHARS = 200

# wav 형식에서만 고를 수 있는 값들. 여기 없는 값을 보내면 거절당하므로
# 호출 전에 막는다 — 실패한 요청도 왕복 시간은 쓴다.
SUPPORTED_SAMPLE_RATES = frozenset({8000, 16000, 24000, 48000})

# 전화 상담용으로 튜닝된 목소리. 우리는 전화 서비스라 이걸 기본으로 둔다.
# 앱 이름과 같은 "napple"(늘봄)도 있다 — 실제 통화를 들어 보고 고른다.
DEFAULT_SPEAKER = "nara_call"

# CLOVA는 괄호 안 텍스트를 읽지 않는다. 오류도 없이 그냥 사라진다.
# 우리가 먼저 지워야 "보낸 것"과 "들린 것"이 같아진다.
_BRACKETED = re.compile(r"[(\[{][^)\]}]*[)\]}]")

# 문장 끝. 뒤의 공백까지 함께 먹어 조각에 앞 공백이 남지 않게 한다.
_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+")

# 문장 하나가 그래도 길면 쉼표에서 한 번 더 끊는다. 말의 호흡과 맞는
# 자리라 소리가 어색해지지 않는다.
_CLAUSE_END = re.compile(r"(?<=[,、;:])\s*")


class Transport(Protocol):
    def __call__(
        self, url: str, *, headers: dict, data: dict, timeout: float
    ) -> bytes: ...


class VoiceSynthesizer(Protocol):
    def synthesize(self, text: str, sample_rate: int) -> bytes:
        """텍스트를 PCM16 LE 바이트로 바꾼다.

        빈 바이트는 "들려줄 것이 없음"이며 오류가 아니다 — Responder 규약과
        같은 뜻이다.
        """
        ...


def strip_unspoken(text: str) -> str:
    """읽히지 않을 부분을 미리 없앤다.

    괄호 안 내용만 지운다. 문장부호는 억양에 쓰이므로 남긴다. 다른 기호도
    CLOVA가 읽지 않지만 소리에 영향을 주지 않아 굳이 손대지 않는다 —
    과하게 지우면 진짜 할 말이 사라진다.
    """
    return " ".join(_BRACKETED.sub(" ", text).split())


def split_for_tts(text: str, limit: int = TTS_MAX_SENTENCE_CHARS) -> list[str]:
    """문장당 상한에 맞게 쪼갠다. 잘라 버리지 않고 전부 말한다.

    문장 → 절 → (그래도 길면) 글자 수 순으로 끊는다. 앞의 두 단계는 말의
    호흡과 맞는 자리라 이어 붙여도 어색하지 않다. 마지막은 최후 수단이다 —
    구두점이 하나도 없는 250자짜리 발화도 소리는 나야 한다.
    """
    pieces: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= limit:
            pieces.append(sentence)
            continue
        for clause in _CLAUSE_END.split(sentence):
            clause = clause.strip()
            if not clause:
                continue
            while len(clause) > limit:
                pieces.append(clause[:limit])
                clause = clause[limit:]
            if clause:
                pieces.append(clause)
    return pieces


def _http_post(url: str, *, headers: dict, data: dict, timeout: float) -> bytes:
    response = httpx.post(url, headers=headers, data=data, timeout=timeout)
    if response.status_code >= 400:
        # 본문에 VS01~VS99 코드와 메시지가 들어 있다. 이걸 버리면 로그에는
        # 400만 남아서, speaker 이름이 틀린 건지(VS02) 문장이 긴 건지(VS18)
        # 합성 자체가 실패한 건지(VS26) 구분할 수 없다.
        logger.error(
            "CLOVA Voice 요청 실패 status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
    response.raise_for_status()
    return response.content


class ClovaVoice:
    """실제 합성. 자격 증명은 생성자로만 받는다 — 코드에 박지 않는다."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        speaker: str = DEFAULT_SPEAKER,
        # 아래 셋은 CLOVA의 부호 규약을 그대로 쓴다. 헷갈리기 쉬워 적어 둔다.
        #   speed  -5=2배 빠름  0=원음  10=0.5배 느림   ← 양수가 '느리게'다
        #   pitch  -5=높게      0=정상   5=낮게         ← 양수가 '낮게'다
        #   volume -5=작게      0=정상   5=크게         ← 이것만 직관대로다
        # 어르신께는 천천히 말해야 하므로 speed는 양수 쪽이지만, 얼마가
        # 적당한지는 실제 통화를 들어 봐야 안다. 지금은 중립으로 둔다.
        speed: int = 0,
        pitch: int = 0,
        volume: int = 0,
        transport: Transport = _http_post,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._speaker = speaker
        self._speed = speed
        self._pitch = pitch
        self._volume = volume
        self._transport = transport
        self._timeout = timeout_seconds

    def synthesize(self, text: str, sample_rate: int) -> bytes:
        if sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(
                f"지원하지 않는 샘플레이트다 — {sample_rate}. "
                f"가능한 값: {sorted(SUPPORTED_SAMPLE_RATES)}"
            )

        spoken = strip_unspoken(text)
        if not spoken:
            # 읽을 게 안 남았다. 호출해 봐야 빈 소리를 받고 요금만 쓴다.
            logger.info("읽을 내용이 없어 합성을 건너뛴다 원문=%r", text)
            return b""

        if len(spoken) > TTS_MAX_CHARS:
            # 잘라서라도 말하는 편이 낫다. 다만 잘랐다는 사실을 남기지 않으면
            # 어르신이 문장 중간에서 끊기는 이유를 아무도 알 수 없다.
            logger.warning(
                "응답이 상한을 넘어 자른다 — %d자 → %d자", len(spoken), TTS_MAX_CHARS
            )
            spoken = spoken[:TTS_MAX_CHARS]

        pieces = split_for_tts(spoken)
        return b"".join(self._synthesize_one(p, sample_rate) for p in pieces)

    def _synthesize_one(self, spoken: str, sample_rate: int) -> bytes:
        raw = self._transport(
            TTS_URL,
            headers={
                "X-NCP-APIGW-API-KEY-ID": self._client_id,
                "X-NCP-APIGW-API-KEY": self._client_secret,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "speaker": self._speaker,
                "text": spoken,
                "speed": self._speed,
                "pitch": self._pitch,
                "volume": self._volume,
                "format": "wav",
                "sampling-rate": sample_rate,
            },
            timeout=self._timeout,
        )
        return _pcm_from_wav(raw, sample_rate)


def _pcm_from_wav(raw: bytes, expected_rate: int) -> bytes:
    """wav에서 PCM 프레임만 꺼낸다.

    헤더를 44바이트로 가정하고 잘라내면 안 된다. RIFF는 청크 구조라 길이가
    고정이 아니고, 청크가 하나만 더 붙어도 오디오 앞부분을 먹거나 헤더
    꼬리를 소리로 내보낸다.
    """
    with wave.open(io.BytesIO(raw), "rb") as source:
        rate = source.getframerate()
        if rate != expected_rate:
            # 그대로 재생하면 목소리가 빨라지거나 느려진다. 어르신은 이상한
            # 소리를 듣는데 우리 지표에는 아무 표시도 남지 않는다.
            raise ValueError(
                f"요청과 다른 샘플레이트가 왔다 — 요청 {expected_rate}, 응답 {rate}"
            )
        return source.readframes(source.getnframes())
