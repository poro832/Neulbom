import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../models/nulbom_models.dart';

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

/// 서버가 거절했거나 열쇠가 없을 때. `message`는 사람이 읽을 수 있는 문장이다.
class ApiException implements Exception {
  final int statusCode;
  final String message;

  const ApiException(this.statusCode, this.message);

  @override
  String toString() => message;
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
  static String guardianKey = const String.fromEnvironment('GUARDIAN_KEY');

  static const Duration _timeout = Duration(seconds: 10);

  /// 테스트에서 교체한다.
  static http.Client client = http.Client();

  static const String _elderKeyPref = 'elder_key';

  // ------------------------------------------------------------ 공통

  static Future<String?> elderKey() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_elderKeyPref);
  }

  static Future<void> saveElderKey(String key) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_elderKeyPref, key);
  }

  static Future<void> clearElderKey() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_elderKeyPref);
  }

  static String _guardianKeyOrThrow(String? override) {
    final key = override ?? guardianKey;
    if (key.isEmpty) {
      throw const ApiException(401, '보호자 열쇠가 앱에 들어 있지 않습니다');
    }
    return key;
  }

  static Future<String> _elderKeyOrThrow(String? override) async {
    final key = override ?? await elderKey();
    if (key == null || key.isEmpty) {
      throw const ApiException(401, '이 폰은 아직 연결되지 않았어요');
    }
    return key;
  }

  static Map<String, dynamic> _decode(http.Response response) {
    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (response.body.isEmpty) return <String, dynamic>{};
      return jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    }
    var message = '요청에 실패했어요 (${response.statusCode})';
    try {
      final body = jsonDecode(utf8.decode(response.bodyBytes));
      if (body is Map<String, dynamic> && body['detail'] is String) {
        message = body['detail'] as String;
      }
    } catch (_) {
      // 본문이 JSON이 아니면 기본 문구를 쓴다.
    }
    throw ApiException(response.statusCode, message);
  }

  static Future<Map<String, dynamic>> _send(
    String method,
    String path, {
    String? key,
    Object? body,
  }) async {
    final headers = <String, String>{
      if (key != null) 'Authorization': 'Bearer $key',
      if (body != null) 'Content-Type': 'application/json',
    };
    final uri = Uri.parse('$baseUrl$path');
    final http.Response response;
    switch (method) {
      case 'GET':
        response = await client.get(uri, headers: headers).timeout(_timeout);
      case 'POST':
        response = await client
            .post(uri, headers: headers, body: body == null ? null : jsonEncode(body))
            .timeout(_timeout);
      case 'DELETE':
        response = await client.delete(uri, headers: headers).timeout(_timeout);
      default:
        throw ArgumentError('지원하지 않는 메서드: $method');
    }
    return _decode(response);
  }

  // ------------------------------------------------------------ 어르신 연결

  /// 보호자가 알려 준 코드와 내 전화번호로 이 폰 전용 열쇠를 받는다. 성공하면 폰에 저장한다.
  static Future<PairResult> pair({required String code, required String phone}) async {
    final json = await _send('POST', '/v1/pair', body: {'code': code, 'phone': phone});
    final result = PairResult.fromJson(json);
    await saveElderKey(result.elderKey);
    return result;
  }

  // ------------------------------------------------------------ 보호자

  static Future<PairingCode> issuePairingCode(int elderId, {String? key}) async {
    final json = await _send('POST', '/v1/elders/$elderId/pairing-code',
        key: _guardianKeyOrThrow(key));
    return PairingCode.fromJson(json);
  }

  static Future<List<ElderSummary>> guardianElders({String? key}) async {
    final json = await _send('GET', '/v1/guardian/elders', key: _guardianKeyOrThrow(key));
    return (json['elders'] as List<dynamic>)
        .map((e) => ElderSummary.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  static Future<WeeklyStats> weekly(int elderId, {String? key, String? weekStart}) async {
    final query = weekStart == null ? '' : '?week_start=$weekStart';
    final json = await _send('GET', '/v1/elders/$elderId/weekly$query',
        key: _guardianKeyOrThrow(key));
    return WeeklyStats.fromJson(json);
  }

  static Future<List<AlertItem>> guardianAlerts({String? key, int limit = 20}) async {
    final json = await _send('GET', '/v1/guardian/alerts?limit=$limit',
        key: _guardianKeyOrThrow(key));
    return (json['alerts'] as List<dynamic>)
        .map((a) => AlertItem.fromJson(a as Map<String, dynamic>))
        .toList();
  }

  // ------------------------------------------------------------ 어르신

  static Future<List<AiCall>> myCalls({String? key, int limit = 30}) async {
    final json =
        await _send('GET', '/v1/me/calls?limit=$limit', key: await _elderKeyOrThrow(key));
    return (json['calls'] as List<dynamic>)
        .map((c) => AiCall.fromJson(c as Map<String, dynamic>))
        .toList();
  }

  static Future<MyContacts> myContacts({String? key}) async {
    final json = await _send('GET', '/v1/me/contacts', key: await _elderKeyOrThrow(key));
    return MyContacts.fromJson(json);
  }

  static Future<ContactItem> addContact({
    required String name,
    required String relation,
    required String phone,
    String? key,
  }) async {
    final json = await _send(
      'POST',
      '/v1/me/contacts',
      key: await _elderKeyOrThrow(key),
      body: {'name': name, 'relation': relation, 'phone': phone},
    );
    return ContactItem.fromJson(json);
  }

  static Future<void> deleteContact(int contactId, {String? key}) async {
    await _send('DELETE', '/v1/me/contacts/$contactId', key: await _elderKeyOrThrow(key));
  }

  // ------------------------------------------------------------ 보호자 코드로 가입

  /// 보호자 개인 코드로 가입한다. 서버가 승인 대기 어르신을 만들고 이 폰 전용 열쇠를 준다.
  /// 보호자가 승인하기 전에는 전화가 오지 않는다.
  static Future<SignupResult> signup({
    required String code,
    required String name,
    required String phone,
    required bool agreed,
  }) async {
    final json = await _send('POST', '/v1/signup',
        body: {'code': code, 'name': name, 'phone': phone, 'agreed': agreed});
    final result = SignupResult.fromJson(json);
    await saveElderKey(result.elderKey);
    return result;
  }

  static Future<MyStatus> myStatus({String? key}) async {
    final json = await _send('GET', '/v1/me/status', key: await _elderKeyOrThrow(key));
    return MyStatus.fromJson(json);
  }

  static Future<InviteCode> issueInvite({String? key}) async {
    final json = await _send('POST', '/v1/guardian/invite', key: _guardianKeyOrThrow(key));
    return InviteCode.fromJson(json);
  }

  static Future<void> approveElder(int elderId, {String? key}) async {
    await _send('POST', '/v1/elders/$elderId/approve', key: _guardianKeyOrThrow(key));
  }

  static Future<void> rejectElder(int elderId, {String? key}) async {
    await _send('POST', '/v1/elders/$elderId/reject', key: _guardianKeyOrThrow(key));
  }

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
