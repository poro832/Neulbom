"""CLOVA Speech 단문 인식 어댑터 — 한 턴의 발화를 글로 옮긴다.

ClovaVoice와 같은 패턴이다. 전송 계층을 주입받으므로 NCP 키가 없어도 규약
전체가 테스트로 검증된다.

**gRPC 스트리밍을 쓰지 않는 이유.** CallSession이 StreamingVad로 발화 끝을
확정한 뒤에야 respond()를 부른다 — 한 턴이 이미 통째로 손에 있다. 스트리밍은
말하는 도중에 받아 가는 방식이라 우리 구조에서 얻을 게 없고, 대신 grpcio
의존성과 nest.proto 컴파일이 따라온다. REST 단문 인식이면 전송 계층만 주입해
키 없이 테스트할 수 있다.

**여기서 나온 전사는 점수에 쓰지 않는다.** 프레임이 어떻게 잘렸느냐에 따라
결과가 달라지므로 같은 통화를 다시 돌리면 부정 표현 개수가 흔들린다. 점수용
전사는 통화가 끝난 뒤 저장된 녹음으로 다시 만든다(설계 3.2). 이 전사는
대화를 이어 가기 위한 것이다.
"""

from __future__ import annotations

import io
import json
import logging
import wave
from typing import Protocol

import httpx
import numpy as np

logger = logging.getLogger(__name__)

# 단문 인식의 상한. 넘겨 보내면 요청이 통째로 실패한다.
STT_MAX_SECONDS = 60

# 인식 언어. 여러 개를 켜는 것보다 하나만 켜는 쪽이 인식률에 유리하다.
DEFAULT_LANGUAGE = "Kor"

_INT16_PEAK = 32767


class Transport(Protocol):
    def __call__(
        self, url: str, *, headers: dict, content: bytes, timeout: float
    ) -> bytes: ...


class SpeechToText(Protocol):
    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        """한 턴의 발화를 글로 옮긴다. 못 알아들었으면 빈 문자열."""
        ...


def _http_post(url: str, *, headers: dict, content: bytes, timeout: float) -> bytes:
    response = httpx.post(url, headers=headers, content=content, timeout=timeout)
    if response.status_code >= 400:
        # 본문에 사업자 오류 코드가 들어 있다. 버리면 로그에 상태 코드만 남아
        # 키가 틀린 건지 오디오가 긴 건지 포맷이 안 맞는 건지 알 수 없다.
        logger.error(
            "CLOVA Speech 요청 실패 status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
    response.raise_for_status()
    return response.content


def _short_stt_url(invoke_url: str) -> str:
    """단문 인식 주소는 Invoke URL 뒤가 아니라 **게이트웨이 주소 바로 아래**다.

    장문 인식은 `https://<게이트웨이>/external/v1/<앱ID>/<해시>/recognizer/upload`
    처럼 Invoke URL 전체를 쓰지만, 단문 인식은 공식 문서에
    `https://clovaspeech-gw.ncloud.com/recog/v1/stt`로 적혀 있다. 처음에는
    Invoke URL 뒤에 `/recog/v1/stt`를 붙였는데, 2026-10-06 첫 실통화에서 404가
    났다(경로가 `.../external/v1/<앱ID>/<해시>/recog/v1/stt`가 되어 존재하지
    않는다). 그래서 같은 환경 변수에서 스킴과 호스트만 가져온다.
    """
    from urllib.parse import urlsplit

    parts = urlsplit(invoke_url.strip())
    if not parts.scheme or not parts.netloc:
        # 주소 모양이 아니면 짐작하지 않고 예전 방식으로 둔다. 어차피 호출할 때
        # 실패하고 그 오류가 로그에 남는다.
        return f"{invoke_url.rstrip('/')}/recog/v1/stt"
    return f"{parts.scheme}://{parts.netloc}/recog/v1/stt"


class ClovaSpeech:
    """실제 인식. 자격 증명은 생성자로만 받는다 — 코드에 박지 않는다."""

    def __init__(
        self,
        invoke_url: str,
        secret_key: str,
        *,
        language: str = DEFAULT_LANGUAGE,
        transport: Transport = _http_post,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._url = _short_stt_url(invoke_url)
        self._secret_key = secret_key
        self._language = language
        self._transport = transport
        self._timeout = timeout_seconds

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        if audio.size == 0:
            # 빈 오디오를 보내도 최소 단위(15초)가 과금된다. 보낼 이유가 없다.
            return ""

        limit = sample_rate * STT_MAX_SECONDS
        if audio.size > limit:
            # 자르면 뒷부분을 잃지만, 넘겨 보내면 그 턴 전체를 잃는다.
            logger.warning(
                "발화가 단문 인식 상한을 넘어 자른다 — %.1f초 → %d초",
                audio.size / sample_rate,
                STT_MAX_SECONDS,
            )
            audio = audio[:limit]

        try:
            raw = self._transport(
                f"{self._url}?lang={self._language}",
                headers={
                    "X-CLOVASPEECH-API-KEY": self._secret_key,
                    "Content-Type": "application/octet-stream",
                },
                content=_wav_bytes(audio, sample_rate),
                timeout=self._timeout,
            )
        except Exception:
            # 한 턴 못 알아들은 것으로 처리한다. ConversationResponder가
            # 되묻기로 받아 주므로 통화는 이어진다.
            logger.exception("전사 요청 실패 — 이 턴은 못 알아들은 것으로 둔다")
            return ""

        return self._text_of(raw)

    def _text_of(self, raw: bytes) -> str:
        try:
            body = json.loads(raw)
        except (ValueError, TypeError):
            logger.error("전사 응답을 읽을 수 없다 body=%r", raw[:200])
            return ""

        # 과금은 15초 단위다 — 3초 발화도 15초로 청구된다. 턴이 짧고 잦은
        # 대화라 이 반올림이 비용을 지배하는데, 남기지 않으면 청구서를 보고
        # 나서야 알게 된다.
        quota = body.get("quota")
        if quota is not None:
            logger.info("전사 완료 — 과금 단위 %s초", quota)

        text = body.get("text")
        if not isinstance(text, str):
            logger.warning("전사 응답에 text가 없다 — 못 알아들은 것으로 둔다")
            return ""
        return text.strip()


def _wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """float32 오디오를 wav 컨테이너로 감싼다.

    raw PCM은 지원 포맷 목록에 없다. 헤더 없이 보내면 인식이 통째로 실패한다.

    범위를 넘는 표본은 잘라 낸다. 그냥 곱하면 정수가 뒤집혀(32768 → -32768)
    그 프레임만 폭발음이 되고, 인식은 그 구간을 잃는다. VAD가 넘겨주는
    오디오는 정규화돼 있지만 구간 경계에서 1을 살짝 넘는 표본이 나올 수 있다.
    """
    clipped = np.clip(audio, -1.0, 1.0)
    samples = (clipped * _INT16_PEAK).astype("<i2")

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()
