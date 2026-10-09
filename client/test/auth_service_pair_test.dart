import 'dart:convert';

import 'package:eldercare/services/auth_service.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Response json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('어르신 가입: 동의와 함께 서버에 가입하면 어르신 열쇠가 폰에 저장된다', () async {
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return json({'elder_key': 'nle_abc', 'status': 'pending'});
    });

    final result = await AuthService.elderlySignup(
      name: '홍길동',
      phone: '010-1111-2222',
      connectionCode: '00001234',
      agreed: true,
    );

    expect(result['success'], isTrue);
    final sent = jsonDecode(seen.body) as Map<String, dynamic>;
    expect(sent['code'], '00001234'); // 앞자리 0이 살아 있다
    expect(sent['agreed'], isTrue);
    expect(await NulbomApi.elderKey(), 'nle_abc');
  });

  test('어르신 가입: 서버가 거절하면 그 문장을 보여 주고 열쇠를 저장하지 않는다', () async {
    NulbomApi.client =
        MockClient((request) async => json({'detail': '가입 코드를 확인해 주세요'}, 401));

    final result = await AuthService.elderlySignup(
      name: '홍길동',
      phone: '010-1111-2222',
      connectionCode: '12345678',
      agreed: true,
    );

    expect(result['success'], isFalse);
    expect(result['message'], '가입 코드를 확인해 주세요');
    expect(await NulbomApi.elderKey(), isNull);
  });

  test('어르신 로그인: 이 폰이 연결되지 않았으면 가입으로 안내한다', () async {
    final result = await AuthService.elderlyLogin(phone: '010-1111-2222');

    expect(result['success'], isFalse);
    expect(result['message'], contains('회원가입'));
  });

  test('어르신 로그인: 연결된 폰이면 전화번호로 들어간다', () async {
    SharedPreferences.setMockInitialValues({'elder_key': 'nle_saved'});

    final result = await AuthService.elderlyLogin(phone: '010-1111-2222');

    expect(result['success'], isTrue);
  });
}
