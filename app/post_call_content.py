"""통화가 끝난 뒤 대화 내용을 남긴다 — 턴 저장은 바로, 요약은 스레드에서.

**여기서 실패해도 통화는 끝난다.** 요약은 네트워크 호출이라 몇 초가 걸릴 수 있어
`stream_finished`를 기다리게 하면 그 어르신이 그만큼 409로 잠긴다. 그래서 요약만
스레드로 돌린다. 내용(턴·요약 본문)은 로그에 남기지 않는다 — call_id만.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence

from app.api.call_content import CallContentStore
from app.media.call_summary import CallSummarizer
from app.media.medication_check import MedicationClassifier
from app.media.mention_extract import MentionExtractor

logger = logging.getLogger(__name__)


def _spawn_thread(job: Callable[[], None]) -> None:
    threading.Thread(target=job, name="call-summary", daemon=True).start()


class ConversationRecorder:
    def __init__(
        self,
        content: CallContentStore,
        summarizer: CallSummarizer | None,
        *,
        classifier: MedicationClassifier | None = None,
        extractor: MentionExtractor | None = None,
        spawn: Callable[[Callable[[], None]], None] = _spawn_thread,
    ) -> None:
        self._content = content
        self._summarizer = summarizer
        self._classifier = classifier
        self._extractor = extractor
        self._spawn = spawn

    def record(self, call_id: int, turns: Sequence[tuple[str, str]]) -> None:
        if not turns:
            return
        try:
            self._content.save_turns(call_id, turns)
        except Exception:
            logger.exception("대화 턴을 저장하지 못했다 call_id=%s", call_id)
            return
        if self._summarizer is None and self._classifier is None and self._extractor is None:
            return
        if not any(speaker == "elder" and text.strip() for speaker, text in turns):
            return
        snapshot = list(turns)
        self._spawn(lambda: self._analyze(call_id, snapshot))

    def _analyze(self, call_id: int, turns: list[tuple[str, str]]) -> None:
        # 둘은 서로 막지 않는다 — 요약이 실패해도 복용 확인을, 그 반대도 계속한다.
        if self._summarizer is not None:
            self._summarize(call_id, turns)
        if self._classifier is not None:
            self._check_medication(call_id, turns)
        if self._extractor is not None:
            self._extract_mentions(call_id, turns)

    def _check_medication(self, call_id: int, turns: list[tuple[str, str]]) -> None:
        try:
            status = self._classifier.classify(turns)
            if status is None:
                logger.info("복용 확인을 하지 않았다 call_id=%s", call_id)
                return
            self._content.save_medication(call_id, status, self._classifier.model_id)
            logger.info("복용 확인을 저장했다 call_id=%s 결과=%s", call_id, status)
        except Exception:
            logger.exception("복용 확인을 하지 못했다 call_id=%s", call_id)

    def _extract_mentions(self, call_id: int, turns: list[tuple[str, str]]) -> None:
        try:
            mentions = self._extractor.extract(turns)
            if mentions is None:
                logger.info("건강·기분 언급을 뽑지 않았다 call_id=%s", call_id)
                return
            self._content.save_mentions(call_id, mentions, self._extractor.model_id)
            logger.info("건강·기분 언급을 저장했다 call_id=%s 개수=%d", call_id, len(mentions))
        except Exception:
            logger.exception("건강·기분 언급을 저장하지 못했다 call_id=%s", call_id)

    def _summarize(self, call_id: int, turns: list[tuple[str, str]]) -> None:
        try:
            summary = self._summarizer.summarize(turns)
            if summary is None:
                logger.info("요약을 만들지 않았다 call_id=%s", call_id)
                return
            self._content.save_summary(call_id, summary, self._summarizer.model_id)
            logger.info("요약을 저장했다 call_id=%s 글자=%d", call_id, len(summary))
        except Exception:
            logger.exception("요약을 만들지 못했다 call_id=%s", call_id)
