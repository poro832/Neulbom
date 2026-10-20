import 'dart:convert';

import 'package:eldercare/screens/call_request_dialog.dart';
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

  Future<void> openDialog(WidgetTester tester, {Duration autoClose = const Duration(minutes: 1)}) async {
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (context) => Scaffold(
          body: Center(
            child: TextButton(
              onPressed: () => showCallRequestDialog(context, autoClose: autoClose),
              child: const Text('통화하기'),
            ),
          ),
        ),
      ),
    ));
    await tester.tap(find.text('통화하기'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  testWidgets('통화하기를 누르면 화면이 바뀌지 않고 팝업으로 알린다', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await NulbomApi.saveElderKey('nle_${'x' * 39}');
    String? path;
    NulbomApi.client = MockClient((request) async {
      path = request.url.path;
      return _json({'call_id': 7, 'status': 'requested'}, 202);
    });

    await openDialog(tester);

    expect(path, '/v1/me/call-request');
    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.textContaining('전화가 곧 가요.'), findsOneWidget);
    expect(find.textContaining('전화가 오면 받아주세요.'), findsOneWidget);
    // 뒤에 있는 화면이 그대로다(새 화면으로 넘어가지 않았다).
    expect(find.text('통화하기'), findsOneWidget);
  });

  testWidgets('팝업은 1분 뒤에 저절로 닫힌다', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await NulbomApi.saveElderKey('nle_${'x' * 39}');
    NulbomApi.client =
        MockClient((request) async => _json({'call_id': 7, 'status': 'requested'}, 202));

    await openDialog(tester);
    expect(find.byType(AlertDialog), findsOneWidget);

    await tester.pump(const Duration(seconds: 59));
    expect(find.byType(AlertDialog), findsOneWidget);

    await tester.pump(const Duration(seconds: 2));
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsNothing);
  });

  testWidgets('확인을 누르면 바로 닫힌다', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await NulbomApi.saveElderKey('nle_${'x' * 39}');
    NulbomApi.client =
        MockClient((request) async => _json({'call_id': 7, 'status': 'requested'}, 202));

    await openDialog(tester);
    await tester.tap(find.text('확인'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsNothing);
  });

  testWidgets('연결 전이면 서버가 알려 준 이유를 팝업에 보인다', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await NulbomApi.saveElderKey('nle_${'x' * 39}');
    NulbomApi.client = MockClient(
        (request) async => _json({'detail': '보호자가 연결하기 전에는 전화를 걸 수 없어요'}, 403));

    await openDialog(tester);

    expect(find.textContaining('연결하기 전에는'), findsOneWidget);
    expect(find.textContaining('전화가 곧 가요'), findsNothing);
  });
}
