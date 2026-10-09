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

http.Client server({bool alerts = true, int eldersStatus = 200}) => MockClient((request) async {
      final path = request.url.path;
      if (path == '/v1/guardian/elders') {
        if (eldersStatus != 200) return json({'detail': '열쇠가 필요합니다'}, eldersStatus);
        return json({
          'week_start': '2026-10-04',
          'elders': [
            {
              'elder_id': 12,
              'name': '어르신 12',
              'last_call_at': null,
              'last_status': null,
              'week_calls': 2,
              'week_avg_score': 20.0,
              'week_alerts': 1,
            }
          ],
        });
      }
      if (path == '/v1/elders/12/weekly') {
        return json({
          'week_start': '2026-10-04',
          'days': [
            for (var i = 4; i <= 10; i++)
              {'date': '2026-10-${i.toString().padLeft(2, '0')}', 'calls': i == 5 ? 1 : 0, 'avg_score': i == 5 ? 20.0 : null},
          ],
          'total_calls': 3,
          'avg_score': 20.0,
        });
      }
      if (path == '/v1/guardian/alerts') {
        return json({
          'alerts': alerts
              ? [
                  {
                    'alert_id': 1,
                    'elder_id': 12,
                    'elder_name': '어르신 12',
                    'type': 'risk_rise',
                    'severity': 'warning',
                    'message': '문구',
                    'created_at': '2026-10-08T10:00:00+09:00',
                  }
                ]
              : [],
        });
      }
      return json({'detail': 'x'}, 404);
    });

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
    NulbomApi.guardianKey = 'nlb_test';
  });
  tearDown(() => NulbomApi.guardianKey = const String.fromEnvironment('GUARDIAN_KEY'));

  testWidgets('서버의 어르신과 이번 주 통계와 알림을 보여 준다', (tester) async {
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    NulbomApi.client = server();

    await tester.pumpWidget(const MaterialApp(home: GuardianScreen()));
    await tester.pumpAndSettle();

    expect(find.text('어르신 12'), findsWidgets);
    expect(find.text('3회'), findsOneWidget); // 주간 통계의 합계
    expect(find.text('20점'), findsOneWidget); // 평소와 다른 정도
    expect(find.text('평소와 다른 정도'), findsOneWidget);
    expect(find.textContaining('평소와 다름'), findsWidgets); // 알림 종류
    expect(find.textContaining('김할머니'), findsNothing); // 옛 예시 데이터가 아니다
    expect(find.textContaining('우울'), findsNothing);
  });

  testWidgets('서버가 거절하면 그 문장과 다시 불러오기를 보여 준다', (tester) async {
    NulbomApi.client = server(eldersStatus: 401);

    await tester.pumpWidget(const MaterialApp(home: GuardianScreen()));
    await tester.pumpAndSettle();

    expect(find.text('열쇠가 필요합니다'), findsOneWidget);
    expect(find.text('다시 불러오기'), findsOneWidget);
  });
}
