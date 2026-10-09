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

Future<void> fill(WidgetTester tester) async {
  final fields = find.byType(TextField);
  await tester.enterText(fields.at(0), '홍길동');
  await tester.enterText(fields.at(1), '010-9999-1111');
  await tester.enterText(fields.at(2), '00001234');
}

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('동의에 체크하지 않으면 서버를 부르지 않고 안내한다', (tester) async {
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    var called = false;
    NulbomApi.client = MockClient((request) async {
      called = true;
      return json({});
    });

    await tester.pumpWidget(const MaterialApp(home: ElderlySignupScreen()));
    await fill(tester);
    await tester.tap(find.text('회원가입 완료'));
    await tester.pumpAndSettle();

    expect(find.text('안부 전화를 받는 데 동의해 주세요.'), findsOneWidget);
    expect(called, isFalse);
  });

  testWidgets('동의하고 제출하면 가입 요청이 나가고 승인 대기 화면으로 간다', (tester) async {
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    final posts = <Map<String, dynamic>>[];
    NulbomApi.client = MockClient((request) async {
      if (request.method == 'POST' && request.url.path == '/v1/signup') {
        posts.add(jsonDecode(request.body) as Map<String, dynamic>);
        return json({'elder_key': 'nle_new', 'status': 'pending'});
      }
      return json({'status': 'pending', 'name': '홍길동'}); // /v1/me/status
    });

    await tester.pumpWidget(const MaterialApp(home: ElderlySignupScreen()));
    await fill(tester);
    await tester.tap(find.byType(Checkbox));
    await tester.pump();
    await tester.tap(find.text('회원가입 완료'));
    await tester.pumpAndSettle(const Duration(seconds: 3));

    expect(posts, [
      {'code': '00001234', 'name': '홍길동', 'phone': '010-9999-1111', 'agreed': true}
    ]);
    expect(find.text('보호자 승인을 기다리고 있어요'), findsOneWidget);
  });

  testWidgets('서버가 거절하면 그 문장을 보여 준다', (tester) async {
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    NulbomApi.client =
        MockClient((request) async => json({'detail': '가입 코드를 확인해 주세요'}, 401));

    await tester.pumpWidget(const MaterialApp(home: ElderlySignupScreen()));
    await fill(tester);
    await tester.tap(find.byType(Checkbox));
    await tester.pump();
    await tester.tap(find.text('회원가입 완료'));
    await tester.pumpAndSettle();

    expect(find.text('가입 코드를 확인해 주세요'), findsOneWidget);
  });
}
