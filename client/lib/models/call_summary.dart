/// 설계 5장 인터페이스 계약을 그대로 옮긴 모델.
///
/// 서버가 계산한 숫자(metrics, riskScore)와 LLM이 쓴 문장(summary)을
/// 필드 단위로 분리해 둔다 — 화면에서도 둘의 출처가 섞이지 않게 한다.
class CallMetrics {
  const CallMetrics({
    required this.speechRatio,
    required this.silenceRatio,
    required this.turnCount,
    required this.negativeWordCount,
    this.avgResponseDelayMs,
    required this.noAnswerRecent7,
  });

  final double speechRatio;
  final double silenceRatio;
  final int turnCount;
  final int negativeWordCount;

  /// 어르신이 한 번도 응답하지 않으면 null. 0이 아니다.
  final int? avgResponseDelayMs;
  final int noAnswerRecent7;

  factory CallMetrics.fromJson(Map<String, dynamic> json) => CallMetrics(
        speechRatio: (json['speech_ratio'] as num).toDouble(),
        silenceRatio: (json['silence_ratio'] as num).toDouble(),
        turnCount: json['turn_count'] as int,
        negativeWordCount: json['negative_word_count'] as int,
        avgResponseDelayMs: json['avg_response_delay_ms'] as int?,
        noAnswerRecent7: json['no_answer_recent_7'] as int,
      );
}

class BaselineDelta {
  const BaselineDelta({required this.speechRatio, this.avgResponseDelayMs});

  final double speechRatio;
  final int? avgResponseDelayMs;

  factory BaselineDelta.fromJson(Map<String, dynamic> json) => BaselineDelta(
        speechRatio: (json['speech_ratio'] as num).toDouble(),
        avgResponseDelayMs: json['avg_response_delay_ms'] as int?,
      );
}

class CallAnalysis {
  const CallAnalysis({
    required this.metrics,
    this.riskScore,
    this.riskLevel,
    this.baselineDelta,
    this.summary,
    required this.degraded,
  });

  final CallMetrics metrics;

  /// VAD가 실패하면 null. 앱은 임의 점수를 만들지 않고 "측정 실패"로 표시한다.
  final int? riskScore;
  final String? riskLevel;
  final BaselineDelta? baselineDelta;

  /// LLM이 쓴 설명. 숫자는 여기서 오지 않는다.
  final String? summary;
  final bool degraded;

  factory CallAnalysis.fromJson(Map<String, dynamic> json) => CallAnalysis(
        metrics: CallMetrics.fromJson(json['metrics'] as Map<String, dynamic>),
        riskScore: json['risk_score'] as int?,
        riskLevel: json['risk_level'] as String?,
        baselineDelta: json['baseline_delta'] == null
            ? null
            : BaselineDelta.fromJson(
                json['baseline_delta'] as Map<String, dynamic>),
        summary: json['summary'] as String?,
        degraded: json['degraded'] as bool? ?? false,
      );
}

class CallRecord {
  const CallRecord({
    required this.callId,
    required this.status,
    required this.startedAt,
    this.durationSeconds,
    this.riskLevel,
    this.riskScore,
  });

  final int callId;

  /// completed | no_answer | failed
  final String status;
  final DateTime startedAt;
  final int? durationSeconds;
  final String? riskLevel;
  final int? riskScore;

  factory CallRecord.fromJson(Map<String, dynamic> json) => CallRecord(
        callId: json['call_id'] as int,
        status: json['status'] as String,
        startedAt: DateTime.parse(json['started_at'] as String),
        durationSeconds: json['duration_seconds'] as int?,
        riskLevel: json['risk_level'] as String?,
        riskScore: json['risk_score'] as int?,
      );
}

/// 보호자 홈이 한 번에 필요로 하는 묶음.
class GuardianOverview {
  const GuardianOverview({
    required this.elderName,
    required this.latest,
    required this.trend,
    required this.recentCalls,
  });

  final String elderName;
  final CallAnalysis? latest;

  /// 최근 2주 위험 점수. 없는 날(미응답 등)은 null.
  final List<int?> trend;
  final List<CallRecord> recentCalls;
}
