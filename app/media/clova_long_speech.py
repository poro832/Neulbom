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

# 성공을 뜻하는 result 값. 실호출에서 sync 응답이 "COMPLETED"를 주는 것을
# 확인했고, 문서의 async 제출 응답 예시는 "SUCCEEDED"를 쓴다. 둘 다 받는다.
#
# 모르는 값은 실패로 본다. 사업자가 새 성공 값을 추가하면 우리는 점수를 안
# 내는 쪽으로 틀리는데, 그 방향이 맞다 — 근거 없이 점수를 내는 것보다 낫고
# 로그에 result 값이 그대로 남아 금방 드러난다.
SUCCESS_RESULTS = frozenset({"COMPLETED", "SUCCEEDED"})


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

        # 성공 여부는 result가 말한다. 글자가 있느냐로 판단하면 양쪽으로 틀린다
        # — 말을 안 한 통화를 실패로 접고, 사업자가 실패라고 답한 결과에 글자가
        # 딸려 오면 그걸 점수에 넣는다.
        result = body.get("result")
        if result not in SUCCESS_RESULTS:
            raise TranscriptionFailed(
                f"전사가 실패로 끝났다 — result={result!r} "
                f"message={body.get('message')!r}"
            )

        text = body.get("text")
        if not isinstance(text, str):
            # 사업자가 숫자나 리스트를 줄 수 있다. 검사 없이 넘기면 아래 len()이나
            # count_negative_words가 그 값을 문자열처럼 다루다 TypeError나
            # AttributeError를 내는데, 그건 우리가 선언한 예외가 아니라서 워커의
            # except Exception이 삼키고 sink가 아예 안 불린다 — 그 통화는
            # CallOutcome을 하나도 못 받는다.
            raise TranscriptionFailed(
                f"전사 결과가 문자열이 아니다 — {type(text).__name__} "
                f"result={result!r} message={body.get('message')!r}"
            )

        if not text:
            # 인식은 성공했는데 알아들을 말이 없었다. 실호출로 확인한 실제
            # 응답이 이 모양이다(result="COMPLETED", text="", segments=[]).
            #
            # 이걸 실패로 접으면 안 된다. 어르신이 통화 내내 거의 말을 안 한
            # 통화가 바로 가장 위험한 통화인데(발화 비율 35점과 침묵 25점이
            # 동시에 치솟는다), degraded로 빠지면 점수가 아예 안 나오고 기준선
            # 표본에서도 빠진다 — 보호자가 가장 알아야 할 때 아무 숫자도 못 본다.
            #
            # 말을 안 한 것과 못 알아들은 것은 다르다. 앞은 데이터고 뒤는 사고다.
            logger.info("전사 완료 — 알아들은 말이 없다 wav=%s", Path(wav_path).name)
            return ""

        logger.info("전사 완료 — %d자 wav=%s", len(text), Path(wav_path).name)
        return text
