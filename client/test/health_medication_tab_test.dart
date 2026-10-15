import 'dart:convert';

import 'package:eldercare/screens/guardian_account_screen.dart';
import 'package:eldercare/screens/health_alerts_screen.dart';
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

Map<String, dynamic> elder(int id, String name, {String status = 'active'}) => {
      'elder_id': id,
      'name': name,
      'last_call_at': null,
      'last_status': null,
      'week_calls': 0,
      'week_avg_score': null,
      'week_alerts': 0,
      'status': status,
    };

Map<String, dynamic> call(int id, String startedAt, String? medication) => {
      'call_id': id,
      'started_at': startedAt,
      'duration_s': 60,
      'status': 'completed',
      'summary': null,
      'has_turns': false,
      'medication': medication,
    };

void useServer({
  required List<Map<String, dynamic>> elders,
  Map<int, Map<String, dynamic>> calls = const {},
  int callsStatus = 200,
}) {
  NulbomApi.client = MockClient((request) async {
    final path = request.url.path;
    if (path == '/v1/guardian/elders') return json({'elders': elders});
    if (path == '/v1/guardian/alerts') return json({'alerts': []});
    if (path == '/v1/guardian/me') {
      return json({'name': '김보호', 'email': 'kim@example.com', 'phone': '010-1111-2222'});
    }
    final m = RegExp(r'^/v1/elders/(\d+)/calls$').firstMatch(path);
    if (m != null) {
      if (callsStatus != 200) return json({'detail': '오류'}, callsStatus);
      expect(request.url.queryParameters['limit'], '14');
      return json(calls[int.parse(m.group(1)!)] ?? {'share_agreed': true, 'calls': []});
    }
    return json({'detail': '없음'}, 404);
  });
}

Future<void> open(WidgetTester tester, int tab) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(MaterialApp(home: HealthAlertsScreen(initialTabIndex: tab)));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
    NulbomApi.guardianKey = 'nlb_test';
  });
  tearDown(() => NulbomApi.guardianKey = '');

  group('약물 복용 탭', () {
    testWidgets('서버 값대로 최신순으로 보이고 가짜 이름·진단 문구가 없다', (tester) async {
      useServer(elders: [
        elder(1, '박순자'),
        elder(2, '최영호'),
      ], calls: {
        1: {
          'share_agreed': true,
          'calls': [
            call(11, '2026-10-10T09:00:00', 'taken'),
            call(12, '2026-10-09T09:00:00', null), // 분석 전 - 보이지 않는다
          ],
        },
        2: {
          'share_agreed': true,
          'calls': [
            call(21, '2026-10-12T09:00:00', 'not_taken'),
            call(22, '2026-10-11T09:00:00', 'unknown'),
          ],
        },
      });

      await open(tester, 0);

      expect(find.text('약을 드셨다고 하셨어요'), findsOneWidget);
      expect(find.text('아직 안 드셨다고 하셨어요'), findsOneWidget);
      expect(find.text('약 이야기가 없었어요'), findsOneWidget);
      expect(find.text('박순자'), findsOneWidget);
      expect(find.text('최영호'), findsNWidgets(2));
      // 최신순: 10-12(최영호 안 드심) -> 10-11(최영호 이야기 없음) -> 10-10(박순자 드심)
      final order = ['아직 안 드셨다고 하셨어요', '약 이야기가 없었어요', '약을 드셨다고 하셨어요']
          .map((t) => tester.getTopLeft(find.text(t)).dy)
          .toList();
      expect(order[0] < order[1] && order[1] < order[2], isTrue);
      expect(find.textContaining('김할머니'), findsNothing);
      expect(find.textContaining('이할아버지'), findsNothing);
      expect(find.textContaining('혈압약'), findsNothing);
      expect(find.textContaining('위험'), findsNothing);
    });

    testWidgets('공유에 동의하기 전인 어르신은 안내 문구만 보인다', (tester) async {
      useServer(elders: [elder(1, '박순자', status: 'unconsented')], calls: {
        1: {'share_agreed': false, 'calls': []},
      });

      await open(tester, 0);

      expect(find.text('박순자'), findsOneWidget);
      expect(find.text('통화 내용 공유에 동의하기 전이에요'), findsOneWidget);
    });

    testWidgets('약 이야기가 하나도 없으면 빈 상태 문구를 보여 준다', (tester) async {
      useServer(elders: [elder(1, '박순자')]);

      await open(tester, 0);

      expect(find.text('아직 약 복용에 대한 이야기가 없어요.'), findsOneWidget);
    });

    testWidgets('불러오지 못하면 오류 문구와 다시 시도를 보여 준다', (tester) async {
      useServer(elders: [elder(1, '박순자')], callsStatus: 500);

      await open(tester, 0);

      expect(find.textContaining('불러오지 못했어요'), findsOneWidget);
      expect(find.text('다시 시도'), findsOneWidget);
    });
  });

  group('건강 확인 탭', () {
    testWidgets('가짜 목록 없이 준비 중이라고 알려 준다', (tester) async {
      useServer(elders: [elder(1, '박순자')]);

      await open(tester, 2);

      expect(find.text('준비 중인 기능이에요'), findsOneWidget);
      expect(find.textContaining('김할머니'), findsNothing);
      expect(find.textContaining('정상'), findsNothing);
    });
  });

  group('계정 화면의 관리 중인 어르신', () {
    Future<void> openAccount(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      await tester.pumpWidget(const MaterialApp(home: GuardianAccountScreen()));
      await tester.pumpAndSettle();
    }

    testWidgets('서버의 실제 목록(이름·상태)을 보여 주고 예시 이름은 없다', (tester) async {
      useServer(elders: [
        elder(1, '박순자'),
        elder(2, '최영호', status: 'pending'),
      ]);

      await openAccount(tester);

      expect(find.text('박순자'), findsOneWidget);
      expect(find.text('연결됨'), findsOneWidget);
      expect(find.text('최영호'), findsOneWidget);
      expect(find.text('승인 대기'), findsOneWidget);
      expect(find.text('김할머니'), findsNothing);
      expect(find.text('이할아버지'), findsNothing);
    });

    testWidgets('비어 있으면 연결된 어르신이 없다고 알려 준다', (tester) async {
      useServer(elders: []);

      await openAccount(tester);

      expect(find.text('연결된 어르신이 없어요'), findsOneWidget);
    });

    testWidgets('불러오기에 실패하면 오류 문구를 보여 준다', (tester) async {
      NulbomApi.client = MockClient((request) async {
        if (request.url.path == '/v1/guardian/elders') return json({'detail': '오류'}, 500);
        return json({'name': '김보호', 'email': 'kim@example.com', 'phone': '010-1111-2222'});
      });

      await openAccount(tester);

      expect(find.text('어르신 목록을 불러오지 못했어요.'), findsOneWidget);
      expect(find.text('김할머니'), findsNothing);
    });
  });
}
