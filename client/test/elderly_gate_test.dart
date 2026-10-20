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
    expect(find.textContaining('저절로 바뀌어요'), findsOneWidget);
    expect(find.text('새로고침'), findsNothing);
  });

  testWidgets('기다리다 승인되면 저절로 "연결되었습니다"가 뜨고, 시작하기로 홈에 들어간다', (tester) async {
    var status = 'pending';
    NulbomApi.client =
        MockClient((request) async =>
            json({'status': status, 'name': '홍길동', 'share_agreed': true}));

    await tester.pumpWidget(
      MaterialApp(
        home: ElderlyGate(
          pollInterval: const Duration(seconds: 1),
          homeBuilder: (_) => const Text('어르신 홈'),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('보호자 승인을 기다리고 있어요'), findsOneWidget);

    status = 'active';
    await tester.pump(const Duration(seconds: 1));
    await tester.pumpAndSettle();

    expect(find.text('보호자 승인을 기다리고 있어요'), findsNothing);
    expect(find.text('연결되었습니다'), findsOneWidget);
    expect(find.text('어르신 홈'), findsNothing);

    await tester.tap(find.text('시작하기'));
    await tester.pumpAndSettle();
    expect(find.text('어르신 홈'), findsOneWidget);
  });

  testWidgets('처음부터 연결된 어르신은 "연결되었습니다" 없이 바로 홈이다', (tester) async {
    NulbomApi.client = MockClient((request) async =>
        json({'status': 'active', 'name': '홍길동', 'share_agreed': true}));

    await tester.pumpWidget(
      MaterialApp(home: ElderlyGate(homeBuilder: (_) => const Text('어르신 홈'))),
    );
    await tester.pumpAndSettle();

    expect(find.text('어르신 홈'), findsOneWidget);
    expect(find.text('연결되었습니다'), findsNothing);
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

  group('먼저 가입한 어르신(연결 대기)', () {
    Future<void> open(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      await tester.pumpWidget(
        MaterialApp(home: ElderlyGate(homeBuilder: (_) => const Text('어르신 홈'))),
      );
      await tester.pumpAndSettle();
    }

    testWidgets('보호자 연결 대기 화면을 보고, 코드를 저절로 새로 받지 않는다', (tester) async {
      final calls = <String>[];
      NulbomApi.client = MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
        return json({'status': 'unlinked', 'name': '홍길동', 'share_agreed': true});
      });

      await open(tester);

      expect(find.text('보호자 연결을 기다리고 있어요'), findsOneWidget);
      expect(find.text('연결 코드 보기'), findsOneWidget);
      expect(find.text('새로고침'), findsNothing);
      expect(find.text('어르신 홈'), findsNothing);
      expect(calls, ['GET /v1/me/status']);
    });

    testWidgets('연결 코드 보기를 누르면 서버에서 8자리 코드를 받아 보여 준다', (tester) async {
      final calls = <String>[];
      NulbomApi.client = MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
        if (request.url.path == '/v1/me/link-code') {
          return json({'code': '00012345', 'expires_at': '2026-10-16T14:30:00+09:00'});
        }
        return json({'status': 'unlinked', 'name': '홍길동', 'share_agreed': true});
      });

      await open(tester);
      await tester.tap(find.text('연결 코드 보기'));
      await tester.pumpAndSettle();

      expect(calls, contains('POST /v1/me/link-code'));
      expect(find.text('00012345'), findsOneWidget);
      expect(find.text('새 코드 받기'), findsOneWidget);
      expect(find.textContaining('이전 코드는 쓸 수 없어요'), findsOneWidget);
    });

    testWidgets('코드를 받지 못하면 서버 문장을 보여 준다', (tester) async {
      NulbomApi.client = MockClient((request) async {
        if (request.url.path == '/v1/me/link-code') {
          return json({'detail': '잠시 뒤에 다시 해 주세요'}, 503);
        }
        return json({'status': 'unlinked', 'name': '홍길동', 'share_agreed': true});
      });

      await open(tester);
      await tester.tap(find.text('연결 코드 보기'));
      await tester.pumpAndSettle();

      expect(find.text('잠시 뒤에 다시 해 주세요'), findsOneWidget);
    });

    testWidgets('보호자가 연결하면 저절로 "연결되었습니다"가 뜨고 시작하기로 홈에 들어간다', (tester) async {
      var status = 'unlinked';
      NulbomApi.client = MockClient((request) async =>
          json({'status': status, 'name': '홍길동', 'share_agreed': true}));

      await tester.pumpWidget(
        MaterialApp(
          home: ElderlyGate(
            pollInterval: const Duration(seconds: 1),
            homeBuilder: (_) => const Text('어르신 홈'),
          ),
        ),
      );
      await tester.pumpAndSettle();
      status = 'active';
      await tester.pump(const Duration(seconds: 1));
      await tester.pumpAndSettle();

      expect(find.text('보호자 연결을 기다리고 있어요'), findsNothing);
      expect(find.text('연결되었습니다'), findsOneWidget);
      await tester.tap(find.text('시작하기'));
      await tester.pumpAndSettle();
      expect(find.text('어르신 홈'), findsOneWidget);
    });
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
