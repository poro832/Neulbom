import 'dart:async';
import 'dart:convert';

import 'package:eldercare/screens/elderly_detail_screen.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:eldercare/utils/kst.dart';
import 'package:fl_chart/fl_chart.dart';
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

/// 안부 전화 시간 카드(일간 화면)가 읽는 주소와 그 기본 응답.
const String callTimePath = '/v1/elders/20/call-time';
http.Response callTimeReply() => json({'call_time': '18:30'});

/// 그 달(YYYY-MM)의 모든 날짜 키.
List<String> monthKeys(String month) {
  final year = int.parse(month.substring(0, 4));
  final mon = int.parse(month.substring(5, 7));
  final length = DateTime(year, mon + 1, 0).day;
  return [for (var d = 1; d <= length; d++) '$month-${d.toString().padLeft(2, '0')}'];
}

/// 받은 요청을 "경로?쿼리"로 적는다.
String requestLine(http.BaseRequest request) =>
    request.url.hasQuery ? '${request.url.path}?${request.url.query}' : request.url.path;

/// 요청한 날이 속한 주(일~토)의 7일, 또는 요청한 달의 모든 날을 돌려준다. 하루에 한 통, 평균 점수 40.
http.Client serverWithOneCallPerDay({
  List<String>? weekStarts,
  List<String>? months,
  Map<String, dynamic>? calls,
  Map<String, dynamic>? mentions,
  List<String>? paths,
}) =>
    MockClient((request) async {
      paths?.add(request.url.path);
      if (request.url.path == callTimePath) return callTimeReply();
      if (request.url.path == '/v1/elders/20/calls') {
        return json(calls ?? {'share_agreed': true, 'calls': []});
      }
      if (request.url.path == '/v1/elders/20/mentions') {
        return json(mentions ?? mentionsBeforeConsent);
      }
      if (request.url.path == '/v1/elders/20/monthly') {
        final month = request.url.queryParameters['month']!;
        months?.add(month);
        final keys = monthKeys(month);
        return json({
          'month': month,
          'days': [for (final key in keys) {'date': key, 'calls': 1, 'avg_score': 40.0}],
          'total_calls': keys.length,
          'avg_score': 40.0,
        });
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

/// 2026-10-10(토) 정오(한국 날짜). 그 주는 2026-10-04(일) ~ 2026-10-10(토).
DateTime fixedNow() => DateTime(2026, 10, 10, 12);

/// 요청한 날이 속한 주(일~토)의 7일, 또는 요청한 달의 모든 날을 날짜별 점수 표에서 만든다.
/// 표에 있는 날은 한 통, 없는 날은 통화 없음. 기준 통화 수가 null이면 응답에 그 필드를 넣지 않는다(옛 서버).
http.Client serverWithScores(
  Map<String, double> scores, {
  int? baselineCalls,
  int? monthBaselineCalls,
  List<String>? requests,
}) =>
    MockClient((request) async {
      requests?.add(requestLine(request));
      if (request.url.path == callTimePath) return callTimeReply();
      if (request.url.path == '/v1/elders/20/calls') {
        return json({'share_agreed': true, 'calls': []});
      }
      if (request.url.path == '/v1/elders/20/mentions') return json(mentionsBeforeConsent);
      final List<String> keys;
      final Map<String, dynamic> head;
      if (request.url.path == '/v1/elders/20/monthly') {
        final month = request.url.queryParameters['month']!;
        keys = monthKeys(month);
        final baseline = monthBaselineCalls ?? baselineCalls;
        head = {'month': month, 'baseline_calls': ?baseline};
      } else if (request.url.path == '/v1/elders/20/weekly') {
        final asked = DateTime.parse(request.url.queryParameters['week_start']!);
        final sunday = DateTime(asked.year, asked.month, asked.day - asked.weekday % 7);
        keys = [
          for (var i = 0; i < 7; i++) dateKey(DateTime(sunday.year, sunday.month, sunday.day + i)),
        ];
        head = {'week_start': dateKey(sunday), 'baseline_calls': ?baselineCalls};
      } else {
        return json({'detail': 'x'}, 404);
      }
      return json({
        ...head,
        'days': [
          for (final key in keys)
            {'date': key, 'calls': scores.containsKey(key) ? 1 : 0, 'avg_score': scores[key]},
        ],
        'total_calls': keys.where(scores.containsKey).length,
        'avg_score': null,
      });
    });

Future<void> open(
  WidgetTester tester, {
  DateTime Function()? now,
  Size size = const Size(1200, 4000),
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(
    MaterialApp(home: ElderlyDetailScreen(elderlyId: 20, elderlyName: '홍길동', now: now)),
  );
  await tester.pumpAndSettle();
}

BarChartData chartData(WidgetTester tester) => tester.widget<BarChart>(find.byType(BarChart)).data;

Finder inChart(String text) => find.descendant(of: find.byType(BarChart), matching: find.text(text));

const Color green = Color(0xFF4CAF50);
const Color orange = Color(0xFFFFA726);
const Color red = Color(0xFFE56F67);

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    NulbomApi.guardianKey = 'nlb_test';
  });
  tearDown(() => NulbomApi.guardianKey = '');

  testWidgets('좁은 화면에서도 일간·주간·월간 통계 제목과 수치의 상단이 맞는다', (tester) async {
    NulbomApi.client = serverWithOneCallPerDay();
    await open(tester, now: () => DateTime(2026, 10, 8), size: const Size(340, 2400));

    for (final (period, count) in [('일간', '1회'), ('주간', '7회'), ('월간', '31회')]) {
      await tester.tap(find.text(period));
      await tester.pumpAndSettle();
      final titleTop = tester.getTopLeft(find.text('평소와 다른 정도')).dy;
      expect(tester.getTopLeft(find.text('통화 횟수')).dy, closeTo(titleTop, 0.1));
      expect(tester.getTopLeft(find.text('상태')).dy, closeTo(titleTop, 0.1));
      final valueTop = tester.getTopLeft(find.text('40점')).dy;
      expect(tester.getTopLeft(find.text(count)).dy, closeTo(valueTop, 0.1));
      expect(tester.getTopLeft(find.text('주의').first).dy, closeTo(valueTop, 0.1));
      expect(tester.takeException(), isNull);
    }
  });

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

  testWidgets('월간: 이번 달 통계를 월간 주소에서 한 번에 읽는다', (tester) async {
    final weeks = <String>[];
    final months = <String>[];
    NulbomApi.client = serverWithOneCallPerDay(weekStarts: weeks, months: months);
    final now = kstNow(); // 화면도 한국 날짜로 이번 달을 정한다
    final daysInMonth = DateTime(now.year, now.month + 1, 0).day;

    await open(tester);
    final weeksBefore = weeks.length; // 일간이 읽은 주
    await tester.tap(find.text('월간'));
    await tester.pumpAndSettle();

    expect(find.text('$daysInMonth회'), findsOneWidget);
    expect(find.text('40점'), findsOneWidget);
    expect(months, ['${now.year}-${now.month.toString().padLeft(2, '0')}']);
    expect(weeks.length, weeksBefore); // 주간 통계를 여러 번 이어 읽지 않는다
    expect(find.text('48회'), findsNothing); // 옛 고정값이 아니다
  });

  group('월간은 한 번만 부른다', () {
    bool isStats(String r) => r.contains('/weekly') || r.contains('/monthly');

    testWidgets('월간: /monthly?month=2026-10 한 번만 부르고 주간 통계는 부르지 않는다', (tester) async {
      final requests = <String>[];
      NulbomApi.client = serverWithScores({'2026-09-30': 99, '2026-10-01': 15, '2026-10-31': 65},
          requests: requests);

      await open(tester, now: fixedNow);
      requests.clear();
      await tester.tap(find.text('월간'));
      await tester.pumpAndSettle();

      expect(requests.where(isStats).toList(), ['/v1/elders/20/monthly?month=2026-10']);
      expect(find.text('2회'), findsOneWidget); // 9월 30일은 그 달이 아니다
      expect(find.text('40점'), findsOneWidget); // (15 + 65) / 2
    });

    testWidgets('다른 달을 고르면 그 달로 한 번 부른다', (tester) async {
      final requests = <String>[];
      NulbomApi.client = serverWithScores({'2026-09-30': 50}, requests: requests);

      await open(tester, now: fixedNow);
      await tester.tap(find.text('월간'));
      await tester.pumpAndSettle();
      requests.clear();
      await tester.tap(find.text('2026년 10월'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('9월'));
      await tester.pumpAndSettle();

      expect(requests.where(isStats).toList(), ['/v1/elders/20/monthly?month=2026-09']);
      expect(find.text('1회'), findsOneWidget);
      expect(find.text('가장 높았던 날: 9월 30일 · 50점'), findsOneWidget);
    });
  });

  group('평소 기준 안내', () {
    for (final (count, text) in <(int?, String?)>[
      (0, '아직 평소 기준을 만드는 중이에요(0통). 점수는 참고만 해 주세요.'),
      (2, '아직 평소 기준을 만드는 중이에요(2통). 점수는 참고만 해 주세요.'),
      (3, '평소 기준 3/14통을 쌓았어요.'),
      (13, '평소 기준 13/14통을 쌓았어요.'),
      (14, null),
      (20, null),
      (null, null), // 옛 서버: 응답에 필드가 없다
    ]) {
      testWidgets('기준 $count통: ${text ?? '안내 없음'}', (tester) async {
        NulbomApi.client = serverWithScores({'2026-10-10': 20}, baselineCalls: count);

        await open(tester, now: fixedNow);

        if (text == null) {
          expect(find.textContaining('평소 기준'), findsNothing);
        } else {
          expect(find.text(text), findsOneWidget);
          // 통계 카드 바로 아래, 최근 통화 요약 위
          final y = tester.getTopLeft(find.text(text)).dy;
          expect(y, greaterThan(tester.getBottomLeft(find.text('상태')).dy));
          expect(y, lessThan(tester.getTopLeft(find.text('최근 통화 요약')).dy));
        }
      });
    }

    testWidgets('주간은 주간 응답, 월간은 월간 응답의 기준 수로 안내한다', (tester) async {
      NulbomApi.client =
          serverWithScores({'2026-10-08': 20}, baselineCalls: 5, monthBaselineCalls: 1);

      await open(tester, now: fixedNow);
      await tester.tap(find.text('주간'));
      await tester.pumpAndSettle();
      expect(find.text('평소 기준 5/14통을 쌓았어요.'), findsOneWidget);

      await tester.tap(find.text('월간'));
      await tester.pumpAndSettle();
      expect(find.text('아직 평소 기준을 만드는 중이에요(1통). 점수는 참고만 해 주세요.'), findsOneWidget);
      expect(find.textContaining('5/14'), findsNothing);
    });

    testWidgets('통계를 못 읽으면 안내도 보이지 않는다', (tester) async {
      NulbomApi.client = MockClient((request) async => json({'detail': '잠시 뒤에 다시 해 주세요'}, 503));

      await open(tester, now: fixedNow);

      expect(find.textContaining('평소 기준'), findsNothing);
    });
  });

  group('상태는 화면에 보이는 반올림 점수로 정한다', () {
    for (final (score, shown, label, color) in <(double, String, String, Color)>[
      (59.4, '59점', '주의', orange),
      (59.6, '60점', '경고', red),
      (29.4, '29점', '정상', green),
      (29.6, '30점', '주의', orange),
    ]) {
      testWidgets('일간: $score점은 $shown으로 보이고 $label이다', (tester) async {
        NulbomApi.client = serverWithScores({'2026-10-10': score});

        await open(tester, now: fixedNow);

        expect(find.text(shown), findsOneWidget);
        expect(tester.widget<Text>(find.text(shown)).style?.color, color);
        expect(find.text(label), findsNWidgets(2)); // 상태 카드와 상태 분석
        for (final w in find.text(label).evaluate()) {
          expect((w.widget as Text).style?.color, color);
        }
      });
    }

    testWidgets('주간: 59.6점인 날은 카드·막대·툴팁·가장 높았던 날 모두 60점 경고다', (tester) async {
      NulbomApi.client = serverWithScores({'2026-10-05': 29.6, '2026-10-08': 59.6});

      await open(tester, now: fixedNow);
      await tester.tap(find.text('주간'));
      await tester.pumpAndSettle();

      expect(find.text('경고'), findsOneWidget);
      expect(tester.widget<Text>(find.text('경고')).style?.color, red);
      expect(find.text('45점'), findsOneWidget); // 평균 44.6 → 45점, 주의
      expect(tester.widget<Text>(find.text('45점')).style?.color, orange);
      final data = chartData(tester);
      final monday = data.barGroups[1];
      final thursday = data.barGroups[4];
      expect(monday.barRods.single.color, orange); // 29.6 → 30점 → 주의
      expect(thursday.barRods.single.color, red); // 59.6 → 60점 → 경고
      final tooltip = data.barTouchData.touchTooltipData.getTooltipItem;
      expect(tooltip(monday, 1, monday.barRods.single, 0)?.text, '10/5 · 30점');
      expect(tooltip(thursday, 4, thursday.barRods.single, 0)?.text, '10/8 · 60점');
      expect(find.text('가장 높았던 날: 10월 8일 · 60점'), findsOneWidget);
      expect(find.textContaining('(60점, 경고)'), findsOneWidget);
    });

    testWidgets('보이는 점수가 같은 두 날이면 가장 높았던 날은 나중 날이다', (tester) async {
      NulbomApi.client = serverWithScores({'2026-10-05': 60.4, '2026-10-08': 60.0});

      await open(tester, now: fixedNow);
      await tester.tap(find.text('주간'));
      await tester.pumpAndSettle();

      expect(find.text('가장 높았던 날: 10월 8일 · 60점'), findsOneWidget);
    });
  });

  testWidgets('통화가 없는 기간은 기록 없음으로 보여 준다', (tester) async {
    NulbomApi.client = MockClient((request) async {
      if (request.url.path == '/v1/elders/20/mentions') return json(mentionsBeforeConsent);
      if (request.url.path == callTimePath) return callTimeReply();
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
    NulbomApi.client = serverWithOneCallPerDay(calls: {'share_agreed': false, 'calls': []});

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

  testWidgets('최근 통화 요약 아래에 어르신이 말씀하신 것 구역이 있다', (tester) async {
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
    final title = find.text('어르신이 말씀하신 것');
    expect(title, findsOneWidget);
    expect(find.text('이번 주'), findsOneWidget);
    expect(find.text('몸이 아프거나 불편함'), findsOneWidget);
    // 상태 분석에도 진단이 아니라는 안내가 있으니 이 구역의 문장으로 찾는다.
    expect(find.text('어르신이 통화에서 하신 말을 그대로 옮긴 것이에요. 진단이 아니에요.'), findsOneWidget);
    final y = tester.getTopLeft(title).dy;
    expect(y, greaterThan(tester.getTopLeft(find.text('최근 통화 요약')).dy));
    expect(y, lessThan(tester.getTopLeft(find.text('상태 분석')).dy));
  });

  group('날짜별 점수 차트', () {
    testWidgets('주간: 점수가 있는 날 3개가 막대로 나오고, 일간에는 차트가 없다', (tester) async {
      NulbomApi.client = serverWithScores({'2026-10-05': 20, '2026-10-07': 45, '2026-10-08': 72});

      await open(tester, now: fixedNow);
      expect(find.byType(BarChart), findsNothing);
      // 일간의 부제는 그대로다
      expect(find.text('낮을수록 평소와 같아요'), findsOneWidget);
      expect(find.text('30점부터 주의, 60점부터 경고'), findsOneWidget);

      await tester.tap(find.text('주간'));
      await tester.pumpAndSettle();

      expect(find.byType(BarChart), findsOneWidget);
      final data = chartData(tester);
      expect(data.minY, 0);
      expect(data.maxY, 100);
      final rods = [for (final g in data.barGroups) g.barRods.single];
      expect(rods.map((r) => r.toY), [0, 20, 0, 45, 72, 0, 0]);
      // 점수가 없는 날은 막대가 보이지 않는다
      for (final i in [0, 2, 5, 6]) {
        expect(rods[i].color, Colors.transparent);
      }
      expect(rods[1].color, green);
      expect(rods[3].color, orange);
      expect(rods[4].color, red);
      for (final w in ['일', '월', '화', '수', '목', '금', '토']) {
        expect(inChart(w), findsOneWidget);
      }
      expect(find.text('정상 30점 미만 · 주의 30~59점 · 경고 60점 이상'), findsOneWidget);

      await tester.tap(find.text('일간'));
      await tester.pumpAndSettle();
      expect(find.byType(BarChart), findsNothing);
    });

    testWidgets('막대를 누르면 M/d · N점을 보여 주고, 점수 없는 날은 아무것도 띄우지 않는다', (tester) async {
      NulbomApi.client = serverWithScores({'2026-10-05': 20, '2026-10-07': 45, '2026-10-08': 72});

      await open(tester, now: fixedNow);
      await tester.tap(find.text('주간'));
      await tester.pumpAndSettle();

      final data = chartData(tester);
      expect(data.barTouchData.enabled, isTrue);
      final tooltip = data.barTouchData.touchTooltipData.getTooltipItem;
      final thursday = data.barGroups[4];
      expect(tooltip(thursday, 4, thursday.barRods.single, 0)?.text, '10/8 · 72점');
      final sunday = data.barGroups[0];
      expect(tooltip(sunday, 0, sunday.barRods.single, 0), isNull);
    });

    testWidgets('주간: 가장 높았던 날을 카드 아래 한 줄로 보인다', (tester) async {
      NulbomApi.client = serverWithScores({'2026-10-05': 20, '2026-10-07': 45, '2026-10-08': 72});

      await open(tester, now: fixedNow);
      await tester.tap(find.text('주간'));
      await tester.pumpAndSettle();

      final line = find.text('가장 높았던 날: 10월 8일 · 72점');
      expect(line, findsOneWidget);
      expect(tester.getTopLeft(line).dy, greaterThan(tester.getTopLeft(find.text('상태')).dy));
      expect(tester.getTopLeft(line).dy, lessThan(tester.getTopLeft(find.byType(BarChart)).dy));
    });

    testWidgets('점수를 낸 날이 없는 기간에는 가장 높았던 날 줄과 차트를 숨긴다', (tester) async {
      NulbomApi.client = serverWithScores({});

      await open(tester, now: fixedNow);
      await tester.tap(find.text('주간'));
      await tester.pumpAndSettle();

      expect(find.textContaining('가장 높았던 날:'), findsNothing); // 줄
      expect(find.textContaining('가장 높았던 날은'), findsNothing); // 요약 문장
      expect(find.byType(BarChart), findsNothing);
      expect(find.text('기록 없음'), findsOneWidget);
    });

    testWidgets('하루만 60점 이상이면 주간 상태는 경고이고, 평소와 다른 정도는 평균을 보인다', (tester) async {
      NulbomApi.client = serverWithScores({
        '2026-10-04': 10,
        '2026-10-05': 10,
        '2026-10-06': 10,
        '2026-10-07': 10,
        '2026-10-08': 70,
      });

      await open(tester, now: fixedNow);
      await tester.tap(find.text('주간'));
      await tester.pumpAndSettle();

      expect(find.text('22점'), findsOneWidget); // (10*4 + 70) / 5
      expect(find.text('평균 · 낮을수록 평소와 같아요'), findsOneWidget);
      expect(find.text('경고'), findsOneWidget);
      expect(find.text('정상'), findsNothing);
      expect(find.text('가장 높았던 날 기준 · 30점부터 주의, 60점부터 경고'), findsOneWidget);
      expect(tester.widget<Text>(find.text('경고')).style?.color, red);
      expect(tester.widget<Text>(find.text('22점')).style?.color, green); // 평균은 평균의 구간 색
      expect(
        find.text('2026년 10월 4일 ~ 2026년 10월 10일에는 홍길동님과 5번 통화했고, '
            '평소와 다른 정도는 평균 22점, 가장 높았던 날은 10월 8일(70점, 경고)이에요.'),
        findsOneWidget,
      );
    });

    testWidgets('월간: 그 달의 날마다 막대 자리가 있고 1일부터 5일 간격으로 날짜 숫자가 붙는다', (tester) async {
      NulbomApi.client = serverWithScores({'2026-10-01': 15, '2026-10-15': 40, '2026-10-31': 65});

      await open(tester, now: fixedNow);
      await tester.tap(find.text('월간'));
      await tester.pumpAndSettle();

      expect(find.byType(BarChart), findsOneWidget);
      final data = chartData(tester);
      expect(data.barGroups.length, 31);
      final rods = [for (final g in data.barGroups) g.barRods.single];
      expect(rods[0].toY, 15);
      expect(rods[14].toY, 40);
      expect(rods[30].toY, 65);
      expect(rods[1].color, Colors.transparent);
      for (final d in ['1', '6', '11', '16', '21', '26', '31']) {
        expect(inChart(d), findsOneWidget);
      }
      for (final d in ['2', '5', '15']) {
        expect(inChart(d), findsNothing);
      }
      final last = data.barGroups[30];
      expect(
        data.barTouchData.touchTooltipData.getTooltipItem(last, 30, last.barRods.single, 0)?.text,
        '10/31 · 65점',
      );
      expect(find.text('가장 높았던 날: 10월 31일 · 65점'), findsOneWidget);
      expect(find.text('경고'), findsOneWidget);
      expect(find.text('정상 30점 미만 · 주의 30~59점 · 경고 60점 이상'), findsOneWidget);
    });

    testWidgets('좁은 폰 화면에서도 주간·월간 카드와 차트가 넘치지 않는다', (tester) async {
      NulbomApi.client = serverWithScores({'2026-10-01': 15, '2026-10-08': 72, '2026-10-31': 65});

      await open(tester, now: fixedNow, size: const Size(340, 2400));
      for (final period in ['주간', '월간']) {
        await tester.tap(find.text(period));
        await tester.pumpAndSettle();
        expect(find.byType(BarChart), findsOneWidget);
        expect(tester.takeException(), isNull);
      }
    });
  });

  group('상태 분석은 원인을 말하지 않는다', () {
    const notice = '통화에서 나온 신호를 점수로 요약한 것이에요. 진단이 아니에요.';
    for (final (score, label, lines) in <(double?, String, String)>[
      (10, '정상', '• 평소와 비슷했어요\n• 특별히 달라진 점이 없어요'),
      (40, '주의', '• 평소와 다른 신호가 있었어요\n• 안부를 한 번 확인해 보세요'),
      (70, '경고', '• 평소와 많이 달랐어요\n• 가능하면 직접 연락해 보세요'),
      (null, '기록 없음', '• 이 기간에는 점수를 낸 통화가 없어요'),
    ]) {
      testWidgets('$label: 새 문구와 맨 아래 안내가 보이고 옛 문구는 없다', (tester) async {
        NulbomApi.client = serverWithScores(score == null ? {} : {'2026-10-10': score});

        await open(tester, now: fixedNow);

        expect(find.text(lines), findsOneWidget);
        expect(find.text(notice), findsOneWidget);
        expect(
          tester.getTopLeft(find.text(notice)).dy,
          greaterThan(tester.getTopLeft(find.text(lines)).dy),
        );
        expect(find.textContaining('말수가 줄었거나'), findsNothing);
        expect(find.textContaining('말수'), findsNothing);
        expect(find.textContaining('대답'), findsNothing);
      });
    }
  });

  group('안부 전화 시간 카드', () {
    /// 통계·통화·언급은 비어 있다. 부른 요청("메서드 경로")을 남긴다.
    http.Client server({List<String>? requests}) => MockClient((request) async {
          requests?.add('${request.method} ${request.url.path}');
          final path = request.url.path;
          if (path == callTimePath) return callTimeReply();
          if (path == '/v1/elders/20/calls') return json({'share_agreed': true, 'calls': []});
          if (path == '/v1/elders/20/mentions') return json(mentionsBeforeConsent);
          return json({'week_start': '2026-10-04', 'days': [], 'total_calls': 0, 'avg_score': null});
        });

    testWidgets('일간 화면의 상태 분석 아래에 안부 전화 시간 카드가 있고, 어르신 폰 연결 카드는 없다', (tester) async {
      final requests = <String>[];
      NulbomApi.client = server(requests: requests);

      await open(tester, now: fixedNow);

      expect(requests, contains('GET /v1/elders/20/call-time'));
      expect(find.text('안부 전화 시간'), findsOneWidget);
      expect(find.text('오후 6:30'), findsOneWidget);
      expect(tester.getTopLeft(find.text('안부 전화 시간')).dy,
          greaterThan(tester.getTopLeft(find.text('상태 분석')).dy));
      expect(find.text('어르신 폰 연결'), findsNothing);
      expect(find.text('연결 코드 만들기'), findsNothing);

      // 주간·월간 화면에는 없다
      for (final period in ['주간', '월간']) {
        await tester.tap(find.text(period));
        await tester.pumpAndSettle();
        expect(find.text('안부 전화 시간'), findsNothing);
      }
    });
  });

  testWidgets('오늘과 이번 주는 넘겨준 한국 날짜로 정한다', (tester) async {
    final asked = <String>[];
    NulbomApi.client = serverWithOneCallPerDay(weekStarts: asked);

    await open(tester, now: fixedNow);
    expect(find.text('2026-10-10'), findsOneWidget); // 일간의 날짜 칸
    expect(asked.last, '2026-10-10');

    await tester.tap(find.text('주간'));
    await tester.pumpAndSettle();
    expect(find.text('2026년 10월 4일 ~ 2026년 10월 10일'), findsOneWidget);
  });
}
