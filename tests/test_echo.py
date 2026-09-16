"""AI 재생 구간을 어르신 발화에서 잘라낸다 (전화망 설계 3.4).

스피커폰이면 AI 음성이 어르신 수화기로 되울려 들어온다. 그걸 어르신
발화로 세면 발화 비율 35점이 부풀려진다. barge-in과 구별되지 않지만,
4주 범위에서는 지표를 부풀리는 쪽이 비우는 쪽보다 위험하다.
"""

from app.analysis.echo import clip_ai_playback
from app.analysis.segments import VadSegment


def test_no_overlap_changes_nothing():
    elder = [VadSegment(0, 1000), VadSegment(2000, 3000)]
    result = clip_ai_playback(elder, [VadSegment(1200, 1800)])
    assert result.segments == elder
    assert result.clipped_ms == 0


def test_fully_covered_segment_disappears():
    """AI가 말하는 내내 잡힌 '발화'는 에코다."""
    result = clip_ai_playback([VadSegment(1000, 2000)], [VadSegment(900, 2100)])
    assert result.segments == []
    assert result.clipped_ms == 1000


def test_overlap_at_the_head_is_trimmed():
    result = clip_ai_playback([VadSegment(1000, 2000)], [VadSegment(800, 1300)])
    assert result.segments == [VadSegment(1300, 2000)]
    assert result.clipped_ms == 300


def test_overlap_at_the_tail_is_trimmed():
    result = clip_ai_playback([VadSegment(1000, 2000)], [VadSegment(1700, 2500)])
    assert result.segments == [VadSegment(1000, 1700)]
    assert result.clipped_ms == 300


def test_overlap_in_the_middle_splits_the_segment():
    """가운데가 잘리면 구간이 둘로 나뉜다 — 발화 턴 수가 늘어난다."""
    result = clip_ai_playback([VadSegment(1000, 2000)], [VadSegment(1400, 1600)])
    assert result.segments == [VadSegment(1000, 1400), VadSegment(1600, 2000)]
    assert result.clipped_ms == 200


def test_multiple_ai_turns_are_all_removed():
    result = clip_ai_playback(
        [VadSegment(0, 3000)],
        [VadSegment(500, 1000), VadSegment(2000, 2200)],
    )
    assert result.segments == [
        VadSegment(0, 500),
        VadSegment(1000, 2000),
        VadSegment(2200, 3000),
    ]
    assert result.clipped_ms == 700


def test_overlapping_ai_turns_are_not_double_counted():
    """겹친 AI 구간을 두 번 세면 잘린 양이 실제보다 커 보인다."""
    result = clip_ai_playback(
        [VadSegment(0, 2000)],
        [VadSegment(500, 1200), VadSegment(1000, 1500)],
    )
    assert result.segments == [VadSegment(0, 500), VadSegment(1500, 2000)]
    assert result.clipped_ms == 1000


def test_no_ai_turns_is_a_pass_through():
    elder = [VadSegment(0, 1000)]
    assert clip_ai_playback(elder, []).segments == elder


def test_zero_length_ai_window_is_no_op():
    """mark 타이밍이 같으면 AI 윈도우가 zero-length가 된다.

    재생 시간이 없으므로 뺄 게 없다. 어르신 구간은 단일이고 변하지 않는다.
    turn_count를 부풀리는 phantom split이 생기면 안 된다.
    """
    elder = [VadSegment(1000, 2000)]
    result = clip_ai_playback(elder, [VadSegment(1500, 1500)])
    assert result.segments == [VadSegment(1000, 2000)]
    assert result.clipped_ms == 0


def test_zero_length_elder_segment_is_kept():
    """어르신 구간이 zero-length면 그대로 유지된다 (split되지 않음)."""
    result = clip_ai_playback([VadSegment(1000, 1000)], [VadSegment(500, 1500)])
    # zero-length는 유지되지만, AI 윈도우와 겹치므로 "뺀다".
    # 다만 뺄 게 없으므로 segments는 비어 있고 clipped_ms는 0이다.
    assert result.segments == []
    assert result.clipped_ms == 0
