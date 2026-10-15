import 'dart:convert';

import 'package:eldercare/models/nulbom_models.dart';
import 'package:eldercare/screens/connection_code_section.dart';
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

Future<void> open(WidgetTester tester, {ValueChanged<LinkResult>? onLinked}) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(
    MaterialApp(home: Scaffold(body: ConnectionCodeSection(onLinked: onLinked))),
  );
}

/// 연결하기 → 코드 입력 → 추가. 미리보기 요청까지 간다.
Future<void> enterCode(WidgetTester tester, String code) async {
  await tester.tap(find.byKey(const Key('link-elder-button')));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('link-code-field')), code);
  await tester.tap(find.text('추가'));
  await tester.pumpAndSettle();
}

void main() {
  var kicked = 0;

  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({'guardian_key': 'nlb_test'});
    NulbomApi.guardianKey = 'nlb_test';
    kicked = 0;
    NulbomApi.onGuardianKeyRejected = () => kicked++; // 앱은 여기서 로그인 화면으로 보낸다
  });
  tearDown(() {
    NulbomApi.guardianKey = '';
    NulbomApi.onGuardianKeyRejected = null;
  });

  testWidgets('구 보호자 코드 발급 대신 어르신 연결 코드 입력을 안내한다', (tester) async {
    var called = false;
    NulbomApi.client = MockClient((request) async {
      called = true;
      return json({});
    });

    await open(tester);

    expect(find.text('어르신이 앱에서 가입하고 받은 연결 코드를 입력하세요.'), findsOneWidget);
    expect(find.text('연결하기'), findsOneWidget);
    expect(find.text('코드 발급'), findsNothing);
    expect(called, isFalse); // 열기만 해서는 서버를 부르지 않는다
  });

  testWidgets('코드를 넣으면 이름과 가려진 번호를 보여 주고, 확인해야만 연결한다', (tester) async {
    final calls = <String>[];
    final codes = <String>[];
    LinkResult? linked;
    NulbomApi.client = MockClient((request) async {
      calls.add('${request.method} ${request.url.path}');
      codes.add((jsonDecode(request.body) as Map<String, dynamic>)['code'] as String);
      if (request.url.path == '/v1/guardian/link/preview') {
        return json({'name': '홍길동', 'phone_masked': '010-****-1111'});
      }
      return json({'elder_id': 31, 'name': '홍길동', 'status': 'active'});
    });

    await open(tester, onLinked: (result) => linked = result);
    await enterCode(tester, '04829316');

    expect(calls, ['POST /v1/guardian/link/preview']); // 미리보기는 아무것도 바꾸지 않는다
    expect(find.text('홍길동 어르신(010-****-1111)이 맞나요?'), findsOneWidget);
    expect(find.text('연결하면 이 어르신께 안부 전화가 시작돼요.'), findsOneWidget);
    expect(linked, isNull);

    await tester.tap(find.byKey(const Key('link-confirm')));
    await tester.pumpAndSettle();

    expect(calls, ['POST /v1/guardian/link/preview', 'POST /v1/guardian/link']);
    expect(codes, ['04829316', '04829316']); // 앞자리 0이 살아 있다
    expect(linked?.elderId, 31);
    expect(find.textContaining('이 맞나요?'), findsNothing); // 대화상자가 닫혔다
  });

  testWidgets('확인 화면에서 취소하면 연결하지 않는다', (tester) async {
    final calls = <String>[];
    LinkResult? linked;
    NulbomApi.client = MockClient((request) async {
      calls.add(request.url.path);
      return json({'name': '홍길동', 'phone_masked': '010-****-1111'});
    });

    await open(tester, onLinked: (result) => linked = result);
    await enterCode(tester, '04829316');
    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();

    expect(calls, ['/v1/guardian/link/preview']);
    expect(linked, isNull);
  });

  testWidgets('코드가 틀리면(401) 서버 문장을 보여 주고 로그인 화면으로 쫓아내지 않는다', (tester) async {
    NulbomApi.client = MockClient(
        (request) async => json({'detail': NulbomApi.badLinkCodeMessage}, 401));

    await open(tester);
    await enterCode(tester, '12345678');

    expect(find.text('연결 코드를 확인해 주세요'), findsOneWidget);
    expect(find.byKey(const Key('link-code-field')), findsOneWidget); // 다시 입력할 수 있다
    await tester.pump(); // 혹시 열쇠를 지우러 갔다면 그 일이 끝나길 기다린다
    expect(kicked, 0);
    expect(NulbomApi.guardianKey, 'nlb_test');
    expect(await NulbomApi.loadGuardianKey(), 'nlb_test');
  });

  testWidgets('확인 사이에 코드가 쓰였으면(연결 401) 문장을 보여 주고 로그아웃하지 않는다', (tester) async {
    NulbomApi.client = MockClient((request) async {
      if (request.url.path == '/v1/guardian/link/preview') {
        return json({'name': '홍길동', 'phone_masked': '010-****-1111'});
      }
      return json({'detail': NulbomApi.badLinkCodeMessage}, 401);
    });

    await open(tester);
    await enterCode(tester, '04829316');
    await tester.tap(find.byKey(const Key('link-confirm')));
    await tester.pumpAndSettle();

    expect(find.text('연결 코드를 확인해 주세요'), findsOneWidget);
    expect(kicked, 0);
    expect(NulbomApi.guardianKey, 'nlb_test');
  });

  testWidgets('운영자 확인 전 보호자(403)에게는 서버 문장을 그대로 보여 준다', (tester) async {
    NulbomApi.client =
        MockClient((request) async => json({'detail': '운영자 확인 후 사용할 수 있어요'}, 403));

    await open(tester);
    await enterCode(tester, '04829316');

    expect(find.text('운영자 확인 후 사용할 수 있어요'), findsOneWidget);
    expect(kicked, 0);
  });

  testWidgets('8자리 숫자가 아니면 서버를 부르지 않는다', (tester) async {
    var called = false;
    NulbomApi.client = MockClient((request) async {
      called = true;
      return json({});
    });

    await open(tester);
    await enterCode(tester, '123456'); // 팀원 목업의 6자리

    expect(find.text('8자리 숫자 연결코드를 입력해주세요.'), findsOneWidget);
    expect(called, isFalse);
  });
}
