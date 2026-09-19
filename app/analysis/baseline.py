"""이 어르신의 '평소'를 과거 결과에서 구한다 (설계 3.1, 3.2).

저장하지 않고 매번 계산한다. 저장된 기준선은 갱신을 한 번 빠뜨리거나 순서가
꼬이면 이력과 다른 말을 하는데, 그 어긋남은 아무 신호도 내지 않으면서 점수만
조용히 틀리게 만든다. 이 프로젝트에서 조용히 틀린 숫자는 터지는 것보다 나쁘다.

이 모듈에는 저장소도 네트워크도 시계도 없다 — 리스트를 넣으면 값이 나온다.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.analysis.metrics_calculator import Baseline
from app.analysis.outcome import CallOutcome

# 직전 몇 통을 보는가. 짧으면 하루치 컨디션이 기준선을 흔들고, 길면 회복을
# 반영하지 못한다. 매일 1통 기준 2주다.
BASELINE_WINDOW = 14

# 이보다 적으면 기준선이라 부르지 않는다. 근거 없는 평균을 지어내느니 None을
# 주고 assess_risk가 절대 기준을 쓰게 한다.
BASELINE_MIN_CALLS = 3


def compute_baseline(recent: Sequence[CallOutcome]) -> Baseline | None:
    """과거 결과들에서 평소 상태를 구한다. 근거가 모자라면 None.

    입력은 호출부가 최신순으로 BASELINE_WINDOW만큼 잘라서 준다. 창을 먼저
    자르고 여기서 degraded를 버리는 순서다 — 반대로 하면(멀쩡한 통화를 찾아
    과거로 거슬러 올라가면) 두 달 전 상태가 오늘의 기준선이 될 수 있다.
    그건 '평소'가 아니다.

    현재 통화는 여기 들어오면 안 된다. 섞이면 델타가 자기 자신 쪽으로
    희석돼 나쁜 통화가 정상으로 보인다 — 오류도 경고도 나지 않는다.
    """
    usable = [outcome for outcome in recent if not outcome.degraded]
    if len(usable) < BASELINE_MIN_CALLS:
        return None

    speech = round(sum(outcome.metrics.speech_ratio for outcome in usable) / len(usable), 10)

    # None은 "응답이 없었다"이지 "0ms였다"가 아니다. 0으로 세면 평균이 내려가
    # 이후 모든 통화가 '느려졌다'가 된다. 분자에서도 분모에서도 뺀다.
    delays = [
        outcome.metrics.avg_response_delay_ms
        for outcome in usable
        if outcome.metrics.avg_response_delay_ms is not None
    ]
    delay = round(sum(delays) / len(delays)) if delays else None

    return Baseline(speech_ratio=speech, avg_response_delay_ms=delay)
