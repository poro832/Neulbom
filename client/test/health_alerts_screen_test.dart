import 'dart:convert';

import 'package:eldercare/screens/health_alerts_screen.dart';
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

Map<String, dynamic> alert(int id, String elder, String type, String severity, String message) => {
      'alert_id': id,
      'elder_id': id,
      'elder_name': elder,
      'type': type,
      'severity': severity,
      'message': message,
      'created_at': DateTime.now().toIso8601String(),
    };

Future<void> open(WidgetTester tester, {String? elderName}) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(
    MaterialApp(home: HealthAlertsScreen(initialTabIndex: 1, elderName: elderName)),
  );
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    NulbomApi.guardianKey = 'nlb_test';
  });
  tearDown(() => NulbomApi.guardianKey = const String.fromEnvironment('GUARDIAN_KEY'));

  testWidgets('건강 경고 탭은 서버의 실제 알림을 종류별로 보여 준다', (tester) async {
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return json({
        'alerts': [
          alert(1, '어르신 12', 'risk_rise', 'critical', '최근 통화에서 평소와 많이 달랐어요.'),
          alert(2, '어르신 13', 'no_answer', 'info', '오늘 안부 전화를 받지 못하셨어요.'),
        ],
      });
    });

    await open(tester);

    expect(seen.url.path, '/v1/guardian/alerts');
    expect(seen.url.queryParameters['limit'], '50');
    expect(find.text('최근 통화에서 평소와 많이 달랐어요.'), findsOneWidget);
    expect(find.text('오늘 안부 전화를 받지 못하셨어요.'), findsOneWidget);
    expect(find.text('평소와 다름'), findsWidgets);
    expect(find.text('미응답'), findsWidgets);
    expect(find.text('우울의심'), findsNothing); // 옛 예시 분류가 아니다
    expect(find.text('정상완료'), findsNothing); // 정상완료는 알림이 아니다
    expect(find.textContaining('우울'), findsNothing);
    expect(find.text('심리상담사 연결'), findsNothing);
  });

  testWidgets('어르신을 눌러 들어왔으면 그 어르신 알림만 보인다', (tester) async {
    NulbomApi.client = MockClient((request) async => json({
          'alerts': [
            alert(1, '어르신 12', 'risk_rise', 'warning', '12번 어르신의 알림'),
            alert(2, '어르신 13', 'risk_rise', 'warning', '13번 어르신의 알림'),
          ],
        }));

    await open(tester, elderName: '어르신 12');

    expect(find.text('12번 어르신의 알림'), findsOneWidget);
    expect(find.text('13번 어르신의 알림'), findsNothing);
  });

  testWidgets('알림이 하나도 없으면 안내 문구를 보여 준다', (tester) async {
    NulbomApi.client = MockClient((request) async => json({'alerts': []}));

    await open(tester);

    expect(find.text('아직 알림이 없어요.'), findsOneWidget);
  });

  testWidgets('서버가 거절하면 그 문장을 보여 준다', (tester) async {
    NulbomApi.client =
        MockClient((request) async => json({'detail': '열쇠가 필요합니다'}, 401));

    await open(tester);

    expect(find.text('열쇠가 필요합니다'), findsOneWidget);
  });
}
