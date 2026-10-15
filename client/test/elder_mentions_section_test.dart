import 'package:eldercare/models/nulbom_models.dart';
import 'package:eldercare/screens/elder_mentions_section.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

ElderMentions sample({bool agreed = true, bool empty = false}) => ElderMentions.fromJson({
      'share_agreed': agreed,
      'week_start': '2026-10-04',
      'categories': !agreed
          ? []
          : [
              for (final c in ['body', 'sleep', 'meal', 'mood', 'activity'])
                {
                  'category': c,
                  'negative': c == 'body' && !empty ? 2 : 0,
                  'neutral': 0,
                  'positive': c == 'meal' && !empty ? 1 : 0,
                  'items': empty
                      ? []
                      : c == 'body'
                          ? [
                              {'call_id': 1, 'date': '2026-10-08T09:00:00+09:00', 'said': 'bad', 'quote': '허리가 아파요'},
                              {'call_id': 2, 'date': '2026-10-07T09:00:00+09:00', 'said': 'bad', 'quote': '무릎이 시큰거려'},
                            ]
                          : c == 'meal'
                              ? [
                                  {'call_id': 1, 'date': '2026-10-08T09:00:00+09:00', 'said': 'good', 'quote': '밥 맛있게 먹었어'}
                                ]
                              : [],
                },
            ],
    });

Future<void> pump(WidgetTester tester, Future<ElderMentions> Function(int, {String? weekStart}) fetch) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: SingleChildScrollView(
        child: ElderMentionsSection(elderId: 12, fetch: fetch, now: () => DateTime(2026, 10, 8, 12)),
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() => GoogleFonts.config.allowRuntimeFetching = false);

  testWidgets('분류별 개수가 보이고, 펼치면 어르신 말이 따옴표로 나온다', (tester) async {
    await pump(tester, (id, {String? weekStart}) async => sample());

    expect(find.text('어르신이 말씀하신 것'), findsOneWidget);
    expect(find.text('이번 주'), findsOneWidget); // 제목 옆 주 표시
    expect(find.text('몸이 아프거나 불편함'), findsOneWidget);
    expect(find.textContaining('안 좋다 2'), findsOneWidget);
    expect(find.text('잠'), findsNothing); // 말씀이 없는 분류는 보이지 않는다
    expect(find.text('“허리가 아파요”'), findsNothing); // 접혀 있다

    await tester.tap(find.text('몸이 아프거나 불편함'));
    await tester.pumpAndSettle();

    expect(find.text('“허리가 아파요”'), findsOneWidget);
    expect(find.text('“무릎이 시큰거려”'), findsOneWidget);
  });

  testWidgets('진단이 아니라는 안내가 항상 보인다', (tester) async {
    await pump(tester, (id, {String? weekStart}) async => sample());
    expect(find.textContaining('진단이 아니에요'), findsOneWidget);
  });

  testWidgets('말씀이 없으면 빈 상태 문구', (tester) async {
    await pump(tester, (id, {String? weekStart}) async => sample(empty: true));
    expect(find.textContaining('아직 없어요'), findsOneWidget);
  });

  testWidgets('어르신이 동의하기 전에는 구역이 아무것도 보이지 않는다', (tester) async {
    // 동의 전 안내는 바로 위 최근 통화 요약 카드가 이미 한다 — 같은 문장을 두 번 보이지 않는다.
    await pump(tester, (id, {String? weekStart}) async => sample(agreed: false));

    expect(find.text('어르신이 말씀하신 것'), findsNothing);
    expect(find.text('이번 주'), findsNothing);
    expect(find.text('이전 주'), findsNothing);
    expect(find.text('다음 주'), findsNothing);
    expect(find.textContaining('진단이 아니에요'), findsNothing);
    expect(find.text('어르신이 동의한 뒤에 볼 수 있어요.'), findsNothing);
    expect(find.byType(LinearProgressIndicator), findsNothing);
  });

  testWidgets('불러오기에 실패하면 다시 시도할 수 있다', (tester) async {
    var calls = 0;
    await pump(tester, (id, {String? weekStart}) async {
      calls++;
      if (calls == 1) throw const ApiException(503, '잠시 뒤에 다시 해 주세요');
      return sample();
    });
    expect(find.textContaining('불러오지 못했어요'), findsOneWidget);

    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();

    expect(find.text('몸이 아프거나 불편함'), findsOneWidget);
  });

  testWidgets('이전 주로 가면 그 주의 일요일 날짜로 다시 읽고, 이번 주에서는 다음 주 버튼이 없다', (tester) async {
    final asked = <String?>[];
    await pump(tester, (id, {String? weekStart}) async {
      asked.add(weekStart);
      return sample();
    });
    expect(asked, [null]);
    expect(find.text('다음 주'), findsNothing);

    await tester.tap(find.text('이전 주'));
    await tester.pumpAndSettle();

    expect(asked.last, '2026-09-27'); // 2026-10-08(목)이 속한 주의 일요일은 10-04, 한 주 전은 09-27
    expect(find.text('1주 전'), findsOneWidget);
    expect(find.text('이번 주'), findsNothing);
    expect(find.text('어르신이 말씀하신 것'), findsOneWidget); // 지난 주에도 제목에 "이번 주"가 붙지 않는다
    expect(find.text('다음 주'), findsOneWidget);
  });

  testWidgets('지난 주에 말씀이 없으면 "이 주에는"으로 말한다', (tester) async {
    await pump(tester, (id, {String? weekStart}) async => sample(empty: true));

    await tester.tap(find.text('이전 주'));
    await tester.pumpAndSettle();

    expect(find.text('이 주에는 어르신이 말씀하신 내용이 아직 없어요.'), findsOneWidget);
  });

  testWidgets('4주 전까지만 갈 수 있다 — 4주 전에서는 이전 주 버튼이 없다', (tester) async {
    final asked = <String?>[];
    await pump(tester, (id, {String? weekStart}) async {
      asked.add(weekStart);
      return sample();
    });

    for (var i = 0; i < 4; i++) {
      await tester.tap(find.text('이전 주'));
      await tester.pumpAndSettle();
    }

    expect(asked, [null, '2026-09-27', '2026-09-20', '2026-09-13', '2026-09-06']);
    expect(find.text('4주 전'), findsOneWidget);
    expect(find.text('이전 주'), findsNothing);
    expect(find.text('다음 주'), findsOneWidget);
  });

  testWidgets('지난 주에서 다음 주를 눌러 이번 주로 돌아오면 주 날짜 없이 다시 읽는다', (tester) async {
    final asked = <String?>[];
    await pump(tester, (id, {String? weekStart}) async {
      asked.add(weekStart);
      return sample();
    });

    await tester.tap(find.text('이전 주'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('이전 주'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('다음 주'));
    await tester.pumpAndSettle();
    expect(find.text('1주 전'), findsOneWidget);
    await tester.tap(find.text('다음 주'));
    await tester.pumpAndSettle();

    expect(asked, [null, '2026-09-27', '2026-09-20', '2026-09-27', null]);
    expect(asked.last, isNull);
    expect(find.text('이번 주'), findsOneWidget);
    expect(find.text('다음 주'), findsNothing);
    expect(find.text('이전 주'), findsOneWidget);
  });
}
