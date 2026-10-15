import 'dart:convert';

import 'package:eldercare/screens/guardian_screen.dart';
import 'package:eldercare/screens/guardian_signup_screen.dart';
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

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
    NulbomApi.guardianKey = '';
  });
  tearDown(() => NulbomApi.guardianKey = '');

  testWidgets('가입하면 완료 화면이 운영자 확인을 알리고, 시작하기는 로그인 없이 보호자 홈으로 간다', (tester) async {
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    NulbomApi.client = MockClient((request) async {
      final path = request.url.path;
      if (path == '/v1/guardian/signup') {
        return json({
          'key': 'nlb_new',
          'name': '김보호',
          'email': 'kim@example.com',
          'phone': '010-1111-2222',
          'activated': false,
        });
      }
      if (path == '/v1/guardian/elders') return json({'elders': []});
      if (path == '/v1/guardian/alerts') return json({'alerts': []});
      return json({'detail': 'x'}, 404);
    });

    await tester.pumpWidget(const MaterialApp(home: GuardianSignupScreen()));
    final fields = find.byType(TextField);
    await tester.enterText(fields.at(0), '김보호');
    await tester.enterText(fields.at(1), 'kim@example.com');
    await tester.enterText(fields.at(2), '010-1111-2222');
    await tester.enterText(fields.at(3), 'correct-horse-1');
    await tester.enterText(fields.at(4), 'correct-horse-1');
    await tester.tap(find.text('회원가입 완료'));
    await tester.pumpAndSettle();

    expect(find.text('회원가입이 완료되었습니다'), findsOneWidget);
    expect(find.textContaining('운영자 확인 후 어르신을 연결할 수 있어요'), findsOneWidget);
    expect(find.text('로그인하러 가기'), findsNothing); // 열쇠가 이미 폰에 있다
    expect(NulbomApi.guardianKey, 'nlb_new');

    await tester.tap(find.text('시작하기'));
    await tester.pumpAndSettle();

    expect(find.byType(GuardianScreen), findsOneWidget);
    expect(find.text('관리 중인 어르신이 아직 없어요.'), findsOneWidget);
  });
}
