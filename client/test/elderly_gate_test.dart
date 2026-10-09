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
        MockClient((request) async =>
            json({'status': status, 'name': '홍길동', 'share_agreed': true}));

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

  testWidgets('공유에 동의하지 않은 어르신은 홈 대신 재동의 화면을 본다', (tester) async {
    NulbomApi.client = MockClient((request) async =>
        json({'status': 'active', 'name': '홍길동', 'share_agreed': false}));

    await tester.pumpWidget(
      MaterialApp(home: ElderlyGate(homeBuilder: (_) => const Text('어르신 홈'))),
    );
    await tester.pumpAndSettle();

    expect(find.text('통화 내용 공유에 동의해 주세요'), findsOneWidget);
    expect(find.text('어르신 홈'), findsNothing);
  });

  testWidgets('동의합니다를 누르면 서버에 알리고 홈으로 들어간다', (tester) async {
    var agreed = false;
    final calls = <String>[];
    NulbomApi.client = MockClient((request) async {
      calls.add('${request.method} ${request.url.path}');
      if (request.url.path == '/v1/me/share-consent') {
        agreed = true;
        return json({'share_agreed': true});
      }
      return json({'status': 'active', 'name': '홍길동', 'share_agreed': agreed});
    });

    await tester.pumpWidget(
      MaterialApp(home: ElderlyGate(homeBuilder: (_) => const Text('어르신 홈'))),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('동의합니다'));
    await tester.pumpAndSettle();

    expect(calls, contains('POST /v1/me/share-consent'));
    expect(find.text('어르신 홈'), findsOneWidget);
  });

  testWidgets('동의 호출이 거절되면 그 문장을 보여 주고 홈으로 가지 않는다', (tester) async {
    NulbomApi.client = MockClient((request) async {
      if (request.url.path == '/v1/me/share-consent') {
        return json({'detail': '잠시 뒤에 다시 해 주세요'}, 503);
      }
      return json({'status': 'active', 'name': '홍길동', 'share_agreed': false});
    });

    await tester.pumpWidget(
      MaterialApp(home: ElderlyGate(homeBuilder: (_) => const Text('어르신 홈'))),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('동의합니다'));
    await tester.pumpAndSettle();

    expect(find.text('잠시 뒤에 다시 해 주세요'), findsOneWidget);
    expect(find.text('어르신 홈'), findsNothing);
  });
}
