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

  test('어르신 가입: 서버가 코드를 받아 주면 어르신 열쇠가 폰에 저장된다', () async {
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return json({'elder_key': 'nle_abc', 'elder_name': '어르신 12'});
    });

    final result = await AuthService.elderlySignup(
      name: '홍길동',
      phone: '010-1111-2222',
      connectionCode: '000123',
    );

    expect(result['success'], isTrue);
    expect(jsonDecode(seen.body)['code'], '000123'); // 앞자리 0이 살아 있다
    expect(await NulbomApi.elderKey(), 'nle_abc');
  });

  test('어르신 가입: 가짜 코드 123456은 더 이상 통과하지 않는다 (서버가 거절하면 그 문장을 보여 준다)', () async {
    NulbomApi.client =
        MockClient((request) async => json({'detail': '연결 코드를 확인해 주세요'}, 401));

    final result = await AuthService.elderlySignup(
      name: '홍길동',
      phone: '010-1111-2222',
      connectionCode: '123456',
    );

    expect(result['success'], isFalse);
    expect(result['message'], '연결 코드를 확인해 주세요');
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
