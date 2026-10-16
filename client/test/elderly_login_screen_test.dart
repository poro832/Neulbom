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
const Key codeField = Key('elder-pairing-code');
const String codeHelp = '처음 이 폰으로 들어오시나요? 보호자 앱에서 받은 6자리 코드를 입력해 주세요.';
const String codeNeeded = '연결 코드 6자리를 입력해 주세요.';

Future<void> open(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(const MaterialApp(home: ElderlyLoginScreen()));
  await tester.pumpAndSettle();
}

Future<void> submit(WidgetTester tester, {required String phone, String? code}) async {
  await tester.enterText(find.byKey(phoneField), phone);
  if (code != null) await tester.enterText(find.byKey(codeField), code);
  await tester.tap(find.text('로그인'));
  await tester.pumpAndSettle();
}

/// 연결 서버: /v1/pair가 열쇠와 이름을 주고, 어르신 문(ElderlyGate)이 묻는 상태에는 승인 대기로 답한다.
/// 부른 순서("메서드 경로")와 /v1/pair 본문, 상태 조회의 열쇠를 남긴다.
http.Client server(
  List<String> calls, {
  List<Map<String, dynamic>>? pairBodies,
  List<String?>? statusKeys,
  http.Response? pairResponse,
}) =>
    MockClient((request) async {
      final path = request.url.path;
      calls.add('${request.method} $path');
      if (path == '/v1/pair') {
        pairBodies?.add(jsonDecode(request.body) as Map<String, dynamic>);
        return pairResponse ?? json({'elder_key': 'nle_paired', 'elder_name': '이동한'});
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

  group('이 폰에 어르신 열쇠가 없으면', () {
    testWidgets('전화번호 아래에 연결 코드 칸과 설명이 보인다', (tester) async {
      await open(tester);

      expect(find.byKey(codeField), findsOneWidget);
      expect(find.text('연결 코드(6자리)'), findsOneWidget);
      expect(find.text(codeHelp), findsOneWidget);
      expect(
        tester.getTopLeft(find.byKey(codeField)).dy,
        greaterThan(tester.getTopLeft(find.byKey(phoneField)).dy),
      );
      final field = tester.widget<TextField>(find.byKey(codeField));
      expect(field.keyboardType, TextInputType.number);
      expect(field.maxLength, 6);
    });

    testWidgets('열쇠를 읽기 전 첫 화면에는 코드 칸을 그리지 않는다(깜빡이지 않게)', (tester) async {
      await tester.pumpWidget(const MaterialApp(home: ElderlyLoginScreen()));

      expect(find.byKey(codeField), findsNothing);
      expect(find.text(codeHelp), findsNothing);

      await tester.pumpAndSettle();
      expect(find.byKey(codeField), findsOneWidget);
    });

    testWidgets('코드 칸에는 숫자만, 6자까지만 들어간다', (tester) async {
      await open(tester);

      await tester.enterText(find.byKey(codeField), '12a3456789');
      await tester.pump();

      expect(tester.widget<TextField>(find.byKey(codeField)).controller!.text, '123456');
    });

    for (final (label, code) in [('코드 없이', ''), ('5자리로', '01234')]) {
      testWidgets('$label 누르면 서버를 부르지 않고 코드를 입력하라고 안내한다', (tester) async {
        final calls = <String>[];
        NulbomApi.client = server(calls);

        await open(tester);
        await submit(tester, phone: '010-2222-3333', code: code);

        expect(find.text(codeNeeded), findsOneWidget);
        expect(calls, isEmpty);
        expect(find.byType(ElderlyGate), findsNothing);
      });
    }

    testWidgets('전화번호가 없으면 서버를 부르지 않고 번호를 입력하라고 안내한다', (tester) async {
      final calls = <String>[];
      NulbomApi.client = server(calls);

      await open(tester);
      await submit(tester, phone: '', code: '012345');

      expect(find.text('전화번호를 입력해주세요.'), findsOneWidget);
      expect(calls, isEmpty);
    });

    testWidgets('번호와 코드가 맞으면 /v1/pair로 연결하고 열쇠를 저장한 뒤 어르신 문으로 간다', (tester) async {
      final calls = <String>[];
      final bodies = <Map<String, dynamic>>[];
      final statusKeys = <String?>[];
      NulbomApi.client = server(calls, pairBodies: bodies, statusKeys: statusKeys);

      await open(tester);
      await submit(tester, phone: '010-2222-3333', code: '012345');

      expect(bodies, [
        {'code': '012345', 'phone': '010-2222-3333'}, // 앞자리 0이 살아 있다
      ]);
      expect(calls.first, 'POST /v1/pair');
      expect(await NulbomApi.elderKey(), 'nle_paired');
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('user_type'), 'elderly'); // 앱을 다시 열면 어르신 문으로 간다
      expect(prefs.getString('name'), '이동한');
      expect(prefs.getString('phone'), '010-2222-3333');
      expect(prefs.getBool('is_logged_in'), isTrue);
      expect(find.byType(ElderlyGate), findsOneWidget);
      expect(find.byType(ElderlyLoginScreen), findsNothing); // 스택을 비웠다
      expect(statusKeys, ['Bearer nle_paired']); // 방금 받은 열쇠로 상태를 묻는다
    });

    for (final (status, detail) in [
      (401, NulbomApi.badLinkCodeMessage),
      (429, '잠시 뒤에 다시 해 주세요'),
    ]) {
      testWidgets('서버가 $status으로 거절하면 그 문장을 보여 주고 이동하지 않는다', (tester) async {
        final calls = <String>[];
        NulbomApi.client = server(calls, pairResponse: json({'detail': detail}, status));

        await open(tester);
        await submit(tester, phone: '010-2222-3333', code: '012345');

        expect(find.text(detail), findsOneWidget);
        expect(find.byType(ElderlyGate), findsNothing);
        expect(find.byType(ElderlyLoginScreen), findsOneWidget);
        expect(calls, ['POST /v1/pair']);
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
      await submit(tester, phone: '010-2222-3333', code: '012345');

      expect(find.text('서버에 연결하지 못했어요. 잠시 뒤에 다시 해 주세요.'), findsOneWidget);
      expect(find.byType(ElderlyGate), findsNothing);
    });

    testWidgets('연결하는 동안에는 버튼을 막아 두 번 보내지 않는다', (tester) async {
      final reply = Completer<http.Response>();
      var pairs = 0;
      NulbomApi.client = MockClient((request) async {
        if (request.url.path == '/v1/pair') {
          pairs++;
          return reply.future;
        }
        return json({'status': 'pending', 'name': '이동한', 'share_agreed': true});
      });

      await open(tester);
      await tester.enterText(find.byKey(phoneField), '010-2222-3333');
      await tester.enterText(find.byKey(codeField), '012345');
      await tester.tap(find.text('로그인'));
      await tester.pump();

      expect(tester.widget<ElevatedButton>(find.byType(ElevatedButton)).onPressed, isNull);
      await tester.tap(find.byType(ElevatedButton));
      await tester.pump();
      expect(pairs, 1);

      reply.complete(json({'elder_key': 'nle_paired', 'elder_name': '이동한'}));
      await tester.pumpAndSettle();
      expect(pairs, 1);
      expect(find.byType(ElderlyGate), findsOneWidget);
    });
  });

  group('이 폰에 어르신 열쇠가 이미 있으면', () {
    setUp(() => SharedPreferences.setMockInitialValues({'elder_key': 'nle_saved'}));

    testWidgets('코드 칸 없이 번호만 받는다', (tester) async {
      await open(tester);

      expect(find.byKey(phoneField), findsOneWidget);
      expect(find.byKey(codeField), findsNothing);
      expect(find.text(codeHelp), findsNothing);
    });

    testWidgets('번호만으로 들어가고 연결 주소는 부르지 않는다', (tester) async {
      final calls = <String>[];
      final statusKeys = <String?>[];
      NulbomApi.client = server(calls, statusKeys: statusKeys);

      await open(tester);
      await submit(tester, phone: '010-2222-3333');

      expect(calls, isNot(contains('POST /v1/pair')));
      expect(find.byType(ElderlyGate), findsOneWidget);
      expect(statusKeys, ['Bearer nle_saved']);
    });
  });
}
