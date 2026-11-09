"""Bedrock 연결을 실제 키로 한 번 시험한다 (설계: 앱 AI 채팅 — 서버에 키를 넣은 뒤 확인).

사용: `python scripts/check_bedrock_chat.py` (프로젝트 루트에서, `.env`에 AWS_BEARER_TOKEN_BEDROCK이 있어야 한다)
키는 출력하지 않는다. 모델을 두 번 부른다(말동무 대화 한 번, 요약 한 번 — 아주 짧은 요청이라 요금은 거의 없다).
실패하면 HTTP 상태와 Bedrock이 준 문장을 보여 준다(모델 이름·권한·리전 문제를 가리는 데 쓴다).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(".env")

import httpx  # noqa: E402

from app.media.bedrock_chat import chat_model_from_env, summary_model_from_env  # noqa: E402
from app.media.call_summary import CallSummarizer  # noqa: E402
from app.media.conversation import Turn  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # 윈도우 콘솔(cp949)에서도 한글 문장이 깨지지 않게
    chat = chat_model_from_env()
    if chat is None:
        print("AWS_BEARER_TOKEN_BEDROCK이 없다 — .env를 확인한다")
        return 1
    print(f"모델: {chat.model}")
    try:
        answer = chat.reply([Turn("elder", "안녕하세요, 오늘 날씨가 궁금해요.")])
        print(f"대화: {answer}")
        summarizer = CallSummarizer(summary_model_from_env(), chat.model)
        summary = summarizer.summarize(
            [("ai", "안녕하세요, 저는 늘봄이에요."), ("elder", "오늘 날씨가 궁금해요."), ("ai", "맑아요.")]
        )
        print(f"요약: {summary}")
    except httpx.HTTPStatusError as exc:
        print(f"실패 — HTTP {exc.response.status_code}: {exc.response.text[:300]}")
        return 1
    except Exception as exc:  # noqa: BLE001 — 시험 스크립트다
        print(f"실패 — {type(exc).__name__}")
        return 1
    if not answer.strip():
        print("실패 — 응답이 비어 있다")
        return 1
    print("통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
