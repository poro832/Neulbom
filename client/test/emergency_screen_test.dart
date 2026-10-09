import 'dart:convert';

import 'package:eldercare/screens/emergency_screen.dart';
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

  testWidgets('보호자와 어르신이 추가한 연락처를 서버에서 읽어 보여 주고 가짜 기타 연락처는 없다', (tester) async {
    NulbomApi.client = MockClient((request) async => json({
          'guardians': [
            {'name': '보호자1', 'relation': '보호자', 'phone': '010-0000-0001'}
          ],
          'contacts': [
            {'contact_id': 3, 'name': '이웃 김씨', 'relation': '이웃', 'phone': '010-1234-5678'}
          ],
        }));

    await tester.pumpWidget(const MaterialApp(home: EmergencyScreen()));
    await tester.pumpAndSettle();

    expect(find.text('보호자1'), findsOneWidget);
    expect(find.text('이웃 김씨'), findsOneWidget);
    expect(find.text('은평구청'), findsNothing); // 가짜 번호의 예시였다
    expect(find.text('서울의료원'), findsNothing);
    expect(find.text('김보호 (딸)'), findsNothing);
  });

  testWidgets('서버가 거절하면 그 문장을 보여 준다', (tester) async {
    NulbomApi.client =
        MockClient((request) async => json({'detail': '열쇠가 필요합니다'}, 401));

    await tester.pumpWidget(const MaterialApp(home: EmergencyScreen()));
    await tester.pumpAndSettle();

    expect(find.text('열쇠가 필요합니다'), findsOneWidget);
  });

  testWidgets('연락처 추가는 서버에 저장하고 목록을 다시 읽어 보여 준다', (tester) async {
    final contacts = <Map<String, Object>>[];
    final posts = <Map<String, dynamic>>[];
    NulbomApi.client = MockClient((request) async {
      if (request.method == 'POST') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        posts.add(body);
        contacts.add({
          'contact_id': 9,
          'name': body['name'] as String,
          'relation': body['relation'] as String,
          'phone': body['phone'] as String,
        });
        return json({'contact_id': 9, ...body}, 201);
      }
      return json({
        'guardians': [
          {'name': '보호자1', 'relation': '보호자', 'phone': '010-0000-0001'}
        ],
        'contacts': contacts,
      });
    });

    await tester.pumpWidget(const MaterialApp(home: EmergencyScreen()));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.add));
    await tester.pumpAndSettle();
    final fields = find.byType(TextField);
    await tester.enterText(fields.at(0), '이웃 김씨');
    await tester.enterText(fields.at(1), '이웃');
    await tester.enterText(fields.at(2), '010-1234-5678');
    await tester.tap(find.text('추가'));
    await tester.pumpAndSettle();

    expect(posts, [
      {'name': '이웃 김씨', 'relation': '이웃', 'phone': '010-1234-5678'}
    ]);
    expect(find.text('이웃 김씨'), findsOneWidget);
  });
}
