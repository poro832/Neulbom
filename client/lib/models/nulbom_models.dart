/// 늘봄 서버 응답 모델. 필드 이름은 서버 JSON 그대로 읽고 Dart 이름으로 바꾼다.
double? _asDouble(Object? value) => value == null ? null : (value as num).toDouble();
DateTime? _asTime(Object? value) =>
    value == null ? null : DateTime.parse(value as String).toLocal();

class ElderSummary {
  final int elderId;
  final String name;
  final DateTime? lastCallAt;
  final String? lastStatus;
  final int weekCalls;
  final double? weekAvgScore;
  final int weekAlerts;

  const ElderSummary({
    required this.elderId,
    required this.name,
    required this.lastCallAt,
    required this.lastStatus,
    required this.weekCalls,
    required this.weekAvgScore,
    required this.weekAlerts,
  });

  factory ElderSummary.fromJson(Map<String, dynamic> json) => ElderSummary(
        elderId: json['elder_id'] as int,
        name: json['name'] as String,
        lastCallAt: _asTime(json['last_call_at']),
        lastStatus: json['last_status'] as String?,
        weekCalls: json['week_calls'] as int,
        weekAvgScore: _asDouble(json['week_avg_score']),
        weekAlerts: json['week_alerts'] as int,
      );
}

class DayStat {
  final String date;
  final int calls;
  final double? avgScore;

  const DayStat({required this.date, required this.calls, required this.avgScore});

  factory DayStat.fromJson(Map<String, dynamic> json) => DayStat(
        date: json['date'] as String,
        calls: json['calls'] as int,
        avgScore: _asDouble(json['avg_score']),
      );
}

class WeeklyStats {
  final String weekStart;
  final List<DayStat> days;
  final int totalCalls;
  final double? avgScore;

  const WeeklyStats({
    required this.weekStart,
    required this.days,
    required this.totalCalls,
    required this.avgScore,
  });

  factory WeeklyStats.fromJson(Map<String, dynamic> json) => WeeklyStats(
        weekStart: json['week_start'] as String,
        days: (json['days'] as List<dynamic>)
            .map((d) => DayStat.fromJson(d as Map<String, dynamic>))
            .toList(),
        totalCalls: json['total_calls'] as int,
        avgScore: _asDouble(json['avg_score']),
      );
}

class AlertItem {
  final int alertId;
  final int elderId;
  final String elderName;
  final String type; // risk_rise | no_answer
  final String severity; // info | warning | critical
  final String message;
  final DateTime createdAt;

  const AlertItem({
    required this.alertId,
    required this.elderId,
    required this.elderName,
    required this.type,
    required this.severity,
    required this.message,
    required this.createdAt,
  });

  factory AlertItem.fromJson(Map<String, dynamic> json) => AlertItem(
        alertId: json['alert_id'] as int,
        elderId: json['elder_id'] as int,
        elderName: json['elder_name'] as String,
        type: json['type'] as String,
        severity: json['severity'] as String,
        message: json['message'] as String,
        createdAt: _asTime(json['created_at'])!,
      );
}

class AiCall {
  final int callId;
  final DateTime startedAt;
  final int? durationS;
  final String status; // completed | no_answer | failed

  const AiCall({
    required this.callId,
    required this.startedAt,
    required this.durationS,
    required this.status,
  });

  factory AiCall.fromJson(Map<String, dynamic> json) => AiCall(
        callId: json['call_id'] as int,
        startedAt: _asTime(json['started_at'])!,
        durationS: json['duration_s'] as int?,
        status: json['status'] as String,
      );
}

class GuardianContact {
  final String name;
  final String relation;
  final String phone;

  const GuardianContact({required this.name, required this.relation, required this.phone});

  factory GuardianContact.fromJson(Map<String, dynamic> json) => GuardianContact(
        name: json['name'] as String,
        relation: json['relation'] as String,
        phone: json['phone'] as String,
      );
}

class ContactItem {
  final int contactId;
  final String name;
  final String relation;
  final String phone;

  const ContactItem({
    required this.contactId,
    required this.name,
    required this.relation,
    required this.phone,
  });

  factory ContactItem.fromJson(Map<String, dynamic> json) => ContactItem(
        contactId: json['contact_id'] as int,
        name: json['name'] as String,
        relation: json['relation'] as String,
        phone: json['phone'] as String,
      );
}

class MyContacts {
  final List<GuardianContact> guardians;
  final List<ContactItem> contacts;

  const MyContacts({required this.guardians, required this.contacts});

  factory MyContacts.fromJson(Map<String, dynamic> json) => MyContacts(
        guardians: (json['guardians'] as List<dynamic>)
            .map((g) => GuardianContact.fromJson(g as Map<String, dynamic>))
            .toList(),
        contacts: (json['contacts'] as List<dynamic>)
            .map((c) => ContactItem.fromJson(c as Map<String, dynamic>))
            .toList(),
      );
}

class PairResult {
  final String elderKey;
  final String elderName;

  const PairResult({required this.elderKey, required this.elderName});

  factory PairResult.fromJson(Map<String, dynamic> json) => PairResult(
        elderKey: json['elder_key'] as String,
        elderName: json['elder_name'] as String,
      );
}

class PairingCode {
  final String code; // 앞자리 0이 있을 수 있어 문자열이다
  final DateTime expiresAt;

  const PairingCode({required this.code, required this.expiresAt});

  factory PairingCode.fromJson(Map<String, dynamic> json) => PairingCode(
        code: json['code'] as String,
        expiresAt: _asTime(json['expires_at'])!,
      );
}
