import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/call_summary.dart';

/// 서버와 말을 맞추는 유일한 지점.
///
/// 설계 5장 JSON 계약을 그대로 따른다. 이전 프로젝트의 `/api/call-history`,
/// `/api/elders`, `/api/conversation`은 계약이 달라 여기서 쓰지 않는다.
///
/// **fixture 모드** — 백엔드가 아직 없어도 화면을 만들 수 있도록 표본 데이터를
/// 돌려준다. 설계 2장의 "프론트는 계약에 맞춘 fixture로 개발한다"가 이것이다.
/// 실서버를 붙일 때는 아래처럼 끈다.
///
///   flutter run --dart-define=USE_FIXTURES=false \
///               --dart-define=API_BASE_URL=https://api.example.com

/// 전화 요청 결과. 409는 오류가 아니라 "이미 그 통화가 진행 중"이다.
class CallRequestResult {
  final int callId;
  final bool alreadyInProgress;

  const CallRequestResult({
    required this.callId,
    required this.alreadyInProgress,
  });
}

class ApiService {
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000',
  );

  static const bool useFixtures = bool.fromEnvironment(
    'USE_FIXTURES',
    defaultValue: true,
  );

  static const Duration _timeout = Duration(seconds: 10);

  // ------------------------------------------------------------ 보호자

  /// 보호자 홈이 필요한 것을 한 번에 가져온다.
  static Future<GuardianOverview> fetchGuardianOverview({
    int elderId = 1,
  }) async {
    if (useFixtures) return _fixtureOverview();

    final response = await http
        .get(
          Uri.parse('$baseUrl/v1/elders/$elderId/overview'),
          headers: const {'Content-Type': 'application/json'},
        )
        .timeout(_timeout);

    if (response.statusCode != 200) {
      throw Exception('안부 기록 조회 실패 (${response.statusCode})');
    }

    final json =
        jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return GuardianOverview(
      elderName: json['elder_name'] as String,
      latest: json['latest'] == null
          ? null
          : CallAnalysis.fromJson(json['latest'] as Map<String, dynamic>),
      trend: (json['trend'] as List<dynamic>)
          .map((point) => point as int?)
          .toList(),
      recentCalls: (json['recent_calls'] as List<dynamic>)
          .map((call) => CallRecord.fromJson(call as Map<String, dynamic>))
          .toList(),
    );
  }

  // ------------------------------------------------------------ 어르신

  /// 앱 채널 대화. 전화 채널과 달리 음성이 없어 지표가 일부만 나온다.
  static Future<String> chat(String message) async {
    if (useFixtures) {
      await Future<void>.delayed(const Duration(milliseconds: 400));
      return '그러셨군요. 오늘은 어떤 하루를 보내셨어요?';
    }

    final response = await http
        .post(
          Uri.parse('$baseUrl/v1/chat'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'message': message}),
        )
        .timeout(_timeout);

    if (response.statusCode != 200) {
      throw Exception('대화 실패 (${response.statusCode})');
    }
    final json =
        jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return json['reply'] as String;
  }

  /// AI에게 전화를 걸어 달라고 요청한다.
  ///
  /// 앱은 통화를 하지 않는다. 마이크도 소켓도 쓰지 않는다 — 버튼은 신호일 뿐이고
  /// 대화는 어르신의 전화기로 걸려 오는 진짜 전화에서 일어난다.
  static Future<CallRequestResult> requestCall({int elderId = 1}) async {
    if (useFixtures) {
      await Future<void>.delayed(const Duration(milliseconds: 500));
      return const CallRequestResult(callId: 1042, alreadyInProgress: false);
    }

    final response = await http
        .post(
          Uri.parse('$baseUrl/v1/calls/request'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'elder_id': elderId}),
        )
        .timeout(_timeout);

    if (response.statusCode == 202 || response.statusCode == 409) {
      final json =
          jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      return CallRequestResult(
        callId: json['call_id'] as int,
        // 두 번 누른 것은 오류가 아니다. 그 통화의 대기 화면으로 보낸다.
        alreadyInProgress: response.statusCode == 409,
      );
    }
    throw Exception('전화 요청 실패 (${response.statusCode})');
  }

  // ------------------------------------------------------------ 공통

  static Future<void> registerFcmToken(String token) async {
    if (useFixtures) return;

    await http
        .post(
          Uri.parse('$baseUrl/v1/devices/fcm-token'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'token': token}),
        )
        .timeout(_timeout);
  }

  // ------------------------------------------------------------ fixture

  /// 설계 5장 형식 그대로. 서버가 붙으면 이 값이 실측으로 바뀔 뿐
  /// 화면 코드는 바뀌지 않는다.
  static Future<GuardianOverview> _fixtureOverview() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
    final now = DateTime.now();

    // 정기 안부 전화는 매일 09시다(설계 3장). 화면을 언제 열어도 통화 시각이
    // 09:00으로 찍히도록, 이미 지나간 가장 최근 09시를 기준으로 잡는다.
    final nineToday = DateTime(now.year, now.month, now.day, 9);
    final lastCallAt = nineToday.isAfter(now)
        ? nineToday.subtract(const Duration(days: 1))
        : nineToday;

    return GuardianOverview(
      elderName: '박정숙 어르신',
      latest: CallAnalysis(
        metrics: const CallMetrics(
          speechRatio: 0.31,
          silenceRatio: 0.52,
          turnCount: 9,
          negativeWordCount: 4,
          avgResponseDelayMs: 2840,
          noAnswerRecent7: 2,
        ),
        riskScore: 68,
        riskLevel: 'watch',
        baselineDelta: const BaselineDelta(
          speechRatio: -0.19,
          avgResponseDelayMs: 1340,
        ),
        summary: '평소보다 말수가 줄고 대답이 늦어지셨어요. '
            '식사는 하셨다고 하셨지만 무릎이 아프다는 말씀이 여러 번 나왔어요.',
        degraded: false,
      ),
      trend: const [
        18, 22, 20, 25, null, 31, 28,
        34, 30, null, 41, 47, 55, 68,
      ],
      recentCalls: [
        CallRecord(
          callId: 1042,
          status: 'completed',
          startedAt: lastCallAt,
          durationSeconds: 214,
          riskLevel: 'watch',
          riskScore: 68,
        ),
        CallRecord(
          callId: 1040,
          status: 'completed',
          startedAt: lastCallAt.subtract(const Duration(days: 1)),
          durationSeconds: 252,
          riskLevel: 'watch',
          riskScore: 55,
        ),
        CallRecord(
          callId: 1038,
          status: 'no_answer',
          startedAt: lastCallAt.subtract(const Duration(days: 2)),
        ),
        CallRecord(
          callId: 1036,
          status: 'completed',
          startedAt: lastCallAt.subtract(const Duration(days: 3)),
          durationSeconds: 301,
          riskLevel: 'normal',
          riskScore: 22,
        ),
      ],
    );
  }
}
