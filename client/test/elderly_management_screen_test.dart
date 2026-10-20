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
  tearDown(() => NulbomApi.guardianKey = '');

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
    // 건강 상태(정상·주의) 표시는 팀원 화면이 목록에서 내렸다. 연결 상태만 남는다.
    expect(find.textContaining('정상'), findsNothing);
    expect(find.textContaining('주의'), findsNothing);
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

  testWidgets('어르신 추가: 연결 코드만 받고, 확인하고 연결하면 서버 목록을 다시 읽는다', (tester) async {
    var linked = false;
    final calls = <String>[];
    NulbomApi.client = MockClient((request) async {
      final path = request.url.path;
      calls.add('${request.method} $path');
      if (path == '/v1/guardian/link/preview') {
        return json({'name': '박순자', 'phone_masked': '010-****-3333'});
      }
      if (path == '/v1/guardian/link') {
        linked = true;
        return json({'elder_id': 33, 'name': '박순자', 'status': 'active'});
      }
      return json({
        'elders': [
          elder(20, '홍길동', calls: 1),
          if (linked) elder(33, '박순자'),
        ],
      });
    });

    await open(tester);
    expect(find.textContaining('(1명)'), findsOneWidget);

    await tester.tap(find.text('어르신 추가'));
    await tester.pumpAndSettle();
    // 이름은 서버가 알고 나이는 서버에 없다 — 연결 코드 칸 하나만 받는다.
    expect(find.byType(TextField), findsOneWidget);
    expect(find.text('8자리 숫자를 입력해주세요'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('link-code-field')), '55512345');
    await tester.tap(find.text('추가'));
    await tester.pumpAndSettle();
    expect(find.text('박순자 어르신(010-****-3333)이 맞나요?'), findsOneWidget);

    await tester.tap(find.byKey(const Key('link-confirm')));
    await tester.pumpAndSettle();

    expect(calls, [
      'GET /v1/guardian/elders',
      'POST /v1/guardian/link/preview',
      'POST /v1/guardian/link',
      'GET /v1/guardian/elders',
    ]);
    expect(find.text('박순자'), findsOneWidget);
    expect(find.textContaining('(2명)'), findsOneWidget);
    expect(find.text('어르신이 추가되었습니다.'), findsOneWidget);
  });

  testWidgets('어르신 추가: 한도에 걸리면(409) 서버 문장을 보여 주고 목록은 그대로다', (tester) async {
    NulbomApi.client = MockClient((request) async {
      if (request.url.path == '/v1/guardian/link/preview') {
        return json({'name': '박순자', 'phone_masked': '010-****-3333'});
      }
      if (request.url.path == '/v1/guardian/link') {
        return json({'detail': '더 이상 어르신을 연결할 수 없어요'}, 409);
      }
      return json({'elders': [elder(20, '홍길동')]});
    });

    await open(tester);
    await tester.tap(find.text('어르신 추가'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('link-code-field')), '55512345');
    await tester.tap(find.text('추가'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('link-confirm')));
    await tester.pumpAndSettle();

    expect(find.text('더 이상 어르신을 연결할 수 없어요'), findsOneWidget);
    expect(find.textContaining('(1명)'), findsOneWidget);
  });

  testWidgets('삭제는 서버에 없는 기능이라 가짜로 지우지 않는다', (tester) async {
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

  group('어르신 정보 수정', () {
    /// 목록과 번호 읽기·바꾸기·연결 코드 만들기에 답한다. 부른 요청("메서드 경로")을 남긴다.
    http.Client server(List<String> requests, {int changeStatus = 200, String? changeDetail}) =>
        MockClient((request) async {
          requests.add('${request.method} ${request.url.path}');
          final path = request.url.path;
          if (path == '/v1/guardian/elders') {
            return json({
              'elders': [elder(20, '홍길동', calls: 3), elder(21, '김영희')],
            });
          }
          if (path == '/v1/elders/20/phone' && request.method == 'GET') {
            return json({'phone': '010-1111-2222'});
          }
          if (path == '/v1/elders/20/phone' && request.method == 'PUT') {
            if (changeStatus != 200) return json({'detail': changeDetail}, changeStatus);
            return json({'phone': jsonDecode(request.body)['phone']});
          }
          if (path == '/v1/elders/20/pairing-code') {
            return json({'code': '048213', 'expires_at': '2026-10-21T09:00:00+09:00'});
          }
          return json({});
        });

    testWidgets('이름을 눌러도 다른 화면으로 가지 않는다', (tester) async {
      final requests = <String>[];
      NulbomApi.client = server(requests);

      await open(tester);
      await tester.tap(find.text('홍길동'));
      await tester.pumpAndSettle();

      expect(find.text('어르신 관리'), findsOneWidget);
      expect(find.byType(ElderlyManagementScreen), findsOneWidget);
      expect(requests, ['GET /v1/guardian/elders']);
    });

    testWidgets('수정을 누르면 지금 번호가 채워져 열리고, 바꾸면 새 연결 코드를 보여 준다', (tester) async {
      final requests = <String>[];
      NulbomApi.client = server(requests);

      await open(tester);
      await tester.tap(find.byKey(const Key('edit-20')));
      await tester.pumpAndSettle();
      expect(find.text('홍길동 어르신 정보 수정'), findsOneWidget);
      expect(find.widgetWithText(TextField, '010-1111-2222'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('elder-phone')), '010-9999-8888');
      await tester.tap(find.text('저장'));
      await tester.pumpAndSettle();

      expect(find.text('전화번호를 바꿨어요'), findsOneWidget);
      expect(find.text('048213'), findsOneWidget);
      expect(requests, containsAllInOrder(['PUT /v1/elders/20/phone', 'POST /v1/elders/20/pairing-code']));

      await tester.tap(find.text('확인'));
      await tester.pumpAndSettle();
      // 목록을 다시 읽는다
      expect(requests.where((r) => r == 'GET /v1/guardian/elders').length, 2);
    });

    testWidgets('번호를 안 바꾸고 저장하면 서버를 부르지 않고 닫힌다', (tester) async {
      final requests = <String>[];
      NulbomApi.client = server(requests);

      await open(tester);
      await tester.tap(find.byKey(const Key('edit-20')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('저장'));
      await tester.pumpAndSettle();

      expect(find.text('홍길동 어르신 정보 수정'), findsNothing);
      expect(requests, isNot(contains('PUT /v1/elders/20/phone')));
    });

    testWidgets('다른 어르신이 쓰는 번호면 서버 문장을 보여 주고 코드는 만들지 않는다', (tester) async {
      final requests = <String>[];
      NulbomApi.client = server(requests, changeStatus: 409, changeDetail: '이미 등록된 번호예요');

      await open(tester);
      await tester.tap(find.byKey(const Key('edit-20')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('elder-phone')), '010-3333-4444');
      await tester.tap(find.text('저장'));
      await tester.pumpAndSettle();

      expect(find.text('이미 등록된 번호예요'), findsOneWidget);
      expect(find.text('홍길동 어르신 정보 수정'), findsOneWidget);
      expect(requests, isNot(contains('POST /v1/elders/20/pairing-code')));
    });

    testWidgets('전화번호 모양이 틀리면 서버를 부르지 않는다', (tester) async {
      final requests = <String>[];
      NulbomApi.client = server(requests);

      await open(tester);
      await tester.tap(find.byKey(const Key('edit-20')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('elder-phone')), '123');
      await tester.tap(find.text('저장'));
      await tester.pumpAndSettle();

      expect(find.text('전화번호를 확인해 주세요.'), findsOneWidget);
      expect(requests, isNot(contains('PUT /v1/elders/20/phone')));
    });

    testWidgets('취소하면 아무것도 바꾸지 않는다', (tester) async {
      final requests = <String>[];
      NulbomApi.client = server(requests);

      await open(tester);
      await tester.tap(find.byKey(const Key('edit-20')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('취소'));
      await tester.pumpAndSettle();

      expect(find.text('홍길동 어르신 정보 수정'), findsNothing);
      expect(requests, isNot(contains('PUT /v1/elders/20/phone')));
    });
  });
}
