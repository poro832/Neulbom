import 'dart:async';
import 'dart:convert';

import 'package:eldercare/models/nulbom_models.dart' show ElderSummary;
import 'package:eldercare/screens/elderly_detail_screen.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:eldercare/services/push_navigation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class FakeSource implements PushMessageSource {
  final foreground = StreamController<Map<String, String>>.broadcast();
  final opened = StreamController<Map<String, String>>.broadcast();
  Map<String, String>? initial;

  @override
  Stream<Map<String, String>> get onForeground => foreground.stream;
  @override
  Stream<Map<String, String>> get onOpened => opened.stream;
  @override
  Future<Map<String, String>?> initialMessage() async => initial;
}

http.Response json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

Map<String, dynamic> elder(int id, String name) => {
      'elder_id': id,
      'name': name,
      'last_call_at': null,
      'last_status': null,
      'week_calls': 0,
      'week_avg_score': null,
      'week_alerts': 0,
      'status': 'active',
      'phone': null,
    };

void main() {
  late GlobalKey<NavigatorState> navKey;
  late FakeSource source;
  late bool listFails;
  late int listCalls;
  late PushNavigation nav;

  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    NulbomApi.guardianKey = 'nlb_test';
    navKey = GlobalKey<NavigatorState>();
    source = FakeSource();
    listFails = false;
    listCalls = 0;
    NulbomApi.client = MockClient((request) async {
      if (request.url.path == '/v1/guardian/elders') {
        listCalls++;
        if (listFails) return json({'detail': '서버 오류'}, 500);
        return json({
          'elders': [elder(20, '홍길동'), elder(21, '김영희')]
        });
      }
      // 상세 화면이 부르는 나머지 주소는 실패해도 화면은 떠 있다.
      return json({'detail': '없음'}, 500);
    });
  });

  tearDown(() async {
    await nav.dispose();
    NulbomApi.guardianKey = '';
  });

  Future<void> start(WidgetTester tester, {bool Function()? loggedIn}) async {
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    await tester.pumpWidget(MaterialApp(
      navigatorKey: navKey,
      home: const Scaffold(body: Text('홈')),
    ));
    nav = PushNavigation(
      source: source,
      navigatorKey: navKey,
      isGuardianLoggedIn: loggedIn,
    );
    await nav.start();
  }

  Future<void> send(WidgetTester tester, Map<String, String> m) async {
    source.opened.add(m);
    await tester.pumpAndSettle();
  }

  Finder detail([int? id]) => find.byWidgetPredicate((w) =>
      w is ElderlyDetailScreen && (id == null || w.elderlyId == id));

  testWidgets('알림을 누르면 해당 어르신 상세 화면으로 이동하고 이름이 전달된다', (tester) async {
    await start(tester);
    await send(tester, {'elder_id': '20'});

    expect(detail(20), findsOneWidget);
    final w = tester.widget<ElderlyDetailScreen>(detail());
    expect(w.elderlyName, '홍길동');
  });

  testWidgets('로그인 안 된 폰은 이동하지 않는다', (tester) async {
    NulbomApi.guardianKey = '';
    await start(tester);
    await send(tester, {'elder_id': '20'});

    expect(detail(), findsNothing);
    expect(listCalls, 0);
  });

  for (final bad in <Map<String, String>>[
    {'elder_id': 'x'},
    {'elder_id': '0'},
    {'elder_id': '-3'},
    {'body': '본문만'},
  ]) {
    testWidgets('잘못된 elder_id $bad 는 이동하지 않는다', (tester) async {
      await start(tester);
      await send(tester, bad);

      expect(detail(), findsNothing);
      expect(listCalls, 0);
    });
  }

  testWidgets('목록에 없는 어르신이면 이동하지 않는다', (tester) async {
    await start(tester);
    await send(tester, {'elder_id': '99'});

    expect(detail(), findsNothing);
  });

  testWidgets('목록을 불러오지 못하면 이동하지 않고 예외도 없다', (tester) async {
    listFails = true;
    await start(tester);
    await send(tester, {'elder_id': '20'});

    expect(detail(), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('이미 같은 어르신 화면이면 쌓지 않는다', (tester) async {
    await start(tester);
    await send(tester, {'elder_id': '20'});
    await send(tester, {'elder_id': '20'});

    expect(detail(20), findsOneWidget);
    navKey.currentState!.pop();
    await tester.pumpAndSettle();
    expect(find.text('홈'), findsOneWidget);
  });

  testWidgets('다른 어르신 알림이면 그 화면이 위에 쌓인다', (tester) async {
    await start(tester);
    await send(tester, {'elder_id': '20'});
    await send(tester, {'elder_id': '21'});

    expect(tester.widget<ElderlyDetailScreen>(detail(21)).elderlyName, '김영희');
  });

  testWidgets('앱이 켜져 있을 때 알림은 화면을 가로채지 않고 SnackBar로 보이며, 보기를 누르면 이동한다',
      (tester) async {
    await start(tester);
    source.foreground.add({'elder_id': '20', 'body': '홍길동 어르신 확인이 필요해요'});
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(detail(), findsNothing);
    expect(find.text('홍길동 어르신 확인이 필요해요'), findsOneWidget);
    expect(find.text('보기'), findsOneWidget);

    await tester.tap(find.text('보기'));
    await tester.pumpAndSettle();
    expect(detail(20), findsOneWidget);
  });

  testWidgets('본문이 없으면 기본 문구를 보인다', (tester) async {
    await start(tester);
    source.foreground.add({'elder_id': '20'});
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('새 알림이 있어요'), findsOneWidget);
  });

  testWidgets('로그인 안 된 폰에는 SnackBar도 없다', (tester) async {
    NulbomApi.guardianKey = '';
    await start(tester);
    source.foreground.add({'elder_id': '20', 'body': '본문'});
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.byType(SnackBar), findsNothing);
  });

  testWidgets('앱이 꺼진 상태에서 알림으로 열린 initialMessage도 이동시킨다', (tester) async {
    source.initial = {'elder_id': '21'};
    await start(tester);
    await tester.pumpAndSettle();

    expect(tester.widget<ElderlyDetailScreen>(detail(21)).elderlyName, '김영희');
  });

  testWidgets('목록을 불러오는 동안 다른 보호자가 로그인하면 이동하지 않는다', (tester) async {
    final gate = Completer<List<ElderSummary>>();
    await tester.pumpWidget(MaterialApp(
      navigatorKey: navKey,
      home: const Scaffold(body: Text('홈')),
    ));
    nav = PushNavigation(
      source: source,
      navigatorKey: navKey,
      loadElders: () => gate.future,
    );
    await nav.start();
    source.opened.add({'elder_id': '20'});
    await tester.pump();

    NulbomApi.guardianKey = 'nlb_other';
    gate.complete([ElderSummary.fromJson(elder(20, '홍길동'))]);
    await tester.pumpAndSettle();

    expect(detail(), findsNothing);
  });

  testWidgets('화면이 뜨기를 기다리는 동안 로그아웃하면 이동하지 않는다', (tester) async {
    nav = PushNavigation(source: source, navigatorKey: navKey);
    await nav.start();
    source.opened.add({'elder_id': '20'});
    await tester.pump(const Duration(milliseconds: 250));

    NulbomApi.guardianKey = '';
    await tester.pumpWidget(MaterialApp(
      navigatorKey: navKey,
      home: const Scaffold(body: Text('홈')),
    ));
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();

    expect(detail(), findsNothing);
  });

  testWidgets('dispose된 뒤에는 이동도 SnackBar도 없다', (tester) async {
    final gate = Completer<List<ElderSummary>>();
    await tester.pumpWidget(MaterialApp(
      navigatorKey: navKey,
      home: const Scaffold(body: Text('홈')),
    ));
    nav = PushNavigation(
      source: source,
      navigatorKey: navKey,
      loadElders: () => gate.future,
    );
    await nav.start();
    source.opened.add({'elder_id': '20'});
    await tester.pump();
    unawaited(nav.dispose());
    gate.complete([ElderSummary.fromJson(elder(20, '홍길동'))]);
    await tester.pumpAndSettle();
    expect(detail(), findsNothing);

    source.foreground.add({'elder_id': '20', 'body': '본문'});
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byType(SnackBar), findsNothing);
  });
}
