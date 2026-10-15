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
  final String status; // active | pending | unconsented
  final String? phone; // 승인 대기일 때만 온다

  const ElderSummary({
    required this.elderId,
    required this.name,
    required this.lastCallAt,
    required this.lastStatus,
    required this.weekCalls,
    required this.weekAvgScore,
    required this.weekAlerts,
    this.status = 'active',
    this.phone,
  });

  factory ElderSummary.fromJson(Map<String, dynamic> json) => ElderSummary(
        elderId: json['elder_id'] as int,
        name: json['name'] as String,
        lastCallAt: _asTime(json['last_call_at']),
        lastStatus: json['last_status'] as String?,
        weekCalls: json['week_calls'] as int,
        weekAvgScore: _asDouble(json['week_avg_score']),
        weekAlerts: json['week_alerts'] as int,
        status: (json['status'] as String?) ?? 'active',
        phone: json['phone'] as String?,
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

class SignupResult {
  final String elderKey;
  final String status;

  const SignupResult({required this.elderKey, required this.status});

  factory SignupResult.fromJson(Map<String, dynamic> json) => SignupResult(
        elderKey: json['elder_key'] as String,
        status: json['status'] as String,
      );
}

/// 보호자가 연결 코드를 입력했을 때 확인하는 어르신 정보. 번호는 가려져 온다.
class ElderPreview {
  final String name;
  final String phoneMasked; // 010-****-1111

  const ElderPreview({required this.name, required this.phoneMasked});

  factory ElderPreview.fromJson(Map<String, dynamic> json) => ElderPreview(
        name: json['name'] as String,
        phoneMasked: json['phone_masked'] as String,
      );
}

class LinkResult {
  final int elderId;
  final String name;

  const LinkResult({required this.elderId, required this.name});

  factory LinkResult.fromJson(Map<String, dynamic> json) => LinkResult(
        elderId: json['elder_id'] as int,
        name: json['name'] as String,
      );
}

class MyStatus {
  final String status; // unlinked | pending | active | unconsented
  final String name;
  // 통화 내용(요약·원문)을 보호자에게 공유하는 데 동의했는가. 없으면 동의 전으로 본다.
  final bool shareAgreed;

  const MyStatus({required this.status, required this.name, this.shareAgreed = false});

  factory MyStatus.fromJson(Map<String, dynamic> json) => MyStatus(
        status: json['status'] as String,
        name: json['name'] as String,
        shareAgreed: (json['share_agreed'] as bool?) ?? false,
      );
}

/// 보호자 앱의 통화 한 줄: 요약이 있으면 요약, 원문이 있으면 눌러서 볼 수 있다.
class CallSummary {
  final int callId;
  final DateTime startedAt;
  final int? durationS;
  final String status;
  final String? summary;
  final bool hasTurns;
  final String? medication; // taken | not_taken | unknown | null(분석 전)

  const CallSummary({
    required this.callId,
    required this.startedAt,
    required this.durationS,
    required this.status,
    required this.summary,
    required this.hasTurns,
    this.medication,
  });

  factory CallSummary.fromJson(Map<String, dynamic> json) => CallSummary(
        callId: json['call_id'] as int,
        startedAt: _asTime(json['started_at'])!,
        durationS: json['duration_s'] as int?,
        status: json['status'] as String,
        summary: json['summary'] as String?,
        hasTurns: (json['has_turns'] as bool?) ?? false,
        medication: json['medication'] as String?,
      );
}

class ElderCalls {
  final bool shareAgreed; // false면 어르신이 아직 공유에 동의하지 않았다 — calls는 비어 있다
  final List<CallSummary> calls;

  const ElderCalls({required this.shareAgreed, required this.calls});

  factory ElderCalls.fromJson(Map<String, dynamic> json) => ElderCalls(
        shareAgreed: (json['share_agreed'] as bool?) ?? false,
        calls: (json['calls'] as List<dynamic>)
            .map((c) => CallSummary.fromJson(c as Map<String, dynamic>))
            .toList(),
      );
}

class CallTurn {
  final String speaker; // ai | elder
  final String text;

  const CallTurn({required this.speaker, required this.text});

  bool get isAi => speaker == 'ai';

  factory CallTurn.fromJson(Map<String, dynamic> json) =>
      CallTurn(speaker: json['speaker'] as String, text: json['text'] as String);
}

class InviteCode {
  final String code; // 앞자리 0이 있을 수 있어 문자열이다

  const InviteCode({required this.code});

  factory InviteCode.fromJson(Map<String, dynamic> json) =>
      InviteCode(code: json['code'] as String);
}

class GuardianProfile {
  final String name;
  final String email;
  final String phone;
  final bool activated; // false면 운영자 확인을 기다리는 중이다(어르신 등록·승인 불가)
  final bool emailVerified; // 응답에 필드가 없는 옛 서버·옛 계정은 인증된 것으로 본다

  const GuardianProfile({
    required this.name,
    required this.email,
    required this.phone,
    this.activated = true,
    this.emailVerified = true,
  });

  factory GuardianProfile.fromJson(Map<String, dynamic> json) => GuardianProfile(
        name: json['name'] as String,
        email: json['email'] as String,
        phone: json['phone'] as String,
        activated: (json['activated'] as bool?) ?? true,
        emailVerified: (json['email_verified'] as bool?) ?? true,
      );
}

class MentionItem {
  final int callId;
  final DateTime date;
  final String said; // bad | ok | good — 어르신이 스스로 한 표현
  final String quote; // 어르신 말 그대로

  const MentionItem({required this.callId, required this.date, required this.said, required this.quote});

  factory MentionItem.fromJson(Map<String, dynamic> json) => MentionItem(
        callId: json['call_id'] as int,
        date: _asTime(json['date'])!,
        said: json['said'] as String,
        quote: json['quote'] as String,
      );
}

class MentionCategory {
  final String category; // body | sleep | meal | mood | activity
  final int negative;
  final int neutral;
  final int positive;
  final List<MentionItem> items;

  const MentionCategory({
    required this.category,
    required this.negative,
    required this.neutral,
    required this.positive,
    required this.items,
  });

  int get total => negative + neutral + positive;

  String get label {
    switch (category) {
      case 'body':
        return '몸이 아프거나 불편함';
      case 'sleep':
        return '잠';
      case 'meal':
        return '식사·입맛';
      case 'mood':
        return '기분·외로움';
      case 'activity':
        return '움직임·외출';
      default:
        return category;
    }
  }

  factory MentionCategory.fromJson(Map<String, dynamic> json) => MentionCategory(
        category: json['category'] as String,
        negative: (json['negative'] as int?) ?? 0,
        neutral: (json['neutral'] as int?) ?? 0,
        positive: (json['positive'] as int?) ?? 0,
        items: ((json['items'] as List<dynamic>?) ?? [])
            .map((i) => MentionItem.fromJson(i as Map<String, dynamic>))
            .toList(),
      );
}

class ElderMentions {
  final bool shareAgreed; // false면 어르신이 아직 공유에 동의하지 않았다 — categories는 비어 있다
  final String weekStart;
  final List<MentionCategory> categories;

  const ElderMentions({required this.shareAgreed, required this.weekStart, required this.categories});

  factory ElderMentions.fromJson(Map<String, dynamic> json) => ElderMentions(
        shareAgreed: (json['share_agreed'] as bool?) ?? false,
        weekStart: (json['week_start'] as String?) ?? '',
        categories: ((json['categories'] as List<dynamic>?) ?? [])
            .map((c) => MentionCategory.fromJson(c as Map<String, dynamic>))
            .toList(),
      );
}
