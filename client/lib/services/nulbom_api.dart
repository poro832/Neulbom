import 'dart:convert';

import 'package:http/http.dart' as http;

/// 늘봄 서버에 전화를 걸어 달라고 요청하는 유일한 지점.
///
/// 팀원 앱의 `ApiService`(별도 백엔드용)와 섞이지 않게 따로 둔다. 이 서버의
/// 계약은 `POST /v1/calls/request` 하나이고 보호자 열쇠가 있어야 통과한다.
///
///   flutter build apk --dart-define=GUARDIAN_KEY=nlb_... \
///                     --dart-define=API_BASE_URL=https://nuelbom.duckdns.org

/// 전화 요청 결과. 409는 오류가 아니라 "이미 그 통화가 진행 중"이다.
class CallRequestResult {
  final int callId;
  final bool alreadyInProgress;

  const CallRequestResult({
    required this.callId,
    required this.alreadyInProgress,
  });
}

class NulbomApi {
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://nuelbom.duckdns.org',
  );

  /// 보호자 개인 열쇠. 빌드할 때 `--dart-define=GUARDIAN_KEY=nlb_...`로 넣는다.
  ///
  /// 시연 단계의 방식이다. 앱 파일에 열쇠가 들어가므로 앱 파일을 남에게 주면
  /// 열쇠도 간다 — 피해는 그 보호자의 어르신께 하루 상한 이하로 한정되고, 서버에서
  /// 폐기하면 끝난다. 로그인 단계에서 이 상수는 사라진다.
  static const String guardianKey = String.fromEnvironment('GUARDIAN_KEY');

  static const Duration _timeout = Duration(seconds: 10);

  /// AI에게 전화를 걸어 달라고 요청한다.
  ///
  /// 앱은 통화를 하지 않는다. 마이크도 소켓도 쓰지 않는다 — 버튼은 신호일 뿐이고
  /// 대화는 어르신의 전화기로 걸려 오는 진짜 전화에서 일어난다.
  static Future<CallRequestResult> requestCall({int elderId = 1}) async {
    final response = await http
        .post(
          Uri.parse('$baseUrl/v1/calls/request'),
          headers: {
            'Content-Type': 'application/json',
            if (guardianKey.isNotEmpty) 'Authorization': 'Bearer $guardianKey',
          },
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
    throw Exception(callRequestMessage(response.statusCode));
  }

  /// 전화 요청이 거절된 이유를 보호자가 알아볼 말로 바꾼다.
  /// 서버는 401을 열쇠의 없음, 틀림, 폐기에 똑같이 쓴다(이유를 알려 주지 않으려고).
  static String callRequestMessage(int statusCode) {
    switch (statusCode) {
      case 401:
        return '보호자 열쇠가 없거나 올바르지 않습니다';
      case 403:
        return '어르신의 동의가 아직 없습니다';
      case 404:
        return '등록되지 않은 어르신입니다';
      case 429:
        return '오늘 요청 횟수를 넘었습니다';
      case 503:
        return '지금은 확인할 수 없습니다. 잠시 뒤에 다시 해 주세요';
      default:
        return '전화 요청 실패 ($statusCode)';
    }
  }
}
