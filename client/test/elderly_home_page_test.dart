import 'dart:convert';

import 'package:eldercare/screens/elderly_home_page.dart';
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

/// 어르신 홈의 탭들이 읽는 주소에 빈 자료를 주고, 연결 코드 주소만 테스트가 정한다.
http.Client server(List<String> calls, http.Response Function() linkCode) =>
    MockClient((request) async {
      final path = request.url.path;
      calls.add('${request.method} $path');
      if (path == '/v1/me/link-code') return linkCode();
      if (path == '/v1/me/calls') return json({'calls': []});
      if (path == '/v1/me/contacts') return json({'guardians': [], 'contacts': []});
      return json({'detail': 'x'}, 404);
    });

Future<void> openMenuCode(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(const MaterialApp(home: ElderlyHomePage()));
  await tester.pumpAndSettle();
  await tester.tap(find.byIcon(Icons.more_horiz_rounded));
  await tester.pumpAndSettle();
  expect(find.text('로그아웃'), findsOneWidget);
  await tester.tap(find.text('내 연결코드'));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({
      'elder_key': 'nle_saved',
      'ai_friend_name': '봄이', // 첫 실행 이름 짓기 대화상자를 건너뛴다
    });
  });

  testWidgets('내 연결코드: 서버에서 새 코드를 받아 보여 준다', (tester) async {
    final calls = <String>[];
    NulbomApi.client = server(
      calls,
      () => json({'code': '04829316', 'expires_at': '2026-10-16T14:30:00+09:00'}),
    );

    await openMenuCode(tester);

    expect(calls, contains('POST /v1/me/link-code'));
    expect(find.text('04829316'), findsOneWidget);
    expect(find.textContaining('24시간'), findsOneWidget);
  });

  testWidgets('내 연결코드: 이미 연결된 어르신(409)에게는 이미 연결돼 있다고 알린다', (tester) async {
    NulbomApi.client = server(
      <String>[],
      () => json({'detail': '이미 보호자가 연결돼 있어요'}, 409),
    );

    await openMenuCode(tester);

    expect(find.text('이미 보호자와 연결돼 있어요'), findsOneWidget);
    await tester.tap(find.text('닫기'));
    await tester.pumpAndSettle();
    expect(find.text('이미 보호자와 연결돼 있어요'), findsNothing);
  });
}
