import 'dart:convert';

import 'package:eldercare/screens/elderly_home_page.dart';
import 'package:eldercare/screens/guardian_account_screen.dart';
import 'package:eldercare/screens/text_size_sheet.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:eldercare/services/text_size.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Response _json(Object body) =>
    http.Response(jsonEncode(body), 200, headers: {'content-type': 'application/json; charset=utf-8'});

void _bigScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
}

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({'elder_key': 'nle_saved', 'ai_friend_name': '봄이'});
    textSizeIndex.value = textSizeDefaultIndex;
  });
  tearDown(() => textSizeIndex.value = textSizeDefaultIndex);

  Future<void> openSheet(WidgetTester tester) async {
    _bigScreen(tester);
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (context) => Scaffold(
          body: TextButton(onPressed: () => showTextSizeSheet(context), child: const Text('열기')),
        ),
      ),
    ));
    await tester.tap(find.text('열기'));
    await tester.pumpAndSettle();
  }

  testWidgets('글자 크기 창: 4단계가 보이고 현재 단계가 표시된다', (tester) async {
    await openSheet(tester);

    expect(find.byKey(const Key('text-size-sheet')), findsOneWidget);
    for (var i = 0; i < textSizeOptions.length; i++) {
      expect(find.byKey(Key('text-size-$i')), findsOneWidget);
    }
    // 기본인 "보통"에만 체크 표시가 있다.
    expect(find.descendant(of: find.byKey(const Key('text-size-1')), matching: find.byIcon(Icons.check_circle_rounded)),
        findsOneWidget);
    expect(find.byIcon(Icons.check_circle_rounded), findsOneWidget);
  });

  testWidgets('글자 크기 창: 단계를 고르면 바로 바뀌고 저장되며 창은 열려 있다', (tester) async {
    await openSheet(tester);

    await tester.tap(find.byKey(const Key('text-size-3')));
    await tester.pumpAndSettle();

    expect(textSizeIndex.value, 3);
    expect((await SharedPreferences.getInstance()).getInt('app_text_size_index'), 3);
    expect(find.byKey(const Key('text-size-sheet')), findsOneWidget);

    await tester.tap(find.byKey(const Key('text-size-done')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('text-size-sheet')), findsNothing);
  });

  testWidgets('어르신 홈: ... 메뉴에 글자 크기가 있고 누르면 창이 열린다', (tester) async {
    _bigScreen(tester);
    NulbomApi.client = MockClient((request) async {
      final path = request.url.path;
      if (path == '/v1/me/calls') return _json({'calls': []});
      if (path == '/v1/me/contacts') return _json({'guardians': [], 'contacts': []});
      return http.Response('{}', 404);
    });
    await tester.pumpWidget(const MaterialApp(home: ElderlyHomePage()));
    await tester.pumpAndSettle();

    await tester.tap(find.byIcon(Icons.more_horiz_rounded));
    await tester.pumpAndSettle();
    await tester.tap(find.text('글자 크기'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('text-size-sheet')), findsOneWidget);
  });

  testWidgets('보호자 계정 화면: 글자 크기 항목을 누르면 창이 열린다', (tester) async {
    _bigScreen(tester);
    NulbomApi.guardianKey = 'nlb_test';
    addTearDown(() => NulbomApi.guardianKey = '');
    NulbomApi.client = MockClient(
        (request) async => _json({'name': '김보호', 'email': 'kim@example.com', 'phone': '010-1111-2222'}));
    await tester.pumpWidget(const MaterialApp(home: GuardianAccountScreen()));
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.byKey(const Key('guardian-text-size')));
    await tester.tap(find.byKey(const Key('guardian-text-size')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('text-size-sheet')), findsOneWidget);
  });
}
