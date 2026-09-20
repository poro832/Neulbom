"""CLOVA Speech 장문 인식 어댑터 — 통화 녹음 전체를 글로 바꾼다.

단문 인식(clova_speech.py)과 사업자도 도메인도 같지만 쓰임이 다르다. 단문은
통화 중 한 턴을 알아듣는 데 쓰고, 이쪽은 통화가 끝난 뒤 녹음 전체를 한 번에
전사해 부정 표현을 세는 데 쓴다.

**왜 통화 전체를 한 번에 보내는가.** 부정 표현은 문맥이 전부다. 구간을 잘라
따로 보내면 경계가 "안"과 "아파요" 사이에 떨어질 수 있고, 그러면 뜻이 정반대로
뒤집힌다. metrics_calculator가 공들여 잡아 둔 부정 범위 규칙이 조각 위에서는
돌지 않는다.

**폴링이 없다.** 처음에는 제출 후 상태를 물어보는 비동기 API로 알았으나,
사업자 문서에 폴링 엔드포인트가 없다. async는 콜백이나 Object Storage로만
결과를 주고 토큰으로 가져오는 방법이 없다. 그래서 completion="sync"를 쓴다 —
요청 하나로 끝난다. 다만 그 요청이 1~2분 걸리므로 통화 종료 경로에서 부르면
안 된다. 그 일은 TranscriptionWorker가 한다.

**인식 옵션을 전부 명시해서 보낸다.** fullText, wordAlignment, noiseFiltering,
diarization.enable이 모두 기본값 True다. 안 보내면 켜진 채로 돈다. 사업자가
언젠가 기본값을 바꾸면 우리 점수가 아무 신호 없이 바뀌므로, 입력의 생성
조건을 사업자 기본값에 맡겨 두지 않는다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.transcription import TranscriptionFailed, TranscriptionUnavailable

logger = logging.getLogger(__name__)

# 한 통화에 쓰는 전체 예산이다. 5분 통화 전사가 보통 1~2분이니 넉넉하고,
# 이걸 넘기면 늦는 게 아니라 잘못된 것이다(설계 5장).
DEFAULT_TIMEOUT_SECONDS = 600.0

# 단문은 쿼리 lang="Kor", 장문은 params.language="ko-KR"이다. 같은 사업자의
# 같은 제품인데 다르다 — 단문 어댑터를 보고 짐작하면 틀린다.
LANGUAGE = "ko-KR"


def _http_transport(url: str, *, headers: dict, files: dict, timeout: float) -> bytes:
    import httpx

    response = httpx.post(url, headers=headers, files=files, timeout=timeout)
    response.raise_for_status()
    return response.content


class ClovaLongSpeech:
    def __init__(
        self,
        *,
        invoke_url: str,
        secret_key: str,
        transport=None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._invoke_url = invoke_url.rstrip("/")
        self._secret_key = secret_key
        self._transport = transport if transport is not None else _http_transport
        self._timeout = timeout

    def transcribe(self, wav_path: Path) -> str:
        try:
            audio = Path(wav_path).read_bytes()
        except OSError as exc:
            # 녹음이 없는데 보내면 돈만 쓰고 실패한다. 다시 보내도 파일은
            # 돌아오지 않으므로 재시도 대상이 아니다.
            raise TranscriptionFailed(f"녹음을 읽을 수 없다 — {wav_path}") from exc

        params = {
            "language": LANGUAGE,
            "completion": "sync",
            "fullText": True,
            # 우리가 쓰는 건 루트 text 하나뿐이다. 단어 단위 정렬은 응답만 키운다.
            "wordAlignment": False,
            # 전화 통화는 잡음이 많다. 끄면 인식률이 떨어진다.
            "noiseFiltering": True,
            # 기본값이 True다. 반드시 끈다(설계 10장).
            "diarization": {"enable": False},
        }
        files = {
            "media": (Path(wav_path).name, audio, "audio/wav"),
            "params": (None, json.dumps(params, ensure_ascii=False), "application/json"),
        }

        try:
            raw = self._transport(
                f"{self._invoke_url}/recognizer/upload",
                headers={"X-CLOVASPEECH-API-KEY": self._secret_key},
                files=files,
                timeout=self._timeout,
            )
        except (TranscriptionFailed, TranscriptionUnavailable):
            # 전송 계층이 이미 분류해 올린 것은 그대로 통과시킨다. 다시 감싸면
            # 영구 실패가 재시도 가능으로 뒤집힌다.
            raise
        except (ImportError, TypeError, AttributeError) as exc:
            # 우리 쪽 배선 결함이거나 환경 문제다. 다시 보내도 영원히 같은
            # 결과가 나오므로 재시도 대상이 아니다 — 재시도로 분류하면 워커가
            # 세 번 시도하고 통화를 접는데, 로그에는 "연결 실패"만 남아 진짜
            # 원인이 묻힌다.
            raise TranscriptionFailed(f"전사를 부를 수 없는 상태다 — {exc!r}") from exc
        except Exception as exc:
            # 요청이 닿지 않았다. 빠르게 돌아오고 잠깐 끊긴 네트워크가 원인일
            # 수 있으므로 워커가 다시 해볼 수 있게 구분해서 올린다.
            raise TranscriptionUnavailable(f"전사를 부르지 못했다 — {exc}") from exc

        try:
            body = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise TranscriptionFailed(f"전사 응답을 읽을 수 없다 — {raw[:200]!r}") from exc

        if not isinstance(body, dict):
            raise TranscriptionFailed(f"전사 응답이 객체가 아니다 — {raw[:200]!r}")

        text = body.get("text")
        if not isinstance(text, str) or not text:
            # HTTP는 200인데 본문이 실패인 경우가 있다. 빈 문자열을 돌려주면
            # "부정어가 없었다"와 "전사가 실패했다"가 같은 값이 되어, 점수
            # 20점이 조용히 0으로 들어간다. text가 문자열이 아닌 경우(사업자가
            # 숫자나 리스트를 줄 수 있다)도 같은 실패다 — 아래 len()이나
            # count_negative_words가 그 값을 문자열처럼 다루다 TypeError나
            # AttributeError를 내는데, 그건 우리가 선언한 예외가 아니라서
            # 워커의 except Exception이 삼키고 sink가 아예 안 불린다.
            raise TranscriptionFailed(
                f"전사 결과가 문자열이 아니거나 비어 있다 — {type(text).__name__} "
                f"result={body.get('result')!r} message={body.get('message')!r}"
            )

        logger.info("전사 완료 — %d자 wav=%s", len(text), Path(wav_path).name)
        return text
