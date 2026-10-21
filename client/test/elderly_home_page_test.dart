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
http.Client server(List<String> calls, http.Response Function(String method) linkCode) =>
    MockClient((request) async {
      final path = request.url.path;
      calls.add('${request.method} $path');
      if (path == '/v1/me/link-code') return linkCode(request.method);
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
  greetingGroup();
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({
      'elder_key': 'nle_saved',
      'ai_friend_name': '봄이', // 첫 실행 이름 짓기 대화상자를 건너뛴다
    });
  });

  testWidgets('내 연결코드: 서버에서 내 고정 코드를 읽어 보여 주고, 새로 만들지는 않는다', (tester) async {
    final calls = <String>[];
    NulbomApi.client = server(calls, (_) => json({'code': '04829316'}));

    await openMenuCode(tester);

    expect(calls, contains('GET /v1/me/link-code'));
    expect(calls, isNot(contains('POST /v1/me/link-code'))); // 보기만 한다
    expect(find.text('04829316'), findsOneWidget);
    expect(find.textContaining('바뀌지 않아요'), findsOneWidget);
    expect(find.textContaining('24시간'), findsNothing);
  });

  testWidgets('내 연결코드: 이미 보호자와 연결된 어르신도 코드를 다시 볼 수 있다', (tester) async {
    NulbomApi.client = server(<String>[], (_) => json({'code': '04829316'}));

    await openMenuCode(tester);

    expect(find.text('04829316'), findsOneWidget);
    expect(find.text('이미 보호자와 연결돼 있어요'), findsNothing);
  });

  testWidgets('내 연결코드: 새 코드 만들기는 확인을 받은 뒤에 서버를 부르고 새 코드를 보여 준다', (tester) async {
    final calls = <String>[];
    NulbomApi.client = server(
      calls,
      (method) => json({'code': method == 'POST' ? '55556666' : '04829316'}),
    );

    await openMenuCode(tester);
    await tester.tap(find.byKey(const Key('renew-link-code')));
    await tester.pumpAndSettle();
    expect(find.text('새 코드를 만들까요?'), findsOneWidget);
    expect(calls, isNot(contains('POST /v1/me/link-code')));

    await tester.tap(find.text('새로 만들기'));
    await tester.pumpAndSettle();
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pumpAndSettle();

    expect(calls, contains('POST /v1/me/link-code'));
    expect(find.text('55556666'), findsOneWidget);
    expect(find.text('04829316'), findsNothing);
  });

  testWidgets('내 연결코드: 새 코드 만들기를 취소하면 코드가 그대로다', (tester) async {
    final calls = <String>[];
    NulbomApi.client = server(calls, (_) => json({'code': '04829316'}));

    await openMenuCode(tester);
    await tester.tap(find.byKey(const Key('renew-link-code')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();

    expect(find.text('04829316'), findsOneWidget);
    expect(calls, isNot(contains('POST /v1/me/link-code')));
  });

  testWidgets('내 연결코드: 서버가 거절하면 그 문장을 보여 주고 닫기로 닫는다', (tester) async {
    NulbomApi.client = server(<String>[], (_) => json({'detail': '잠시 뒤에 다시 해 주세요'}, 503));

    await openMenuCode(tester);

    expect(find.text('잠시 뒤에 다시 해 주세요'), findsOneWidget);
    await tester.tap(find.text('닫기'));
    await tester.pumpAndSettle();
    expect(find.text('잠시 뒤에 다시 해 주세요'), findsNothing);
  });
}


void greetingTests() {
  testWidgets('상단에 안녕하세요 ○○ 어르신 인사가 뜬다', (tester) async {
    NulbomApi.client = server(<String>[], (_) => json({'code': '04829316'}));

    await tester.pumpWidget(const MaterialApp(home: ElderlyHomePage(name: '배주호')));
    await tester.pumpAndSettle();

    expect(find.text('안녕하세요, 배주호 어르신'), findsOneWidget);
  });

  testWidgets('이름을 모르면 인사를 띄우지 않는다', (tester) async {
    NulbomApi.client = server(<String>[], (_) => json({'code': '04829316'}));

    await tester.pumpWidget(const MaterialApp(home: ElderlyHomePage()));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('elder-greeting')), findsNothing);
  });
}

void greetingGroup() {
  group('인사', () {
    setUp(() {
      GoogleFonts.config.allowRuntimeFetching = false;
      SharedPreferences.setMockInitialValues({'elder_key': 'nle_saved', 'ai_friend_name': '봄이'});
    });
    greetingTests();
  });
}
