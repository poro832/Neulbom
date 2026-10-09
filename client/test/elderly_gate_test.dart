import 'dart:convert';

import 'package:eldercare/screens/elderly_gate.dart';
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

  testWidgets('승인 대기인 어르신은 대기 화면을 본다', (tester) async {
    NulbomApi.client =
        MockClient((request) async => json({'status': 'pending', 'name': '홍길동'}));

    await tester.pumpWidget(const MaterialApp(home: ElderlyGate()));
    await tester.pumpAndSettle();

    expect(find.text('보호자 승인을 기다리고 있어요'), findsOneWidget);
    expect(find.text('새로고침'), findsOneWidget);
  });

  testWidgets('새로고침했을 때 승인됐으면 대기 화면이 풀린다', (tester) async {
    var status = 'pending';
    NulbomApi.client =
        MockClient((request) async => json({'status': status, 'name': '홍길동'}));

    await tester.pumpWidget(
      MaterialApp(home: ElderlyGate(homeBuilder: (_) => const Text('어르신 홈'))),
    );
    await tester.pumpAndSettle();
    expect(find.text('보호자 승인을 기다리고 있어요'), findsOneWidget);

    status = 'active';
    await tester.tap(find.text('새로고침'));
    await tester.pumpAndSettle();

    expect(find.text('보호자 승인을 기다리고 있어요'), findsNothing);
    expect(find.text('어르신 홈'), findsOneWidget);
  });

  testWidgets('서버가 거절하면 그 문장과 다시 시도를 보여 준다', (tester) async {
    NulbomApi.client =
        MockClient((request) async => json({'detail': '열쇠가 필요합니다'}, 401));

    await tester.pumpWidget(const MaterialApp(home: ElderlyGate()));
    await tester.pumpAndSettle();

    expect(find.text('열쇠가 필요합니다'), findsOneWidget);
    expect(find.text('다시 시도'), findsOneWidget);
  });
}
