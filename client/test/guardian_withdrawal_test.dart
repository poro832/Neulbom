import 'dart:convert';

import 'package:eldercare/screens/guardian_screen.dart';
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

Map<String, dynamic> request({int approved = 0, int total = 1, bool byMe = false}) => {
      'elder_id': 12,
      'name': '어르신 12',
      'requested_at': '2026-10-20T10:00:00+09:00',
      'expires_at': '2026-10-27T10:00:00+09:00',
      'approved': approved,
      'total': total,
      'approved_by_me': byMe,
    };

/// 어르신 한 명과 탈퇴 요청 목록을 주는 서버. 목록은 [requests]를 호출 때마다 읽어 테스트가 바꿀 수 있다.
http.Client server(
  List<String> calls, {
  required List<Map<String, dynamic>> Function() requests,
  http.Response Function(String path)? onDecide,
}) =>
    MockClient((req) async {
      final path = req.url.path;
      calls.add('${req.method} $path');
      if (path == '/v1/guardian/elders') {
        return json({
          'week_start': '2026-10-04',
          'elders': [
            {
              'elder_id': 12,
              'name': '어르신 12',
              'last_call_at': null,
              'last_status': null,
              'week_calls': 0,
              'week_avg_score': null,
              'week_alerts': 0,
            }
          ],
        });
      }
      if (path == '/v1/elders/12/weekly') {
        return json({'week_start': '2026-10-04', 'days': [], 'total_calls': 0, 'avg_score': null});
      }
      if (path == '/v1/guardian/alerts') return json({'alerts': []});
      if (path == '/v1/guardian/withdrawals') return json({'withdrawals': requests()});
      if (path.endsWith('/withdrawal/approve') || path.endsWith('/withdrawal/reject')) {
        return (onDecide ?? (_) => json({'status': 'deleted'}))(path);
      }
      return json({'detail': 'x'}, 404);
    });

