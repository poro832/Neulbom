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

    test('어르신 탈퇴: 어르신 열쇠로 DELETE /v1/me에 확인 값을 싣는다', () async {
      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return noContent();
      });

      await NulbomApi.deleteElderAccount(key: 'nle_test');

      expect(seen.method, 'DELETE');
      expect(seen.url.path, '/v1/me');
      expect(seen.headers['Authorization'], 'Bearer nle_test');
      expect(jsonDecode(seen.body), {'confirm': true});
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

    test('어르신 탈퇴가 성공하면 폰의 어르신 열쇠와 정보를 지운다', () async {
      SharedPreferences.setMockInitialValues({
        'user_type': 'elderly',
        'is_logged_in': true,
        'elder_key': 'nle_test',
      });
      NulbomApi.client = MockClient((request) async => noContent());

      await AuthService.deleteElderAccount();

      expect(await NulbomApi.elderKey(), isNull);
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getBool('is_logged_in'), isNull);
    });

    test('어르신 탈퇴를 서버가 거절하면 열쇠를 그대로 둔다', () async {
      SharedPreferences.setMockInitialValues({'user_type': 'elderly', 'elder_key': 'nle_test'});
      NulbomApi.client = MockClient(
          (request) async => json({'detail': '잠시 뒤에 다시 해 주세요'}, 503));

      await expectLater(AuthService.deleteElderAccount(), throwsA(isA<ApiException>()));

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
    Future<List<String>> openDeleteFlow(WidgetTester tester, http.Response Function() onDelete) async {
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
        if (request.method == 'DELETE' && request.url.path == '/v1/me') return onDelete();
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
      return calls;
    }

    testWidgets('탈퇴하기: 두 번 확인해야 서버를 부르고, 끝나면 로그인 화면으로 간다', (tester) async {
      final calls = await openDeleteFlow(tester, noContent);

      expect(find.textContaining('통화 기록이 모두 지워지고'), findsOneWidget);
      expect(calls.where((c) => c.startsWith('DELETE')), isEmpty);
      await tester.tap(find.text('계속'));
      await tester.pumpAndSettle();
      expect(find.text('정말 탈퇴할까요?'), findsOneWidget);
      expect(calls.where((c) => c.startsWith('DELETE')), isEmpty);
      await tester.tap(find.text('탈퇴하기').last);
      await tester.pumpAndSettle();

      expect(calls, contains('DELETE /v1/me'));
      expect(find.byType(ElderlyLoginScreen), findsOneWidget);
      expect(await NulbomApi.elderKey(), isNull);
    });

    testWidgets('첫 확인에서 취소하면 서버를 부르지 않는다', (tester) async {
      final calls = await openDeleteFlow(tester, noContent);

      await tester.tap(find.text('취소'));
      await tester.pumpAndSettle();

      expect(calls.where((c) => c.startsWith('DELETE')), isEmpty);
      expect(find.byType(ElderlyHomePage), findsOneWidget);
    });

    testWidgets('두 번째 확인에서 취소해도 서버를 부르지 않는다', (tester) async {
      final calls = await openDeleteFlow(tester, noContent);

      await tester.tap(find.text('계속'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('취소'));
      await tester.pumpAndSettle();

      expect(calls.where((c) => c.startsWith('DELETE')), isEmpty);
      expect(await NulbomApi.elderKey(), 'nle_saved');
    });

    testWidgets('지우는 동안 뒤로가기를 눌러도 화면을 떠나지 않고, 끝나면 로그인 화면으로 간다', (tester) async {
      final gate = Completer<void>();
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      SharedPreferences.setMockInitialValues({'elder_key': 'nle_saved', 'ai_friend_name': '봄이'});
      NulbomApi.client = MockClient((request) async {
        if (request.method == 'DELETE' && request.url.path == '/v1/me') {
          await gate.future;
          return noContent();
        }
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
      await tester.tap(find.text('탈퇴하기').last);
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
      await openDeleteFlow(tester, () => json({'detail': '잠시 뒤에 다시 해 주세요'}, 503));

      await tester.tap(find.text('계속'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('탈퇴하기').last);
      await tester.pumpAndSettle();

      expect(find.text('잠시 뒤에 다시 해 주세요'), findsOneWidget);
      expect(find.byType(ElderlyHomePage), findsOneWidget);
      expect(await NulbomApi.elderKey(), 'nle_saved');
    });
  });
}
