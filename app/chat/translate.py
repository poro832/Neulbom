"""AI 채팅 번역 — 어르신이 AI의 말을 설정한 언어로 번역해 듣는다.

앱은 AI의 말과 언어 코드를 보내고, 서버는 LLM 게이트웨이로 번역해 돌려준다. **저장하지 않는다** — 번역문은 앱 화면에만
있고, 서버에는 최근 번역을 잠깐 기억하는 메모리 캐시(재시작하면 사라진다)만 있다.

**말 내용은 로그에 남기지 않는다.** 어르신과 AI의 사적인 대화다. 실패도 언어와 오류 종류만 남긴다.

**비용을 막는 장치 둘.** (1) 같은 글을 같은 언어로 다시 번역하면 모델을 부르지 않는다(캐시). (2) 어르신 한 명이
하루에 새로 번역할 수 있는 수가 정해져 있다 — 캐시에서 나가는 것은 세지 않고, 실패한 번역도 세지 않는다.
하루 수는 서버가 메모리에 센다(재시작하면 0으로 돌아간다). 요금 사고를 막는 안전망이지 보안 장치가 아니다.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable

from app.media.conversation import ChatModel, Turn

logger = logging.getLogger(__name__)

# 앱의 설정 목록과 같아야 한다(client/lib/screens/chat_widgets.dart의 chatLanguages).
LANGUAGES: dict[str, str] = {
    "en": "영어",
    "ja": "일본어",
    "zh": "중국어(간체)",
    "vi": "베트남어",
    "th": "태국어",
    "ru": "러시아어",
}

TRANSLATE_DAILY_LIMIT = 100  # 어르신 한 명이 하루에 새로 번역할 수 있는 글
MAX_TRANSLATE_CHARS = 600  # AI의 답 한 번의 길이(MAX_REPLY_CHARS)와 같다
MAX_RESULT_CHARS = 1500
CACHE_SIZE = 256


class TranslateUnavailable(Exception):
    """번역할 수 없다(모델이 없거나 응답하지 못했다)."""


class TranslateLimitReached(Exception):
    """오늘 번역할 수 있는 글을 다 썼다."""


def clean_language(value: object) -> str | None:
    """지원하는 언어 코드면 소문자로 정리해 돌려주고, 아니면 None. 한국어(ko)는 번역 대상이 아니다."""
    if not isinstance(value, str):
        return None
    code = value.strip().lower()
    return code if code in LANGUAGES else None


class Translator:
    """언어별 번역 모델을 만들어 쓰고, 최근 번역을 기억한다.

    [model_for]는 언어 이름(예: "영어")을 받아 그 언어로 번역하는 모델을 돌려준다(없으면 None).
    """

    def __init__(self, model_for: Callable[[str], ChatModel | None]) -> None:
        self._model_for = model_for
        self._models: dict[str, ChatModel] = {}
        self._cache: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._lock = threading.Lock()

    def cached(self, text: str, language: str) -> str | None:
        with self._lock:
            hit = self._cache.get((text, language))
            if hit is not None:
                self._cache.move_to_end((text, language))
            return hit

    def translate(self, text: str, language: str) -> str:
        """번역문. 못 만들면 TranslateUnavailable. 성공하면 캐시에 넣는다."""
        model = self._model(language)
        try:
            raw = model.reply([Turn("elder", text)])
        except Exception as exc:
            # 말 내용은 남기지 않는다. 언어와 오류 종류만.
            logger.error("번역 실패 language=%s 오류=%s", language, type(exc).__name__)
            raise TranslateUnavailable("번역 실패") from exc
        result = (raw or "").strip()[:MAX_RESULT_CHARS]
        if not result:
            raise TranslateUnavailable("빈 번역")
        with self._lock:
            self._cache[(text, language)] = result
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return result

    def _model(self, language: str) -> ChatModel:
        with self._lock:
            model = self._models.get(language)
        if model is None:
            model = self._model_for(LANGUAGES[language])
            if model is None:
                raise TranslateUnavailable("모델 없음")
            with self._lock:
                self._models[language] = model
        return model
