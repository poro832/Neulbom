import 'dart:convert';

import 'package:eldercare/screens/call_turns_screen.dart';
import 'package:eldercare/screens/elder_calls_screen.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

http.Response json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

Map<String, dynamic> call(int id, {String? summary, bool turns = false, String status = 'completed'}) => {
      'call_id': id,
      'started_at': '2026-10-09T09:00:00+09:00',
      'duration_s': 95,
      'status': status,
      'summary': summary,
      'has_turns': turns,
    };

Future<void> open(WidgetTester tester, Widget screen) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(MaterialApp(home: screen));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    NulbomApi.guardianKey = 'nlb_test';
  });
  tearDown(() => NulbomApi.guardianKey = '');

  group('ElderCallsScreen', () {
    const screen = ElderCallsScreen(elderId: 20, elderName: '홍길동');

    testWidgets('통화마다 요약을 보여 준다', (tester) async {
      NulbomApi.client = MockClient((request) async {
        expect(request.url.path, '/v1/elders/20/calls');
        return json({
          'share_agreed': true,
          'calls': [
            call(7, summary: '점심을 드셨어요.', turns: true),
            call(6, summary: null, turns: false, status: 'no_answer'),
          ],
        });
      });

      await open(tester, screen);

      expect(find.text('점심을 드셨어요.'), findsOneWidget);
      expect(find.text('요약이 없어요.'), findsOneWidget);
      expect(find.textContaining('우울'), findsNothing);
    });

    testWidgets('어르신이 동의하기 전에는 동의 안내만 보인다', (tester) async {
      NulbomApi.client =
          MockClient((request) async => json({'share_agreed': false, 'calls': []}));

      await open(tester, screen);

      expect(find.text('어르신이 동의한 뒤에 볼 수 있어요.'), findsOneWidget);
      expect(find.text('아직 통화가 없어요.'), findsNothing);
    });

    testWidgets('통화가 없으면 안내 문구를 보여 준다', (tester) async {
      NulbomApi.client =
          MockClient((request) async => json({'share_agreed': true, 'calls': []}));

      await open(tester, screen);

      expect(find.text('아직 통화가 없어요.'), findsOneWidget);
    });

    testWidgets('서버가 거절하면 그 문장을 보여 준다', (tester) async {
      NulbomApi.client =
          MockClient((request) async => json({'detail': '열쇠가 필요합니다'}, 401));

      await open(tester, screen);

      expect(find.text('열쇠가 필요합니다'), findsOneWidget);
    });

    testWidgets('원문이 있는 통화를 누르면 대화 원문 화면으로 간다', (tester) async {
      NulbomApi.client = MockClient((request) async {
        if (request.url.path == '/v1/calls/7/turns') {
          return json({
            'call_id': 7,
            'turns': [
              {'speaker': 'ai', 'text': '안녕하세요'},
              {'speaker': 'elder', 'text': '네 안녕하세요'},
            ],
          });
        }
        return json({
          'share_agreed': true,
          'calls': [call(7, summary: '점심을 드셨어요.', turns: true)],
        });
      });

      await open(tester, screen);
      await tester.tap(find.text('점심을 드셨어요.'));
      await tester.pumpAndSettle();

      expect(find.text('안녕하세요'), findsOneWidget);
      expect(find.text('네 안녕하세요'), findsOneWidget);
    });
  });

  group('CallTurnsScreen', () {
    const screen = CallTurnsScreen(callId: 7, title: '10월 9일 통화');

    testWidgets('AI와 어르신 말을 보여 주고 자동 인식 안내를 붙인다', (tester) async {
      NulbomApi.client = MockClient((request) async => json({
            'call_id': 7,
            'turns': [
              {'speaker': 'ai', 'text': '식사하셨어요?'},
              {'speaker': 'elder', 'text': '네 먹었어요'},
            ],
          }));

      await open(tester, screen);

      expect(find.text('식사하셨어요?'), findsOneWidget);
      expect(find.text('네 먹었어요'), findsOneWidget);
      expect(find.text('자동 인식이라 실제 말과 다를 수 있어요.'), findsOneWidget);
      expect(find.text('AI'), findsOneWidget);
      expect(find.text('어르신'), findsOneWidget);
    });

    testWidgets('열 수 없으면 서버 문장을 보여 준다', (tester) async {
      NulbomApi.client =
          MockClient((request) async => json({'detail': '없는 통화입니다'}, 404));

      await open(tester, screen);

      expect(find.text('없는 통화입니다'), findsOneWidget);
    });
  });
}
