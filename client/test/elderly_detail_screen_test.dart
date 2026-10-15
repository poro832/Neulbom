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

/// 2026-10-10(토) 정오(한국 날짜). 그 주는 2026-10-04(일) ~ 2026-10-10(토).
DateTime fixedNow() => DateTime(2026, 10, 10, 12);

/// 요청한 날이 속한 주(일~토)의 7일을 날짜별 점수 표에서 만든다. 표에 있는 날은 한 통, 없는 날은 통화 없음.
http.Client serverWithScores(Map<String, double> scores) => MockClient((request) async {
      if (request.url.path == '/v1/elders/20/calls') {
        return json({'share_agreed': true, 'calls': []});
      }
      if (request.url.path == '/v1/elders/20/mentions') return json(mentionsBeforeConsent);
      if (request.url.path != '/v1/elders/20/weekly') return json({'detail': 'x'}, 404);
      final asked = DateTime.parse(request.url.queryParameters['week_start']!);
      final sunday = DateTime(asked.year, asked.month, asked.day - asked.weekday % 7);
      final keys = [
        for (var i = 0; i < 7; i++) dateKey(DateTime(sunday.year, sunday.month, sunday.day + i)),
      ];
      return json({
        'week_start': dateKey(sunday),
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
    final now = kstNow(); // 화면도 한국 날짜로 이번 달을 정한다
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
      expect(find.text('30점부터 주의, 60점부터 경보'), findsOneWidget);

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
      expect(find.text('정상 30점 미만 · 주의 30~59점 · 경보 60점 이상'), findsOneWidget);

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

    testWidgets('하루만 60점 이상이면 주간 상태는 경보이고, 평소와 다른 정도는 평균을 보인다', (tester) async {
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
      expect(find.text('경보'), findsOneWidget);
      expect(find.text('정상'), findsNothing);
      expect(find.text('가장 높았던 날 기준 · 30점부터 주의, 60점부터 경보'), findsOneWidget);
      expect(tester.widget<Text>(find.text('경보')).style?.color, red);
      expect(tester.widget<Text>(find.text('22점')).style?.color, green); // 평균은 평균의 구간 색
      expect(
        find.text('2026년 10월 4일 ~ 2026년 10월 10일에는 홍길동님과 5번 통화했고, '
            '평소와 다른 정도는 평균 22점, 가장 높았던 날은 10월 8일(70점, 경보)이에요.'),
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
      expect(find.text('경보'), findsOneWidget);
      expect(find.text('정상 30점 미만 · 주의 30~59점 · 경보 60점 이상'), findsOneWidget);
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
      (70, '경보', '• 평소와 많이 달랐어요\n• 가능하면 직접 연락해 보세요'),
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
