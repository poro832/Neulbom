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

/// 건강·기분 언급 구역이 읽는 주소의 기본 응답: 어르신이 아직 동의하지 않았다.
const Map<String, dynamic> mentionsBeforeConsent = {
  'share_agreed': false,
  'week_start': '2026-10-04',
  'categories': [],
};

/// 요청한 날이 속한 주(일~토)의 7일을 돌려준다. 하루에 한 통, 평균 점수 40.
http.Client serverWithOneCallPerDay({
  List<String>? weekStarts,
  Map<String, dynamic>? calls,
  Map<String, dynamic>? mentions,
  List<String>? paths,
}) =>
    MockClient((request) async {
      paths?.add(request.url.path);
      if (request.url.path == '/v1/elders/20/calls') {
        return json(calls ?? {'share_agreed': true, 'calls': []});
      }
      if (request.url.path == '/v1/elders/20/mentions') {
        return json(mentions ?? mentionsBeforeConsent);
      }
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
  tearDown(() => NulbomApi.guardianKey = '');

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
      if (request.url.path == '/v1/elders/20/mentions') return json(mentionsBeforeConsent);
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

    expect(find.text('열쇠가 필요합니다'), findsWidgets);
  });

  testWidgets('최근 통화 요약: 가짜 대화 대신 서버의 요약을 보여 준다', (tester) async {
    NulbomApi.client = serverWithOneCallPerDay(calls: {
      'share_agreed': true,
      'calls': [
        {
          'call_id': 7,
          'started_at': '2026-10-09T09:00:00+09:00',
          'duration_s': 95,
          'status': 'completed',
          'summary': '점심을 드셨어요.',
          'has_turns': true,
        },
      ],
    });

    await open(tester);

    expect(find.text('최근 통화 요약'), findsOneWidget);
    expect(find.text('점심을 드셨어요.'), findsOneWidget);
    expect(find.text('전체 통화 보기'), findsOneWidget);
    expect(find.textContaining('날씨가 정말 좋네요'), findsNothing); // 옛 예시 대화
    expect(find.text('시간별 대화 기록'), findsNothing);
    expect(find.text('오늘의 대화 요약'), findsNothing);
  });

  testWidgets('어르신이 동의하기 전에는 최근 통화 요약 자리에 안내만 보인다', (tester) async {
    // 이 테스트는 통화 요약 카드만 본다. 언급 구역도 동의 전이면 같은 안내가 한 번 더 나오므로,
    // 언급 구역은 "동의했지만 이번 주 말씀 없음"으로 둔다(언급 구역의 동의 전 안내는
    // elder_mentions_section_test.dart가 따로 확인한다).
    NulbomApi.client = serverWithOneCallPerDay(
      calls: {'share_agreed': false, 'calls': []},
      mentions: {'share_agreed': true, 'week_start': '2026-10-04', 'categories': []},
    );

    await open(tester);

    expect(find.text('어르신이 동의한 뒤에 볼 수 있어요.'), findsOneWidget);
  });

  testWidgets('전체 통화 보기를 누르면 통화 목록 화면이 열린다', (tester) async {
    NulbomApi.client = serverWithOneCallPerDay();

    await open(tester);
    await tester.ensureVisible(find.text('전체 통화 보기'));
    await tester.tap(find.text('전체 통화 보기'));
    await tester.pumpAndSettle();

    expect(find.text('홍길동님 통화'), findsOneWidget);
  });

  testWidgets('최근 통화 요약 아래에 이번 주 어르신이 말씀하신 것 구역이 있다', (tester) async {
    final paths = <String>[];
    NulbomApi.client = serverWithOneCallPerDay(
      paths: paths,
      mentions: {
        'share_agreed': true,
        'week_start': '2026-10-04',
        'categories': [
          {
            'category': 'body',
            'negative': 1,
            'neutral': 0,
            'positive': 0,
            'items': [
              {'call_id': 7, 'date': '2026-10-08T09:00:00+09:00', 'said': 'bad', 'quote': '허리가 아파요'}
            ],
          },
        ],
      },
    );

    await open(tester);

    expect(paths, contains('/v1/elders/20/mentions'));
    final title = find.text('이번 주 어르신이 말씀하신 것');
    expect(title, findsOneWidget);
    expect(find.text('몸이 아프거나 불편함'), findsOneWidget);
    expect(find.textContaining('진단이 아니에요'), findsOneWidget);
    final y = tester.getTopLeft(title).dy;
    expect(y, greaterThan(tester.getTopLeft(find.text('최근 통화 요약')).dy));
    expect(y, lessThan(tester.getTopLeft(find.text('상태 분석')).dy));
  });
}
