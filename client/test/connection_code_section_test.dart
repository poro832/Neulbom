import 'dart:convert';

import 'package:eldercare/screens/connection_code_section.dart';
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

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    NulbomApi.guardianKey = 'nlb_test';
  });
  tearDown(() => NulbomApi.guardianKey = const String.fromEnvironment('GUARDIAN_KEY'));

  testWidgets('개인 코드를 발급하고 앞자리 0이 있는 코드를 그대로 보여 준다', (tester) async {
    final posts = <String>[];
    NulbomApi.client = MockClient((request) async {
      posts.add('${request.method} ${request.url.path}');
      return json({'code': '00001234'});
    });

    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: ConnectionCodeSection())));
    expect(find.text('코드 발급'), findsOneWidget);

    await tester.tap(find.text('코드 발급'));
    await tester.pumpAndSettle();

    expect(posts, ['POST /v1/guardian/invite']);
    expect(find.text('00001234'), findsOneWidget);
    expect(find.text('새 코드 발급'), findsOneWidget);
  });

  testWidgets('서버가 거절하면 그 문장을 보여 준다', (tester) async {
    NulbomApi.client =
        MockClient((request) async => json({'detail': '열쇠가 필요합니다'}, 401));

    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: ConnectionCodeSection())));
    await tester.tap(find.text('코드 발급'));
    await tester.pumpAndSettle();

    expect(find.text('열쇠가 필요합니다'), findsOneWidget);
  });
}
