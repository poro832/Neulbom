import 'dart:async';
import 'dart:convert';

import 'package:eldercare/screens/elderly_gate.dart';
import 'package:eldercare/screens/elderly_login_screen.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Response json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

const Key phoneField = Key('elder-login-phone');
const Key oldCodeField = Key('elder-pairing-code');
const String newPhoneHint = '폰을 바꿨다면 보호자가 어르신 관리에서 번호를 고친 뒤 24시간 안에 한 번 로그인할 수 있어요.';

Future<void> open(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(const MaterialApp(home: ElderlyLoginScreen()));
  await tester.pumpAndSettle();
}

Future<void> submit(WidgetTester tester, {required String phone}) async {
  await tester.enterText(find.byKey(phoneField), phone);
  await tester.tap(find.text('로그인'));
  await tester.pumpAndSettle();
}

/// 서버: /v1/elders/login(새 폰 로그인)이 열쇠와 이름을 주고, 어르신 문(ElderlyGate)이 묻는 상태에는 승인 대기로 답한다.
/// 부른 순서("메서드 경로")와 새 폰 로그인 본문, 상태 조회의 열쇠를 남긴다.
http.Client server(
  List<String> calls, {
  List<Map<String, dynamic>>? loginBodies,
  List<String?>? statusKeys,
  http.Response? loginResponse,
}) =>
    MockClient((request) async {
      final path = request.url.path;
      calls.add('${request.method} $path');
      if (path == '/v1/elders/login') {
        loginBodies?.add(jsonDecode(request.body) as Map<String, dynamic>);
        return loginResponse ?? json({'elder_key': 'nle_newphone', 'elder_name': '이동한'});
      }
      if (path == '/v1/me/status') {
        statusKeys?.add(request.headers['Authorization']);
        return json({'status': 'pending', 'name': '이동한', 'share_agreed': true});
      }
      return json({'detail': 'x'}, 404);
    });

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
  });

  group('이 폰에 어르신 열쇠가 없으면(새 폰)', () {
    testWidgets('연결 코드 칸은 없고 번호만 받으며 새 폰 안내가 보인다', (tester) async {
      await open(tester);

      expect(find.byKey(phoneField), findsOneWidget);
      expect(find.byKey(oldCodeField), findsNothing);
      expect(find.text('연결 코드(6자리)'), findsNothing);
      expect(find.text(newPhoneHint), findsOneWidget);
      expect(find.byType(TextField), findsOneWidget);
    });

    testWidgets('전화번호가 없으면 서버를 부르지 않고 번호를 입력하라고 안내한다', (tester) async {
      final calls = <String>[];
      NulbomApi.client = server(calls);

      await open(tester);
      await submit(tester, phone: '');

      expect(find.text('전화번호를 입력해주세요.'), findsOneWidget);
      expect(calls, isEmpty);
    });

    testWidgets('너무 짧은 번호면 서버를 부르지 않고 안내한다', (tester) async {
      final calls = <String>[];
      NulbomApi.client = server(calls);

      await open(tester);
      await submit(tester, phone: '0102222');

      expect(find.text('유효한 전화번호를 입력해주세요.'), findsOneWidget);
      expect(calls, isEmpty);
      expect(find.byType(ElderlyGate), findsNothing);
    });

    testWidgets('번호만 보내 새 폰 로그인을 하고, 열쇠를 저장한 뒤 어르신 문으로 간다', (tester) async {
      final calls = <String>[];
      final bodies = <Map<String, dynamic>>[];
      final statusKeys = <String?>[];
      NulbomApi.client = server(calls, loginBodies: bodies, statusKeys: statusKeys);

      await open(tester);
      await submit(tester, phone: '010-2222-3333');

      expect(bodies, [
        {'phone': '010-2222-3333'}, // 코드 없이 번호만 간다
      ]);
      expect(calls.first, 'POST /v1/elders/login');
      expect(await NulbomApi.elderKey(), 'nle_newphone');
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('user_type'), 'elderly'); // 앱을 다시 열면 어르신 문으로 간다
      expect(prefs.getString('name'), '이동한');
      expect(prefs.getString('phone'), '010-2222-3333');
      expect(prefs.getBool('is_logged_in'), isTrue);
      expect(find.byType(ElderlyGate), findsOneWidget);
      expect(find.byType(ElderlyLoginScreen), findsNothing); // 스택을 비웠다
      expect(statusKeys, ['Bearer nle_newphone']); // 방금 받은 열쇠로 상태를 묻는다
    });

    for (final (status, detail) in [
      (401, '이 폰으로는 로그인할 수 없어요. 보호자에게 어르신 관리에서 번호를 확인해 달라고 부탁해 주세요'),
      (429, '잠시 뒤에 다시 해 주세요'),
    ]) {
      testWidgets('서버가 $status으로 거절하면 그 문장을 보여 주고 이동하지 않는다', (tester) async {
        final calls = <String>[];
        NulbomApi.client = server(calls, loginResponse: json({'detail': detail}, status));

        await open(tester);
        await submit(tester, phone: '010-2222-3333');

        expect(find.text(detail), findsOneWidget);
        expect(find.byType(ElderlyGate), findsNothing);
        expect(find.byType(ElderlyLoginScreen), findsOneWidget);
        expect(calls, ['POST /v1/elders/login']);
        expect(await NulbomApi.elderKey(), isNull);
        final prefs = await SharedPreferences.getInstance();
        expect(prefs.getBool('is_logged_in'), isNull);
        // 다시 해 볼 수 있다
        expect(tester.widget<ElevatedButton>(find.byType(ElevatedButton)).onPressed, isNotNull);
      });
    }

    testWidgets('서버에 닿지 못하면 연결하지 못했다고 안내한다', (tester) async {
      NulbomApi.client = MockClient((request) async => throw http.ClientException('끊김'));

      await open(tester);
      await submit(tester, phone: '010-2222-3333');

      expect(find.text('서버에 연결하지 못했어요. 잠시 뒤에 다시 해 주세요.'), findsOneWidget);
      expect(find.byType(ElderlyGate), findsNothing);
    });

    testWidgets('로그인하는 동안에는 버튼을 막아 두 번 보내지 않는다', (tester) async {
      final reply = Completer<http.Response>();
      var logins = 0;
      NulbomApi.client = MockClient((request) async {
        if (request.url.path == '/v1/elders/login') {
          logins++;
          return reply.future;
        }
        return json({'status': 'pending', 'name': '이동한', 'share_agreed': true});
      });

      await open(tester);
      await tester.enterText(find.byKey(phoneField), '010-2222-3333');
      await tester.tap(find.text('로그인'));
      await tester.pump();

      expect(tester.widget<ElevatedButton>(find.byType(ElevatedButton)).onPressed, isNull);
      await tester.tap(find.byType(ElevatedButton));
      await tester.pump();
      expect(logins, 1);

      reply.complete(json({'elder_key': 'nle_newphone', 'elder_name': '이동한'}));
      await tester.pumpAndSettle();
      expect(logins, 1);
      expect(find.byType(ElderlyGate), findsOneWidget);
    });
  });

  group('이 폰에 어르신 열쇠가 이미 있으면', () {
    setUp(() => SharedPreferences.setMockInitialValues({'elder_key': 'nle_saved'}));

    testWidgets('번호만 받는다', (tester) async {
      await open(tester);

      expect(find.byKey(phoneField), findsOneWidget);
      expect(find.byKey(oldCodeField), findsNothing);
    });

    testWidgets('번호만으로 들어가고 새 폰 로그인 주소는 부르지 않는다', (tester) async {
      final calls = <String>[];
      final statusKeys = <String?>[];
      NulbomApi.client = server(calls, statusKeys: statusKeys);

      await open(tester);
      await submit(tester, phone: '010-2222-3333');

      expect(calls, isNot(contains('POST /v1/elders/login')));
      expect(find.byType(ElderlyGate), findsOneWidget);
      expect(statusKeys, ['Bearer nle_saved']);
    });
  });
}