Future<void> open(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(const MaterialApp(home: GuardianScreen()));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
    NulbomApi.guardianKey = 'nlb_test';
  });
  tearDown(() => NulbomApi.guardianKey = '');

  testWidgets('탈퇴 요청이 없으면 카드가 없다', (tester) async {
    NulbomApi.client = server(<String>[], requests: () => []);

    await open(tester);

    expect(find.byKey(const Key('withdrawal-12')), findsNothing);
    expect(find.textContaining('탈퇴를 요청했어요'), findsNothing);
  });

  testWidgets('어르신이 탈퇴를 요청하면 맨 위에 승인·거절 카드가 보인다', (tester) async {
    NulbomApi.client = server(<String>[], requests: () => [request()]);

    await open(tester);

    expect(find.byKey(const Key('withdrawal-12')), findsOneWidget);
    expect(find.text('어르신 12 어르신이 탈퇴를 요청했어요'), findsOneWidget);
    expect(find.textContaining('1명 중 0명 승인'), findsOneWidget);
    expect(find.byKey(const Key('withdrawal-approve-12')), findsOneWidget);
    expect(find.byKey(const Key('withdrawal-reject-12')), findsOneWidget);
    // 카드는 "관리 중인 어르신"보다 위에 있다
    expect(
      tester.getTopLeft(find.byKey(const Key('withdrawal-12'))).dy,
      lessThan(tester.getTopLeft(find.text('관리 중인 어르신')).dy),
    );
  });

  testWidgets('승인은 되돌릴 수 없다고 한 번 더 묻고, 확인해야 서버를 부른다', (tester) async {
    final calls = <String>[];
    NulbomApi.client = server(calls, requests: () => [request()]);

    await open(tester);
    await tester.tap(find.byKey(const Key('withdrawal-approve-12')));
    await tester.pumpAndSettle();
    expect(find.text('탈퇴를 승인할까요?'), findsOneWidget);
    expect(find.textContaining('되돌릴 수 없어요'), findsOneWidget);
    expect(calls.where((c) => c.contains('/withdrawal/')), isEmpty);

    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();
    expect(calls.where((c) => c.contains('/withdrawal/')), isEmpty);

    await tester.tap(find.byKey(const Key('withdrawal-approve-12')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('withdrawal-confirm')));
    await tester.pumpAndSettle();

    expect(calls, contains('POST /v1/elders/12/withdrawal/approve'));
  });

  testWidgets('모든 보호자가 승인해 어르신이 지워졌다고 하면 안내하고 목록을 다시 읽는다', (tester) async {
    final calls = <String>[];
    var gone = false;
    NulbomApi.client = server(
      calls,
      requests: () => gone ? [] : [request()],
      onDecide: (_) {
        gone = true;
        return json({'status': 'deleted'});
      },
    );

    await open(tester);
    await tester.tap(find.byKey(const Key('withdrawal-approve-12')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('withdrawal-confirm')));
    await tester.pumpAndSettle();

    expect(find.textContaining('정보가 지워졌어요'), findsOneWidget);
    expect(find.byKey(const Key('withdrawal-12')), findsNothing);
  });

  testWidgets('다른 보호자가 남았으면 승인했다고만 알리고 카드는 기다림 상태가 된다', (tester) async {
    var approved = false;
    NulbomApi.client = server(
      <String>[],
      requests: () => [request(approved: approved ? 1 : 0, total: 2, byMe: approved)],
      onDecide: (_) {
        approved = true;
        return json({'status': 'waiting', 'approved': 1, 'total': 2});
      },
    );

    await open(tester);
    await tester.tap(find.byKey(const Key('withdrawal-approve-12')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('withdrawal-confirm')));
    await tester.pumpAndSettle();

    expect(find.textContaining('다른 보호자의 승인을 기다려요'), findsOneWidget);
    expect(find.byKey(const Key('withdrawal-approve-12')), findsNothing); // 이미 승인했다
    expect(find.textContaining('다른 보호자의 승인을 기다리고 있어요'), findsOneWidget);
  });

  testWidgets('거절하면 서버에 알리고 카드가 사라진다', (tester) async {
    final calls = <String>[];
    var rejected = false;
    NulbomApi.client = server(
      calls,
      requests: () => rejected ? [] : [request()],
      onDecide: (_) {
        rejected = true;
        return http.Response('', 204);
      },
    );

    await open(tester);
    await tester.tap(find.byKey(const Key('withdrawal-reject-12')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('withdrawal-confirm')));
    await tester.pumpAndSettle();

    expect(calls, contains('POST /v1/elders/12/withdrawal/reject'));
    expect(find.text('탈퇴를 거절했어요.'), findsOneWidget);
    expect(find.byKey(const Key('withdrawal-12')), findsNothing);
  });

  testWidgets('서버가 거절하면 그 문장을 보이고 카드를 그대로 둔다', (tester) async {
    NulbomApi.client = server(
      <String>[],
      requests: () => [request()],
      onDecide: (_) => json({'detail': '탈퇴 요청이 없어요'}, 404),
    );

    await open(tester);
    await tester.tap(find.byKey(const Key('withdrawal-approve-12')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('withdrawal-confirm')));
    await tester.pumpAndSettle();

    expect(find.text('탈퇴 요청이 없어요'), findsOneWidget);
    expect(find.byKey(const Key('withdrawal-12')), findsOneWidget);
  });

  testWidgets('화면을 열어 둔 채로도 새 요청을 주기적으로 읽어 보여 준다', (tester) async {
    var list = <Map<String, dynamic>>[];
    NulbomApi.client = server(<String>[], requests: () => list);
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    await tester.pumpWidget(const MaterialApp(
      home: GuardianScreen(withdrawalPollInterval: Duration(seconds: 5)),
    ));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('withdrawal-12')), findsNothing);

    list = [request()];
    await tester.pump(const Duration(seconds: 6));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('withdrawal-12')), findsOneWidget);
  });
}
