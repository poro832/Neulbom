import 'dart:async';
import 'dart:convert';

import 'package:eldercare/screens/elder_call_time_card.dart';
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

const String notice = '이미 지난 시간으로 바꾸면 내일부터 전화가 걸려요.';
const String justPassed =
    '방금 지난 시간이라 곧바로 전화가 걸릴 수 있어요. 지금보다 나중 시간이나 더 일찍 지난 시간(내일부터 걸려요)을 골라 주세요';

Future<void> pump(
  WidgetTester tester, {
  Future<String> Function(int)? fetch,
  Future<String> Function(int, String)? save,
  Size size = const Size(1200, 4000),
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: ElderCallTimeCard(elderId: 12, fetch: fetch, save: save),
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

Future<String> Function(int) fixed(String value) => (_) async => value;

Finder inSheet(Finder finder) => find.descendant(of: find.byType(BottomSheet), matching: finder);

Finder inCard(Finder finder) =>
    find.descendant(of: find.byType(ElderCallTimeCard), matching: finder);

Future<void> openSheet(WidgetTester tester) async {
  await tester.tap(find.text('시간 바꾸기'));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() => GoogleFonts.config.allowRuntimeFetching = false);

  group('표기', () {
    test('24시간 HH:MM을 오전/오후 12시간으로 바꾼다', () {
      expect(formatCallTime('07:00'), '오전 7:00');
      expect(formatCallTime('09:30'), '오전 9:30');
      expect(formatCallTime('11:30'), '오전 11:30');
      expect(formatCallTime('12:00'), '오후 12:00');
      expect(formatCallTime('12:30'), '오후 12:30');
      expect(formatCallTime('13:30'), '오후 1:30');
      expect(formatCallTime('21:00'), '오후 9:00');
    });

    test('자정 쪽은 오전 12시다(목록에는 없지만 함수는 바꾼다)', () {
      expect(formatCallTime('00:00'), '오전 12:00');
      expect(formatCallTime('00:30'), '오전 12:30');
    });

    test('고를 수 있는 시간은 07:00부터 21:00까지 30분 단위 29개다', () {
      expect(callTimeChoices.length, 29);
      expect(callTimeChoices.first, '07:00');
      expect(callTimeChoices[1], '07:30');
      expect(callTimeChoices.last, '21:00');
      expect(callTimeChoices, contains('12:30'));
      expect(callTimeChoices, isNot(contains('06:30')));
      expect(callTimeChoices, isNot(contains('21:30')));
      expect(callTimeChoices.toSet().length, 29);
    });
  });

  testWidgets('현재 시간을 오전/오후로 보이고 설명과 안내가 늘 함께 보인다', (tester) async {
    final asked = <int>[];
    await pump(tester, fetch: (id) async {
      asked.add(id);
      return '09:00';
    });

    expect(asked, [12]);
    expect(find.text('안부 전화 시간'), findsOneWidget);
    expect(find.text('하루에 한 번, 이 시간에 AI가 어르신께 전화해요.'), findsOneWidget);
    expect(find.text('오전 9:00'), findsOneWidget);
    expect(find.text('시간 바꾸기'), findsOneWidget);
    expect(find.text(notice), findsOneWidget);
  });

  testWidgets('오후 시간은 오후로 보인다', (tester) async {
    await pump(tester, fetch: fixed('13:30'));

    expect(find.text('오후 1:30'), findsOneWidget);
  });

  testWidgets('읽는 동안에는 진행 표시만 있고 바꾸기 버튼이 없다', (tester) async {
    final reply = Completer<String>();
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: ElderCallTimeCard(elderId: 12, fetch: (_) => reply.future)),
    ));

    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(find.text('시간 바꾸기'), findsNothing);
    expect(find.text(notice), findsOneWidget);

    reply.complete('10:30');
    await tester.pumpAndSettle();
    expect(find.text('오전 10:30'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsNothing);
  });

  testWidgets('불러오지 못하면 이유와 다시 시도를 보이고, 다시 시도하면 읽는다', (tester) async {
    var calls = 0;
    await pump(tester, fetch: (_) async {
      calls++;
      if (calls == 1) throw const ApiException(503, '인증을 확인할 수 없습니다');
      return '09:00';
    });

    expect(find.text('불러오지 못했어요'), findsOneWidget);
    expect(find.text('인증을 확인할 수 없습니다'), findsOneWidget);
    expect(find.text('시간 바꾸기'), findsNothing);
    expect(find.text(notice), findsOneWidget);

    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();

    expect(calls, 2);
    expect(find.text('불러오지 못했어요'), findsNothing);
    expect(find.text('오전 9:00'), findsOneWidget);
  });

  testWidgets('네트워크 오류로 못 읽으면 잠시 뒤에 다시 하라고 한다', (tester) async {
    await pump(tester, fetch: (_) async => throw Exception('timeout'));

    expect(find.text('불러오지 못했어요'), findsOneWidget);
    expect(find.text('잠시 뒤에 다시 해 주세요.'), findsOneWidget);
    expect(find.text('다시 시도'), findsOneWidget);
  });

  testWidgets('시간 바꾸기: 07:00~21:00 30분 단위 29개가 나오고 현재 값에 체크가 있다', (tester) async {
    await pump(tester, fetch: fixed('09:00'));

    await openSheet(tester);

    expect(inSheet(find.byType(ListTile)), findsNWidgets(29));
    final tiles = tester.widgetList<ListTile>(inSheet(find.byType(ListTile))).toList();
    expect((tiles.first.title as Text).data, '오전 7:00');
    expect((tiles.last.title as Text).data, '오후 9:00');
    expect([for (final t in tiles) (t.title as Text).data], [for (final c in callTimeChoices) formatCallTime(c)]);
    expect(inSheet(find.byIcon(Icons.check_rounded)), findsOneWidget);
    final checked = find.ancestor(of: find.byIcon(Icons.check_rounded), matching: find.byType(ListTile));
    expect(find.descendant(of: checked, matching: find.text('오전 9:00')), findsOneWidget);
  });

  testWidgets('고르면 PUT 본문이 {"call_time": "09:30"}이고 카드 값이 바뀌며 알림이 뜬다', (tester) async {
    final requests = <http.Request>[];
    NulbomApi.guardianKey = 'nlb_test';
    addTearDown(() => NulbomApi.guardianKey = '');
    NulbomApi.client = MockClient((request) async {
      requests.add(request);
      if (request.method == 'PUT') return json({'call_time': jsonDecode(request.body)['call_time']});
      return json({'call_time': '09:00'});
    });

    await pump(tester); // fetch·save 모두 기본값(NulbomApi)을 쓴다
    await openSheet(tester);
    await tester.tap(inSheet(find.text('오전 9:30')));
    await tester.pumpAndSettle();

    expect([for (final r in requests) '${r.method} ${r.url.path}'],
        ['GET /v1/elders/12/call-time', 'PUT /v1/elders/12/call-time']);
    expect(requests.last.headers['Authorization'], 'Bearer nlb_test');
    expect(jsonDecode(requests.last.body), {'call_time': '09:30'});
    expect(find.byType(BottomSheet), findsNothing);
    expect(inCard(find.text('오전 9:30')), findsOneWidget);
    expect(inCard(find.text('오전 9:00')), findsNothing);
    expect(find.text('안부 전화 시간을 오전 9:30으로 바꿨어요'), findsOneWidget);
  });

  testWidgets('서버가 409로 거절하면 그 문장을 시트 안에 보이고 값은 그대로다', (tester) async {
    NulbomApi.guardianKey = 'nlb_test';
    addTearDown(() => NulbomApi.guardianKey = '');
    NulbomApi.client = MockClient((request) async {
      if (request.method == 'PUT') return json({'detail': justPassed}, 409);
      return json({'call_time': '09:00'});
    });

    await pump(tester);
    await openSheet(tester);
    await tester.tap(inSheet(find.text('오전 8:30')));
    await tester.pumpAndSettle();

    expect(inSheet(find.text(justPassed)), findsOneWidget);
    expect(find.byType(SnackBar), findsNothing);
    expect(inSheet(find.byIcon(Icons.check_rounded)), findsOneWidget); // 체크는 여전히 현재 값
    final checked = find.ancestor(of: find.byIcon(Icons.check_rounded), matching: find.byType(ListTile));
    expect(find.descendant(of: checked, matching: find.text('오전 9:00')), findsOneWidget);

    Navigator.of(tester.element(find.byType(BottomSheet))).pop();
    await tester.pumpAndSettle();
    expect(inCard(find.text('오전 9:00')), findsOneWidget);
    expect(find.text('오전 8:30'), findsNothing);
  });

  testWidgets('저장하지 못하면(네트워크) 연결하지 못했다고 시트 안에 보인다', (tester) async {
    await pump(tester, fetch: fixed('09:00'), save: (_, _) async => throw Exception('timeout'));

    await openSheet(tester);
    await tester.tap(inSheet(find.text('오후 3:00')));
    await tester.pumpAndSettle();

    expect(inSheet(find.text('서버에 연결하지 못했어요. 잠시 뒤에 다시 해 주세요.')), findsOneWidget);
    expect(inCard(find.text('오전 9:00')), findsOneWidget);
  });

  testWidgets('저장하는 동안 여러 번 눌러도 한 번만 저장한다', (tester) async {
    final reply = Completer<String>();
    final saved = <String>[];
    await pump(tester, fetch: fixed('09:00'), save: (id, value) {
      saved.add('$id $value');
      return reply.future;
    });

    await openSheet(tester);
    await tester.tap(inSheet(find.text('오전 9:30')));
    await tester.pump();
    await tester.tap(inSheet(find.text('오전 10:00')));
    await tester.pump();
    await tester.tap(inSheet(find.text('오전 9:30')));
    await tester.pump();
    expect(inSheet(find.byType(LinearProgressIndicator)), findsOneWidget);

    reply.complete('09:30');
    await tester.pumpAndSettle();

    expect(saved, ['12 09:30']);
    expect(inCard(find.text('오전 9:30')), findsOneWidget);
  });

  testWidgets('지금 값을 다시 고르면 저장하지 않고 시트만 닫는다', (tester) async {
    var saves = 0;
    await pump(tester, fetch: fixed('09:00'), save: (_, value) async {
      saves++;
      return value;
    });

    await openSheet(tester);
    await tester.tap(inSheet(find.text('오전 9:00')));
    await tester.pumpAndSettle();

    expect(saves, 0);
    expect(find.byType(BottomSheet), findsNothing);
    expect(find.byType(SnackBar), findsNothing);
  });

  testWidgets('좁은 폰 화면에서도 카드와 시트가 넘치지 않는다', (tester) async {
    await pump(tester, fetch: fixed('12:30'), size: const Size(340, 700));

    expect(find.text('오후 12:30'), findsOneWidget);
    await openSheet(tester);
    expect(tester.takeException(), isNull);
    // 늦은 현재 값도 시트를 열면 보이는 자리로 끌어온다
    expect(tester.getRect(inSheet(find.byIcon(Icons.check_rounded))).bottom, lessThan(700));
    await tester.tap(inSheet(find.text('오후 12:30')));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}
