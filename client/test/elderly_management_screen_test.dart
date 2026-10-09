import 'dart:convert';

import 'package:eldercare/screens/elderly_management_screen.dart';
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

Map<String, dynamic> elder(int id, String name,
        {String status = 'active', int calls = 0, double? score, String? phone}) =>
    {
      'elder_id': id,
      'name': name,
      'last_call_at': null,
      'last_status': null,
      'week_calls': calls,
      'week_avg_score': score,
      'week_alerts': 0,
      'status': status,
      'phone': phone,
    };

Future<void> open(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(const MaterialApp(home: ElderlyManagementScreen()));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    NulbomApi.guardianKey = 'nlb_test';
  });
  tearDown(() => NulbomApi.guardianKey = const String.fromEnvironment('GUARDIAN_KEY'));

  testWidgets('서버의 실제 어르신 목록을 보여 준다', (tester) async {
    NulbomApi.client = MockClient((request) async {
      expect(request.url.path, '/v1/guardian/elders');
      return json({
        'elders': [
          elder(20, '홍길동', calls: 3, score: 12.0),
          elder(21, '김영희', calls: 2, score: 45.0),
          elder(22, '대기중', status: 'pending', phone: '010-1111-2222'),
        ],
      });
    });

    await open(tester);

    expect(find.text('홍길동'), findsOneWidget);
    expect(find.text('김영희'), findsOneWidget);
    expect(find.text('대기중'), findsOneWidget);
    expect(find.textContaining('이번 주 통화 3회'), findsOneWidget);
    expect(find.textContaining('정상'), findsWidgets);
    expect(find.textContaining('주의'), findsWidgets);
    expect(find.textContaining('승인 대기'), findsWidgets);
    expect(find.text('김할머니'), findsNothing); // 옛 예시 자료가 아니다
    expect(find.text('이할아버지'), findsNothing);
    expect(find.textContaining('(3명)'), findsOneWidget);
  });

  testWidgets('어르신이 없으면 안내 문구를 보여 준다', (tester) async {
    NulbomApi.client = MockClient((request) async => json({'elders': []}));

    await open(tester);

    expect(find.text('관리 중인 어르신이 없습니다.'), findsOneWidget);
  });

  testWidgets('삭제와 추가는 서버에 없는 기능이라 가짜로 지우지 않는다', (tester) async {
    NulbomApi.client = MockClient(
        (request) async => json({'elders': [elder(20, '홍길동', calls: 1, score: 10.0)]}));

    await open(tester);
    await tester.tap(find.text('삭제'));
    await tester.pumpAndSettle();

    expect(find.text('홍길동'), findsOneWidget);
    expect(find.textContaining('추후 제공됩니다'), findsOneWidget);
  });

  testWidgets('서버가 거절하면 그 문장을 보여 준다', (tester) async {
    NulbomApi.client =
        MockClient((request) async => json({'detail': '열쇠가 필요합니다'}, 401));

    await open(tester);

    expect(find.text('열쇠가 필요합니다'), findsOneWidget);
  });
}
