import 'dart:convert';

import 'package:eldercare/screens/calling_screen.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Response _json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('어르신 통화하기: 어르신 열쇠로 본인 주소를 부른다(보호자 주소가 아니다)', () async {
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return _json({'call_id': 7, 'status': 'requested'}, 202);
    });

    await NulbomApi.requestMyCall(key: 'nle_test');

    expect(seen.method, 'POST');
    expect(seen.url.path, '/v1/me/call-request');
    expect(seen.headers['Authorization'], 'Bearer nle_test');
  });

  test('이미 전화가 오는 중(409)은 오류가 아니다', () async {
    NulbomApi.client =
        MockClient((request) async => _json({'call_id': 7, 'status': 'in_progress'}, 409));

    await NulbomApi.requestMyCall(key: 'nle_test');
  });

  test('연결 전 어르신(403)은 서버가 알려 준 이유로 실패한다', () async {
    NulbomApi.client = MockClient(
        (request) async => _json({'detail': '보호자가 연결하기 전에는 전화를 걸 수 없어요'}, 403));

    await expectLater(
      NulbomApi.requestMyCall(key: 'nle_test'),
      throwsA(isA<ApiException>()
          .having((e) => e.statusCode, 'statusCode', 403)
          .having((e) => e.message, 'message', contains('연결하기 전에는'))),
    );
  });

  test('열쇠가 없는 폰은 서버를 부르지 않고 실패한다', () async {
    var called = false;
    NulbomApi.client = MockClient((request) async {
      called = true;
      return _json({}, 202);
    });

    await expectLater(NulbomApi.requestMyCall(), throwsA(isA<ApiException>()));
    expect(called, isFalse);
  });

  testWidgets('대기 화면은 전화 요청이 가면 "곧 전화가 갑니다"를 보인다', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await NulbomApi.saveElderKey('nle_${'x' * 39}');
    String? path;
    NulbomApi.client = MockClient((request) async {
      path = request.url.path;
      return _json({'call_id': 7, 'status': 'requested'}, 202);
    });

    await tester.pumpWidget(const MaterialApp(home: CallingScreen()));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(path, '/v1/me/call-request');
    expect(find.textContaining('곧 전화가'), findsOneWidget);
  });

  testWidgets('연결 전이면 서버가 알려 준 이유를 화면에 보인다', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await NulbomApi.saveElderKey('nle_${'x' * 39}');
    NulbomApi.client = MockClient(
        (request) async => _json({'detail': '보호자가 연결하기 전에는 전화를 걸 수 없어요'}, 403));

    await tester.pumpWidget(const MaterialApp(home: CallingScreen()));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.textContaining('전화를 걸지'), findsOneWidget);
    expect(find.textContaining('연결하기 전에는'), findsOneWidget);
  });
}
