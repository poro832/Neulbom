import 'dart:convert';

import 'package:eldercare/screens/elderly_signup_screen.dart';
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

Future<void> open(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(const MaterialApp(home: ElderlySignupScreen()));
}

Future<void> fill(WidgetTester tester) async {
  final fields = find.byType(TextField);
  await tester.enterText(fields.at(0), '홍길동');
  await tester.enterText(fields.at(1), '010-9999-1111');
}

Future<void> agreeAndSubmit(WidgetTester tester) async {
  await tester.tap(find.byType(Checkbox));
  await tester.pump();
  await tester.tap(find.text('회원가입 완료'));
  await tester.pumpAndSettle();
}

/// 어르신 먼저 가입 서버: 가입하면 열쇠와 고정 연결 코드를 준다(코드를 안 주는 서버도 흉내 낸다). 부른 순서를 남긴다.
http.Client server(
  List<String> calls, {
  List<Map<String, dynamic>>? bodies,
  int codeStatus = 200,
  bool codeInSignup = true,
}) =>
    MockClient((request) async {
      final path = request.url.path;
      calls.add('${request.method} $path');
      if (path == '/v1/elders/signup') {
        bodies?.add(jsonDecode(request.body) as Map<String, dynamic>);
        return json({
          'elder_key': 'nle_new',
          'status': 'unlinked',
          if (codeInSignup) 'link_code': '04829316',
        });
      }
      if (path == '/v1/me/link-code') {
        expect(request.headers['Authorization'], 'Bearer nle_new'); // 방금 저장한 어르신 열쇠
        if (codeStatus != 200) return json({'detail': '잠시 뒤에 다시 해 주세요'}, codeStatus);
        return json({'code': '04829316'});
      }
      if (path == '/v1/me/status') {
        return json({'status': 'unlinked', 'name': '홍길동', 'share_agreed': true});
      }
      return json({'detail': 'x'}, 404);
    });

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('보호자 코드 칸 없이 이름과 전화번호만 받는다', (tester) async {
    await open(tester);

    expect(find.byType(TextField), findsNWidgets(2));
    expect(find.textContaining('보호자 코드'), findsNothing);
    expect(find.textContaining('보호자 연결 코드'), findsNothing);
  });

  testWidgets('동의에 체크하지 않으면 서버를 부르지 않고 안내한다', (tester) async {
    var called = false;
    NulbomApi.client = MockClient((request) async {
      called = true;
      return json({});
    });

    await open(tester);
    await fill(tester);
    await tester.tap(find.text('회원가입 완료'));
    await tester.pumpAndSettle();

    expect(find.text('안부 전화를 받는 데 동의해 주세요.'), findsOneWidget);
    expect(called, isFalse);
  });

  testWidgets('동의 문구가 통화 내용 공유를 알린다', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: ElderlySignupScreen()));
    await tester.pumpAndSettle();

    expect(find.textContaining('통화 내용이 보호자에게 요약과 원문으로 공유'), findsOneWidget);
  });

  testWidgets('동의하고 가입하면 서버가 준 8자리 연결 코드를 완료 화면에 보여 준다', (tester) async {
    final calls = <String>[];
    final bodies = <Map<String, dynamic>>[];
    NulbomApi.client = server(calls, bodies: bodies);

    await open(tester);
    await fill(tester);
    await agreeAndSubmit(tester);

    expect(calls, ['POST /v1/elders/signup']); // 구 /v1/signup이 아니다. 코드는 가입 응답에 들어 있다
    expect(bodies, [
      {'name': '홍길동', 'phone': '010-9999-1111', 'agreed': true}
    ]);
    expect(find.text('회원가입이 완료되었습니다'), findsOneWidget);
    expect(find.text('04829316'), findsOneWidget); // 앞자리 0이 살아 있는 서버 코드
    expect(find.textContaining('바뀌지 않아요'), findsOneWidget);
    expect(find.textContaining('24시간'), findsNothing);
    expect(await NulbomApi.elderKey(), 'nle_new');
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('user_type'), 'elderly'); // 앱을 다시 열면 어르신 문으로 간다
    expect(prefs.getBool('is_logged_in'), isTrue);
  });

  testWidgets('완료 화면의 확인은 어르신 문으로 가고, 받은 코드를 새로 받지 않고 그대로 보여 준다', (tester) async {
    final calls = <String>[];
    NulbomApi.client = server(calls);

    await open(tester);
    await fill(tester);
    await agreeAndSubmit(tester);
    await tester.tap(find.text('확인'));
    await tester.pumpAndSettle();

    expect(find.text('보호자 연결을 기다리고 있어요'), findsOneWidget);
    expect(find.text('04829316'), findsOneWidget);
    expect(find.text('새 코드 만들기'), findsOneWidget);
    expect(calls.where((c) => c.endsWith('/v1/me/link-code')), isEmpty); // 코드를 다시 묻지도, 새로 만들지도 않는다
    expect(calls.last, 'GET /v1/me/status');
  });

  testWidgets('서버가 거절하면 그 문장을 보여 주고 열쇠를 저장하지 않는다', (tester) async {
    final calls = <String>[];
    NulbomApi.client = MockClient((request) async {
      calls.add(request.url.path);
      return json({'detail': '이미 등록된 번호예요'}, 409);
    });

    await open(tester);
    await fill(tester);
    await agreeAndSubmit(tester);

    expect(find.text('이미 등록된 번호예요'), findsOneWidget);
    expect(find.text('회원가입이 완료되었습니다'), findsNothing);
    expect(calls, ['/v1/elders/signup']);
    expect(await NulbomApi.elderKey(), isNull);
  });

  testWidgets('가입 응답에 코드가 없으면 서버에서 읽어 오고, 새로 만들지는 않는다', (tester) async {
    final calls = <String>[];
    NulbomApi.client = server(calls, codeInSignup: false);

    await open(tester);
    await fill(tester);
    await agreeAndSubmit(tester);

    expect(find.text('04829316'), findsOneWidget);
    expect(calls, ['POST /v1/elders/signup', 'GET /v1/me/link-code']);
  });

  testWidgets('가입은 됐는데 코드를 못 받으면 다음 화면에서 다시 볼 수 있다고 안내한다', (tester) async {
    NulbomApi.client = server(<String>[], codeStatus: 503, codeInSignup: false);

    await open(tester);
    await fill(tester);
    await agreeAndSubmit(tester);

    expect(find.text('회원가입이 완료되었습니다'), findsOneWidget);
    expect(find.textContaining('다음 화면에서 다시 볼 수 있어요'), findsOneWidget);
    expect(find.text('잠시 뒤에 다시 해 주세요'), findsOneWidget);
    expect(await NulbomApi.elderKey(), 'nle_new');
  });
}
