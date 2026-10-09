import 'dart:convert';

import 'package:eldercare/screens/history_screen.dart';
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

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({'elder_key': 'nle_saved'});
  });

  testWidgets('서버의 AI 안부 통화 기록을 보여 준다', (tester) async {
    NulbomApi.client = MockClient((request) async => json({
          'calls': [
            {'call_id': 2, 'started_at': '2026-10-06T09:00:00+09:00', 'duration_s': null, 'status': 'no_answer'},
            {'call_id': 1, 'started_at': '2026-10-05T09:00:00+09:00', 'duration_s': 125, 'status': 'completed'},
          ]
        }));

    await tester.pumpWidget(const MaterialApp(home: HistoryScreen()));
    await tester.pumpAndSettle();

    expect(find.text('늘봄 안부 전화'), findsNWidgets(2));
    expect(find.textContaining('받지 못했어요'), findsOneWidget);
    expect(find.textContaining('통화했어요 · 02:05'), findsOneWidget);
    expect(find.text('아들'), findsNothing); // 옛 예시 데이터가 아니다
  });

  testWidgets('기록이 없으면 안내 문구를 보여 준다', (tester) async {
    NulbomApi.client = MockClient((request) async => json({'calls': []}));

    await tester.pumpWidget(const MaterialApp(home: HistoryScreen()));
    await tester.pumpAndSettle();

    expect(find.text('아직 통화 기록이 없어요.'), findsOneWidget);
  });

  testWidgets('서버가 거절하면 그 문장을 보여 준다', (tester) async {
    NulbomApi.client =
        MockClient((request) async => json({'detail': '열쇠가 필요합니다'}, 401));

    await tester.pumpWidget(const MaterialApp(home: HistoryScreen()));
    await tester.pumpAndSettle();

    expect(find.text('열쇠가 필요합니다'), findsOneWidget);
  });
}
