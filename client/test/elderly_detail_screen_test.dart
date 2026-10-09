import 'dart:convert';

import 'package:eldercare/screens/elderly_detail_screen.dart';
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

String dateKey(DateTime d) =>
    '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// 요청한 날이 속한 주(일~토)의 7일을 돌려준다. 하루에 한 통, 평균 점수 40.
http.Client serverWithOneCallPerDay({List<String>? weekStarts}) => MockClient((request) async {
      if (request.url.path != '/v1/elders/20/weekly') return json({'detail': 'x'}, 404);
      final asked = DateTime.parse(request.url.queryParameters['week_start']!);
      weekStarts?.add(request.url.queryParameters['week_start']!);
      final day = DateTime(asked.year, asked.month, asked.day);
      final sunday = day.subtract(Duration(days: day.weekday % 7));
      return json({
        'week_start': dateKey(sunday),
        'days': [
          for (var i = 0; i < 7; i++)
            {'date': dateKey(sunday.add(Duration(days: i))), 'calls': 1, 'avg_score': 40.0},
        ],
        'total_calls': 7,
        'avg_score': 40.0,
      });
    });

Future<void> open(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(
    const MaterialApp(home: ElderlyDetailScreen(elderlyId: 20, elderlyName: '홍길동')),
  );
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    NulbomApi.guardianKey = 'nlb_test';
  });
  tearDown(() => NulbomApi.guardianKey = const String.fromEnvironment('GUARDIAN_KEY'));

  testWidgets('일간: 그날의 실제 통화 수와 평소와 다른 정도를 보여 준다', (tester) async {
    NulbomApi.client = serverWithOneCallPerDay();

    await open(tester);

    expect(find.text('40점'), findsOneWidget);
    expect(find.text('주의'), findsWidgets);
    expect(find.text('1회'), findsOneWidget);
    expect(find.text('2.8/10'), findsNothing); // 옛 고정값이 아니다
    expect(find.textContaining('우울'), findsNothing);
  });

  testWidgets('주간: 한 주의 합계와 평균을 보여 준다', (tester) async {
    final asked = <String>[];
    NulbomApi.client = serverWithOneCallPerDay(weekStarts: asked);

    await open(tester);
    await tester.tap(find.text('주간'));
    await tester.pumpAndSettle();

    expect(find.text('7회'), findsOneWidget);
    expect(find.text('40점'), findsOneWidget);
    expect(find.text('2.8/10'), findsNothing);
    expect(find.textContaining('우울'), findsNothing);
    expect(asked, isNotEmpty);
  });

  testWidgets('월간: 그 달에 걸친 주들을 이어 읽어 그 달의 날만 합친다', (tester) async {
    final asked = <String>[];
    NulbomApi.client = serverWithOneCallPerDay(weekStarts: asked);
    final now = DateTime.now();
    final daysInMonth = DateTime(now.year, now.month + 1, 0).day;

    await open(tester);
    await tester.tap(find.text('월간'));
    await tester.pumpAndSettle();

    expect(find.text('$daysInMonth회'), findsOneWidget); // 이전·다음 달의 날은 빠진다
    expect(find.text('40점'), findsOneWidget);
    expect(asked.length, greaterThanOrEqualTo(4)); // 한 달은 최소 네 주에 걸친다
    expect(find.text('48회'), daysInMonth == 48 ? findsOneWidget : findsNothing); // 옛 고정값이 아니다
  });

  testWidgets('통화가 없는 기간은 기록 없음으로 보여 준다', (tester) async {
    NulbomApi.client = MockClient((request) async {
      final asked = DateTime.parse(request.url.queryParameters['week_start']!);
      final sunday = DateTime(asked.year, asked.month, asked.day)
          .subtract(Duration(days: asked.weekday % 7));
      return json({
        'week_start': dateKey(sunday),
        'days': [
          for (var i = 0; i < 7; i++)
            {'date': dateKey(sunday.add(Duration(days: i))), 'calls': 0, 'avg_score': null},
        ],
        'total_calls': 0,
        'avg_score': null,
      });
    });

    await open(tester);

    expect(find.text('기록 없음'), findsWidgets);
    expect(find.text('0회'), findsOneWidget);
    expect(find.text('-'), findsWidgets);
  });

  testWidgets('서버가 거절하면 그 문장을 보여 준다', (tester) async {
    NulbomApi.client =
        MockClient((request) async => json({'detail': '열쇠가 필요합니다'}, 401));

    await open(tester);

    expect(find.text('열쇠가 필요합니다'), findsOneWidget);
  });
}
