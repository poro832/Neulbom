import 'dart:async';
import 'dart:convert';

import 'package:eldercare/screens/elderly_home_page.dart';
import 'package:eldercare/screens/elderly_login_screen.dart';
import 'package:eldercare/screens/guardian_account_screen.dart';
import 'package:eldercare/screens/role_selection_screen.dart';
import 'package:eldercare/services/auth_service.dart';
import 'package:eldercare/services/email_proof.dart';
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

http.Response noContent() => http.Response('', 204);

const me = {'name': '김보호', 'email': 'kim@example.com', 'phone': '010-1111-2222'};

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
    NulbomApi.guardianKey = '';
  });
  tearDown(() {
    NulbomApi.guardianKey = '';
    AuthService.firebaseAccountDeleter = deleteFirebaseAccountQuietly;
  });

  group('NulbomApi', () {
    test('보호자 계정 삭제: DELETE 본문에 비밀번호를 싣고 보호자 열쇠로 보낸다', () async {
      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return noContent();
      });

      await NulbomApi.deleteGuardianAccount(password: 'correct-horse-1', key: 'nlb_test');

      expect(seen.method, 'DELETE');
      expect(seen.url.path, '/v1/guardian/me');
      expect(seen.headers['Authorization'], 'Bearer nlb_test');
      expect(jsonDecode(seen.body), {'password': 'correct-horse-1'});
    });

    test('비밀번호가 틀려 401이 와도 보호자 열쇠를 지우지 않는다', () async {
      NulbomApi.guardianKey = 'nlb_test';
      var rejected = 0;
      NulbomApi.onGuardianKeyRejected = () => rejected++;
      addTearDown(() => NulbomApi.onGuardianKeyRejected = null);
      NulbomApi.client = MockClient(
          (request) async => json({'detail': '비밀번호를 확인해 주세요'}, 401));

      await expectLater(
        NulbomApi.deleteGuardianAccount(password: 'wrong-one', key: 'nlb_test'),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', '비밀번호를 확인해 주세요')),
      );
      await Future<void>.delayed(Duration.zero);

      expect(rejected, 0);
      expect(NulbomApi.guardianKey, 'nlb_test');
    });

    test('열쇠 자체가 거절되면(다른 401) 지금처럼 로그아웃 처리한다', () async {
      NulbomApi.guardianKey = 'nlb_test';
      var rejected = 0;
      NulbomApi.onGuardianKeyRejected = () => rejected++;
      addTearDown(() => NulbomApi.onGuardianKeyRejected = null);
      NulbomApi.client = MockClient(
          (request) async => json({'detail': '열쇠가 필요합니다'}, 401));

      await expectLater(
        NulbomApi.deleteGuardianAccount(password: 'x', key: 'nlb_test'),
        throwsA(isA<ApiException>()),
      );

      expect(rejected, 1);
    });

    test('어르신 탈퇴 요청: 어르신 열쇠로 POST /v1/me/withdrawal에 확인 값을 싣는다', () async {
      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return json({
          'status': 'waiting',
          'requested_at': '2026-10-20T10:00:00+09:00',
          'expires_at': '2026-10-27T10:00:00+09:00',
          'approved': 0,
          'total': 2,
        }, 202);
      });

      final result = await NulbomApi.requestWithdrawal(key: 'nle_test');

      expect(seen.method, 'POST');
      expect(seen.url.path, '/v1/me/withdrawal');
      expect(seen.headers['Authorization'], 'Bearer nle_test');
      expect(jsonDecode(seen.body), {'confirm': true});
      expect(result.waiting, isTrue);
      expect(result.total, 2);
      expect(result.expiresAt, isNotNull);
    });

    test('내 탈퇴 요청 상태와 취소', () async {
      final calls = <String>[];
      NulbomApi.client = MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
        if (request.method == 'DELETE') return noContent();
        return json({'status': 'rejected', 'approved': 0, 'total': 1});
      });

      final status = await NulbomApi.myWithdrawal(key: 'nle_test');
      await NulbomApi.cancelWithdrawal(key: 'nle_test');

      expect(status.rejected, isTrue);
      expect(calls, ['GET /v1/me/withdrawal', 'DELETE /v1/me/withdrawal']);
    });

    test('보호자: 탈퇴 요청 목록·승인·거절', () async {
      final calls = <String>[];
      final auth = <String?>[];
      NulbomApi.client = MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
        auth.add(request.headers['Authorization']);
        if (request.url.path == '/v1/guardian/withdrawals') {
          return json({
            'withdrawals': [
              {
                'elder_id': 12,
                'request_id': 41,
                'name': '홍길동',
                'requested_at': '2026-10-20T10:00:00+09:00',
                'expires_at': '2026-10-27T10:00:00+09:00',
                'approved': 1,
                'total': 2,
                'approved_by_me': false,
              }
            ]
          });
        }
        if (request.url.path.endsWith('/reject')) return noContent();
        return json({'status': 'deleted'});
      });

      final list = await NulbomApi.guardianWithdrawals(key: 'nlb_test');
      final approved = await NulbomApi.approveWithdrawal(12, 41, key: 'nlb_test');
      await NulbomApi.rejectWithdrawal(12, 41, key: 'nlb_test');

      expect(list.single.name, '홍길동');
      expect(list.single.requestId, 41);
      expect(list.single.approved, 1);
      expect(list.single.approvedByMe, isFalse);
      expect(approved.deleted, isTrue);
      expect(calls, [
        'GET /v1/guardian/withdrawals',
        'POST /v1/elders/12/withdrawal/approve',
        'POST /v1/elders/12/withdrawal/reject',
      ]);
      expect(auth.toSet(), {'Bearer nlb_test'});
    });
  });

  group('AuthService', () {
    test('보호자 탈퇴가 성공하면 Firebase 삭제를 시도하고 폰의 열쇠와 로그인 정보를 지운다', () async {
      SharedPreferences.setMockInitialValues({
        'user_type': 'guardian',
        'email': 'kim@example.com',
        'is_logged_in': true,
        'guardian_key': 'nlb_test',
      });
      NulbomApi.guardianKey = 'nlb_test';
      NulbomApi.client = MockClient((request) async => noContent());
      String? deletedPassword;
      String? deletedEmail;
      AuthService.firebaseAccountDeleter = ({String? knownPassword, String? email}) async {
        deletedPassword = knownPassword;
        deletedEmail = email;
      };

      await AuthService.deleteGuardianAccount(password: 'correct-horse-1');

      expect(deletedPassword, 'correct-horse-1');
      expect(deletedEmail, 'kim@example.com');
      expect(NulbomApi.guardianKey, '');
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('guardian_key'), isNull);
      expect(prefs.getBool('is_logged_in'), isNull);
      expect(prefs.getString('email'), isNull);
    });

    test('서버가 거절하면 아무것도 지우지 않고 Firebase도 건드리지 않는다', () async {
      SharedPreferences.setMockInitialValues({
        'user_type': 'guardian',
        'email': 'kim@example.com',
        'is_logged_in': true,
        'guardian_key': 'nlb_test',
      });
      NulbomApi.guardianKey = 'nlb_test';
      NulbomApi.client = MockClient(
          (request) async => json({'detail': '비밀번호를 확인해 주세요'}, 401));
      var touchedFirebase = false;
      AuthService.firebaseAccountDeleter = ({String? knownPassword, String? email}) async {
        touchedFirebase = true;
      };

      await expectLater(
        AuthService.deleteGuardianAccount(password: 'wrong'),
        throwsA(isA<ApiException>()),
      );

      expect(touchedFirebase, isFalse);
      expect(NulbomApi.guardianKey, 'nlb_test');
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getBool('is_logged_in'), isTrue);
    });

    test('Firebase 삭제가 터져도 서버 삭제는 끝났으니 폰은 로그아웃 상태가 된다', () async {
      SharedPreferences.setMockInitialValues({
        'user_type': 'guardian',
        'email': 'kim@example.com',
        'is_logged_in': true,
        'guardian_key': 'nlb_test',
      });
      NulbomApi.guardianKey = 'nlb_test';
      NulbomApi.client = MockClient((request) async => noContent());
      AuthService.firebaseAccountDeleter = ({String? knownPassword, String? email}) async {
        throw StateError('firebase down');
      };

      await AuthService.deleteGuardianAccount(password: 'correct-horse-1');

      expect(NulbomApi.guardianKey, '');
    });

    test('어르신 탈퇴 요청이 바로 탈퇴됐으면(보호자 없음) 폰의 어르신 열쇠와 정보를 지운다', () async {
      SharedPreferences.setMockInitialValues({
        'user_type': 'elderly',
        'is_logged_in': true,
        'elder_key': 'nle_test',
      });
      NulbomApi.client = MockClient((request) async => json({'status': 'deleted'}));

      final result = await AuthService.requestElderWithdrawal();

      expect(result.deleted, isTrue);
      expect(await NulbomApi.elderKey(), isNull);
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getBool('is_logged_in'), isNull);
    });

    test('보호자 승인을 기다리는 동안에는 열쇠와 로그인 정보를 그대로 둔다', () async {
      SharedPreferences.setMockInitialValues({
        'user_type': 'elderly',
        'is_logged_in': true,
        'elder_key': 'nle_test',
      });
      NulbomApi.client = MockClient((request) async =>
          json({'status': 'waiting', 'approved': 0, 'total': 1}, 202));

      final result = await AuthService.requestElderWithdrawal();

      expect(result.waiting, isTrue);
      expect(await NulbomApi.elderKey(), 'nle_test');
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getBool('is_logged_in'), isTrue);
    });

    test('어르신 탈퇴 요청을 서버가 거절하면 열쇠를 그대로 둔다', () async {
      SharedPreferences.setMockInitialValues({'user_type': 'elderly', 'elder_key': 'nle_test'});
      NulbomApi.client = MockClient(
          (request) async => json({'detail': '잠시 뒤에 다시 해 주세요'}, 503));

      await expectLater(AuthService.requestElderWithdrawal(), throwsA(isA<ApiException>()));

      expect(await NulbomApi.elderKey(), 'nle_test');
    });
  });

  group('보호자 계정 화면', () {
    Future<void> openScreen(WidgetTester tester, http.Client client) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      NulbomApi.guardianKey = 'nlb_test';
      NulbomApi.client = client;
      await tester.pumpWidget(const MaterialApp(home: GuardianAccountScreen()));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('delete-account')));
      await tester.tap(find.byKey(const Key('delete-account')));
      await tester.pumpAndSettle();
    }

    testWidgets('계정 삭제: 안내를 읽고 비밀번호를 넣어 삭제하면 처음 화면으로 돌아간다', (tester) async {
      late http.Request deleted;
      AuthService.firebaseAccountDeleter = ({String? knownPassword, String? email}) async {};
      await openScreen(tester, MockClient((request) async {
        if (request.method == 'DELETE') {
          deleted = request;
          return noContent();
        }
        return json(me);
      }));

      expect(find.textContaining('되돌릴 수 없어요'), findsOneWidget);
      expect(find.textContaining('어르신 계정은 그대로 남아요'), findsOneWidget);
      await tester.enterText(find.byKey(const Key('delete-password')), 'correct-horse-1');
      await tester.tap(find.text('삭제'));
      await tester.pumpAndSettle();

      expect(jsonDecode(deleted.body), {'password': 'correct-horse-1'});
      expect(find.byType(RoleSelectionScreen), findsOneWidget);
      expect(find.text('계정을 삭제했어요.'), findsOneWidget);
      expect(NulbomApi.guardianKey, '');
    });

    testWidgets('비밀번호가 틀리면 대화상자에 서버 문장을 보이고 로그인은 그대로다', (tester) async {
      await openScreen(tester, MockClient((request) async {
        if (request.method == 'DELETE') {
          return json({'detail': '비밀번호를 확인해 주세요'}, 401);
        }
        return json(me);
      }));

      await tester.enterText(find.byKey(const Key('delete-password')), 'wrong-pass');
      await tester.tap(find.text('삭제'));
      await tester.pumpAndSettle();

      expect(find.text('비밀번호를 확인해 주세요'), findsOneWidget);
      expect(find.byType(RoleSelectionScreen), findsNothing);
      expect(NulbomApi.guardianKey, 'nlb_test');
    });

    testWidgets('비밀번호를 비워 두면 서버를 부르지 않는다', (tester) async {
      var deleteCalls = 0;
      await openScreen(tester, MockClient((request) async {
        if (request.method == 'DELETE') deleteCalls++;
        return json(me);
      }));

      await tester.tap(find.text('삭제'));
      await tester.pumpAndSettle();

      expect(find.text('비밀번호를 입력해 주세요.'), findsOneWidget);
      expect(deleteCalls, 0);
    });

    testWidgets('삭제 요청이 가는 동안 뒤로가기를 눌러도 대화상자가 닫히지 않고, 끝나면 처음 화면으로 간다', (tester) async {
      AuthService.firebaseAccountDeleter = ({String? knownPassword, String? email}) async {};
      final gate = Completer<void>();
      await openScreen(tester, MockClient((request) async {
        if (request.method == 'DELETE') {
          await gate.future; // 서버 응답이 아직 안 왔다
          return noContent();
        }
        return json(me);
      }));

      await tester.enterText(find.byKey(const Key('delete-password')), 'correct-horse-1');
      await tester.tap(find.text('삭제'));
      await tester.pump();
      await tester.binding.handlePopRoute(); // 안드로이드 뒤로가기
      await tester.pump();

      expect(find.byKey(const Key('delete-password')), findsOneWidget); // 아직 열려 있다

      gate.complete();
      await tester.pumpAndSettle();

      expect(find.byType(RoleSelectionScreen), findsOneWidget);
      expect(NulbomApi.guardianKey, '');
    });

    testWidgets('취소하면 아무 일도 일어나지 않는다', (tester) async {
      var deleteCalls = 0;
      await openScreen(tester, MockClient((request) async {
        if (request.method == 'DELETE') deleteCalls++;
        return json(me);
      }));

      await tester.tap(find.text('취소'));
      await tester.pumpAndSettle();

      expect(deleteCalls, 0);
      expect(find.byType(GuardianAccountScreen), findsOneWidget);
    });
  });

  group('어르신 홈 메뉴', () {
    const waitingBody = {
      'status': 'waiting',
      'requested_at': '2026-10-20T10:00:00+09:00',
      'expires_at': '2026-10-27T10:00:00+09:00',
      'approved': 0,
      'total': 1,
    };

    /// 탈퇴 요청 주소들에 테스트가 정한 답을 준다. 탈퇴하기 메뉴를 눌러 첫 확인창까지 연다.
    Future<List<String>> openDeleteFlow(
      WidgetTester tester, {
      http.Response Function()? onRequest,
      http.Response Function()? onStatus,
      http.Response Function()? onCancel,
      bool openConfirm = true,
    }) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      SharedPreferences.setMockInitialValues({
        'elder_key': 'nle_saved',
        'ai_friend_name': '봄이',
      });
      final calls = <String>[];
      NulbomApi.client = MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
        if (request.url.path == '/v1/me/withdrawal') {
          if (request.method == 'POST') return (onRequest ?? () => json(waitingBody, 202))();
          if (request.method == 'GET') return (onStatus ?? () => json({'status': 'none'}))();
          return (onCancel ?? noContent)();
        }
        if (request.url.path == '/v1/me/calls') return json({'calls': []});
        if (request.url.path == '/v1/me/contacts') return json({'guardians': [], 'contacts': []});
        return json({'detail': 'x'}, 404);
      });
      await tester.pumpWidget(const MaterialApp(home: ElderlyHomePage()));
      await tester.pumpAndSettle();
      if (!openConfirm) return calls;
      await tester.tap(find.byIcon(Icons.more_horiz_rounded));
      await tester.pumpAndSettle();
      await tester.tap(find.text('탈퇴하기'));
      await tester.pumpAndSettle();
      return calls;
    }

    bool asked(List<String> calls) => calls.contains('POST /v1/me/withdrawal');

    testWidgets('탈퇴하기: 두 번 확인해야 서버에 요청하고, 보호자가 있으면 승인을 기다린다', (tester) async {
      final calls = await openDeleteFlow(tester);

      expect(find.textContaining('보호자의 승인이 필요해요'), findsOneWidget);
      expect(asked(calls), isFalse);
      await tester.tap(find.text('계속'));
      await tester.pumpAndSettle();
      expect(find.text('정말 탈퇴를 요청할까요?'), findsOneWidget);
      expect(asked(calls), isFalse);
      await tester.tap(find.text('요청하기'));
      await tester.pumpAndSettle();

      expect(asked(calls), isTrue);
      expect(find.text('보호자에게 알렸어요'), findsOneWidget);
      await tester.tap(find.text('확인'));
      await tester.pumpAndSettle();
      // 아직 탈퇴되지 않았다: 홈에 남고 열쇠도 그대로이며 승인을 기다린다는 배너가 뜬다
      expect(find.byType(ElderlyHomePage), findsOneWidget);
      expect(await NulbomApi.elderKey(), 'nle_saved');
      expect(find.byKey(const Key('withdrawal-banner')), findsOneWidget);
      expect(find.text('탈퇴를 요청했어요'), findsOneWidget);
    });

    testWidgets('보호자가 없어 바로 탈퇴되면 로그인 화면으로 가고 열쇠를 지운다', (tester) async {
      await openDeleteFlow(tester, onRequest: () => json({'status': 'deleted'}));

      await tester.tap(find.text('계속'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('요청하기'));
      await tester.pumpAndSettle();

      expect(find.byType(ElderlyLoginScreen), findsOneWidget);
      expect(await NulbomApi.elderKey(), isNull);
    });

    testWidgets('승인을 기다리는 동안 메뉴는 탈퇴 승인 대기 중이고, 다시 누르면 이미 요청했다고 알린다', (tester) async {
      final calls = await openDeleteFlow(tester, onStatus: () => json(waitingBody), openConfirm: false);

      expect(find.text('탈퇴를 요청했어요'), findsOneWidget); // 홈을 열 때 서버에 물어 배너가 떴다
      await tester.tap(find.byIcon(Icons.more_horiz_rounded));
      await tester.pumpAndSettle();
      expect(find.text('탈퇴 승인 대기 중'), findsOneWidget);
      await tester.tap(find.text('탈퇴 승인 대기 중'));
      await tester.pumpAndSettle();

      expect(find.textContaining('이미 탈퇴를 요청했어요'), findsOneWidget);
      expect(asked(calls), isFalse);
    });

    testWidgets('첫 확인에서 취소하면 서버에 요청하지 않는다', (tester) async {
      final calls = await openDeleteFlow(tester);

      await tester.tap(find.text('취소'));
      await tester.pumpAndSettle();

      expect(asked(calls), isFalse);
      expect(find.byType(ElderlyHomePage), findsOneWidget);
    });

    testWidgets('두 번째 확인에서 취소해도 서버에 요청하지 않는다', (tester) async {
      final calls = await openDeleteFlow(tester);

      await tester.tap(find.text('계속'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('취소'));
      await tester.pumpAndSettle();

      expect(asked(calls), isFalse);
      expect(await NulbomApi.elderKey(), 'nle_saved');
    });

    testWidgets('요청하는 동안 뒤로가기를 눌러도 화면을 떠나지 않고, 끝나면 바로 탈퇴된 경우 로그인 화면으로 간다', (tester) async {
      final gate = Completer<void>();
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      SharedPreferences.setMockInitialValues({'elder_key': 'nle_saved', 'ai_friend_name': '봄이'});
      NulbomApi.client = MockClient((request) async {
        if (request.method == 'POST' && request.url.path == '/v1/me/withdrawal') {
          await gate.future;
          return json({'status': 'deleted'});
        }
        if (request.url.path == '/v1/me/withdrawal') return json({'status': 'none'});
        if (request.url.path == '/v1/me/calls') return json({'calls': []});
        if (request.url.path == '/v1/me/contacts') return json({'guardians': [], 'contacts': []});
        return json({'detail': 'x'}, 404);
      });
      await tester.pumpWidget(const MaterialApp(home: ElderlyHomePage()));
      await tester.pumpAndSettle();
      await tester.tap(find.byIcon(Icons.more_horiz_rounded));
      await tester.pumpAndSettle();
      await tester.tap(find.text('탈퇴하기'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('계속'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('요청하기'));
      await tester.pump();

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      await tester.binding.handlePopRoute();
      await tester.pump();
      expect(find.byType(CircularProgressIndicator), findsOneWidget); // 진행 표시가 그대로다

      gate.complete();
      await tester.pumpAndSettle();

      expect(find.byType(ElderlyLoginScreen), findsOneWidget);
      expect(await NulbomApi.elderKey(), isNull);
    });

    testWidgets('서버가 거절하면 문장을 보이고 어르신 화면에 남는다', (tester) async {
      await openDeleteFlow(tester, onRequest: () => json({'detail': '잠시 뒤에 다시 해 주세요'}, 503));

      await tester.tap(find.text('계속'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('요청하기'));
      await tester.pumpAndSettle();

      expect(find.text('잠시 뒤에 다시 해 주세요'), findsOneWidget);
      expect(find.byType(ElderlyHomePage), findsOneWidget);
      expect(await NulbomApi.elderKey(), 'nle_saved');
    });

    testWidgets('보호자가 거절하면 배너로 알리고, 확인을 누르면 요청을 치운다', (tester) async {
      final calls = await openDeleteFlow(
        tester,
        onStatus: () => json({'status': 'rejected', 'approved': 0, 'total': 1}),
        openConfirm: false,
      );

      expect(find.text('보호자가 탈퇴를 거절했어요'), findsOneWidget);
      await tester.tap(find.byKey(const Key('withdrawal-banner-action')));
      await tester.pumpAndSettle();

      expect(calls, contains('DELETE /v1/me/withdrawal'));
    });

    testWidgets('승인을 기다리는 요청은 취소할 수 있다', (tester) async {
      final calls = await openDeleteFlow(tester, onStatus: () => json(waitingBody), openConfirm: false);

      await tester.tap(find.text('요청 취소'));
      await tester.pumpAndSettle();

      expect(calls, contains('DELETE /v1/me/withdrawal'));
    });

    testWidgets('보호자가 이미 모두 승인해 취소할 수 없으면 서버 문장을 보이고 배너를 그대로 둔다', (tester) async {
      await openDeleteFlow(
        tester,
        onStatus: () => json(waitingBody),
        onCancel: () => json({'detail': '보호자가 이미 승인해서 곧 탈퇴돼요'}, 409),
        openConfirm: false,
      );

      await tester.tap(find.text('요청 취소'));
      await tester.pumpAndSettle();

      expect(find.text('보호자가 이미 승인해서 곧 탈퇴돼요'), findsOneWidget);
      expect(find.byKey(const Key('withdrawal-banner')), findsOneWidget);
    });

    testWidgets('보호자가 승인해 서버에서 탈퇴가 끝나면(열쇠가 401) 저절로 로그인 화면으로 간다', (tester) async {
      await openDeleteFlow(tester, onStatus: () => json({'detail': '열쇠가 필요합니다'}, 401), openConfirm: false);

      expect(find.byType(ElderlyLoginScreen), findsOneWidget);
      expect(find.textContaining('탈퇴가 처리됐거나'), findsOneWidget);
      expect(await NulbomApi.elderKey(), isNull);
    });
  });
}
