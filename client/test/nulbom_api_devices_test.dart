import 'dart:convert';

import 'package:eldercare/services/nulbom_api.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  tearDown(() => NulbomApi.guardianKey = '');

  test('폰 등록: 보호자 열쇠로 토큰을 보낸다', () async {
    NulbomApi.guardianKey = 'nlb_test';
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return http.Response('', 204);
    });

    await NulbomApi.registerDevice('token-aaaaaaaaaaaaaaaaaaaa');

    expect(seen.url.path, '/v1/guardian/devices');
    expect(seen.method, 'POST');
    expect(seen.headers['Authorization'], 'Bearer nlb_test');
    expect(jsonDecode(seen.body), {'token': 'token-aaaaaaaaaaaaaaaaaaaa'});
  });

  test('폰 해제: 같은 토큰을 해제 주소로 보낸다', () async {
    NulbomApi.guardianKey = 'nlb_test';
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return http.Response('', 204);
    });

    await NulbomApi.unregisterDevice('token-aaaaaaaaaaaaaaaaaaaa');

    expect(seen.url.path, '/v1/guardian/devices/unregister');
    expect(jsonDecode(seen.body), {'token': 'token-aaaaaaaaaaaaaaaaaaaa'});
  });

  test('열쇠가 없으면 서버를 부르기 전에 로그인이 필요하다고 알린다', () async {
    var called = false;
    NulbomApi.client = MockClient((request) async {
      called = true;
      return http.Response('', 204);
    });

    await expectLater(
      NulbomApi.registerDevice('token-aaaaaaaaaaaaaaaaaaaa'),
      throwsA(isA<ApiException>().having((e) => e.statusCode, 'status', 401)),
    );
    expect(called, isFalse);
  });
}
