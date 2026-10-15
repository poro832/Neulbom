import 'dart:async';
import 'dart:convert';

import 'package:eldercare/models/nulbom_models.dart';
import 'package:eldercare/screens/email_verification_screen.dart';
import 'package:eldercare/screens/guardian_account_screen.dart';
import 'package:eldercare/screens/guardian_login_screen.dart';
import 'package:eldercare/screens/guardian_signup_screen.dart';
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

const profile = {
  'key': 'nlb_new',
  'name': '김보호',
  'email': 'kim@example.com',
  'phone': '010-1111-2222',
};

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
    NulbomApi.guardianKey = '';
  });
  tearDown(() {
    NulbomApi.guardianKey = '';
    AuthService.emailProof = FirebaseEmailProof();
  });

  group('NulbomApi / AuthService', () {
    test('가입하면 서버가 준 열쇠를 폰에 저장한다', () async {
      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return json(profile);
      });

      final result = await AuthService.guardianSignup(
        name: ' 김보호 ',
        email: 'kim@example.com',
        phone: '010-1111-2222',
        password: 'correct-horse-1',
      );

      expect(result['success'], isTrue);
      expect(seen.url.path, '/v1/guardian/signup');
      final sent = jsonDecode(seen.body) as Map<String, dynamic>;
      expect(sent['name'], '김보호');
      expect(sent['phone'], '010-1111-2222');
      expect(NulbomApi.guardianKey, 'nlb_new');
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('guardian_key'), 'nlb_new');
      expect(await AuthService.getUserType(), 'guardian');
    });

    test('가입: 비밀번호가 8자보다 짧으면 서버를 부르지 않는다', () async {
      var called = false;
      NulbomApi.client = MockClient((request) async {
        called = true;
        return json(profile);
      });

      final result = await AuthService.guardianSignup(
        name: '김보호',
        email: 'kim@example.com',
        phone: '010-1111-2222',
        password: '1234567',
      );

      expect(result['success'], isFalse);
      expect(called, isFalse);
    });

    test('가입: 이미 있는 이메일이면 서버 문장을 보여 주고 열쇠를 저장하지 않는다', () async {
      NulbomApi.client =
          MockClient((request) async => json({'detail': '이미 가입된 이메일이에요'}, 409));

      final result = await AuthService.guardianSignup(
        name: '김보호',
        email: 'kim@example.com',
        phone: '010-1111-2222',
        password: 'correct-horse-1',
      );

      expect(result['message'], '이미 가입된 이메일이에요');
      expect(NulbomApi.guardianKey, isEmpty);
      expect(await AuthService.isLoggedIn(), isFalse);
    });

    test('로그인: 틀리면 서버 문장을, 맞으면 열쇠를 저장한다', () async {
      NulbomApi.client = MockClient(
          (request) async => json({'detail': '이메일이나 비밀번호를 확인해 주세요'}, 401));
      final bad = await AuthService.guardianLogin(email: 'kim@example.com', password: 'wrong');
      expect(bad['success'], isFalse);
      expect(bad['message'], '이메일이나 비밀번호를 확인해 주세요');
      expect(NulbomApi.guardianKey, isEmpty);

      NulbomApi.client = MockClient((request) async => json(profile));
      final ok = await AuthService.guardianLogin(
          email: 'kim@example.com', password: 'correct-horse-1');
      expect(ok['success'], isTrue);
      expect(NulbomApi.guardianKey, 'nlb_new');
    });

    test('로그인: 서버에 닿지 못하면 안내 문장을 준다', () async {
      NulbomApi.client = MockClient((request) async => throw http.ClientException('down'));
      final result = await AuthService.guardianLogin(email: 'a@b.co', password: 'whatever-1');
      expect(result['success'], isFalse);
      expect(result['message'], contains('서버에 연결하지 못했어요'));
    });

    test('로그아웃: 서버에 열쇠 폐기를 알리고 폰에서 지운다', () async {
      NulbomApi.client = MockClient((request) async => json(profile));
      await AuthService.guardianLogin(email: 'kim@example.com', password: 'correct-horse-1');

      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return http.Response('', 204);
      });
      await AuthService.logout();

      expect(seen.url.path, '/v1/guardian/logout');
      expect(seen.headers['Authorization'], 'Bearer nlb_new');
      expect(NulbomApi.guardianKey, isEmpty);
      expect(await NulbomApi.loadGuardianKey(), isEmpty);
      expect(await AuthService.isLoggedIn(), isFalse);
    });

    test('로그아웃: 서버가 닿지 않아도 폰에서는 로그아웃된다', () async {
      await NulbomApi.saveGuardianKey('nlb_old');
      NulbomApi.client = MockClient((request) async => throw http.ClientException('down'));

      await AuthService.logout();

      expect(await NulbomApi.loadGuardianKey(), isEmpty);
    });

    test('로그아웃: 이 폰의 Firebase 세션도 끝낸다 — 같은 폰의 다음 보호자가 앞 사람 세션을 쓰지 않게', () async {
      final proof = FakeProof();
      AuthService.emailProof = proof;
      await NulbomApi.saveGuardianKey('nlb_old');
      NulbomApi.client = MockClient((request) async => http.Response('', 204));

      expect(await AuthService.logout(), isTrue);

      expect(proof.signedOut, 1);
      expect(await NulbomApi.loadGuardianKey(), isEmpty);
    });

    test('로그아웃: Firebase 세션 끝내기가 실패해도 로그아웃은 끝난다', () async {
      AuthService.emailProof = FakeProof(signOutError: StateError('Firebase 없음'));
      await NulbomApi.saveGuardianKey('nlb_old');
      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return http.Response('', 204);
      });

      expect(await AuthService.logout(), isTrue);

      expect(seen.url.path, '/v1/guardian/logout');
      expect(await NulbomApi.loadGuardianKey(), isEmpty);
      expect(await AuthService.isLoggedIn(), isFalse);
    });

    testWidgets('로그아웃: Firebase 세션 끝내기가 멈춰도 오래 기다리지 않고 로그아웃이 끝난다', (tester) async {
      final proof = FakeProof(signOutHangs: true);
      AuthService.emailProof = proof;
      await NulbomApi.saveGuardianKey('nlb_old');
      NulbomApi.client = MockClient((request) async => http.Response('', 204));

      bool? loggedOut;
      unawaited(AuthService.logout().then((ok) => loggedOut = ok));
      await tester.pump(const Duration(seconds: 3));
      await tester.pump();

      expect(proof.signedOut, 1);
      expect(loggedOut, isTrue);
      expect(await NulbomApi.loadGuardianKey(), isEmpty);
    });

    test('Firebase가 초기화되지 않은 폰에서도 진짜 감싸기의 세션 끝내기·세션 이메일은 조용히 넘어간다', () async {
      final proof = FirebaseEmailProof();

      await proof.signOut(); // 던지지 않는다
      expect(proof.sessionEmail, isNull);
    });

    test('저장된 열쇠를 시작할 때 불러온다', () async {
      SharedPreferences.setMockInitialValues({'guardian_key': 'nlb_saved'});
      expect(await NulbomApi.loadGuardianKey(), 'nlb_saved');
      expect(NulbomApi.guardianKey, 'nlb_saved');
    });

    test('열쇠가 없으면 요청 전에 로그인이 필요하다고 알린다', () async {
      expect(
        () => NulbomApi.guardianMe(),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', '로그인이 필요해요')),
      );
    });
  });

  rejectedKeyTests();
  pendingTests();
  emailPendingTests();

  group('화면', () {
    Future<void> pump(WidgetTester tester, Widget home) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      await tester.pumpWidget(MaterialApp(home: home));
      await tester.pumpAndSettle();
    }

    testWidgets('가입 화면: 전화번호 칸이 있고 비밀번호 8자 규칙을 안내한다', (tester) async {
      await pump(tester, const GuardianSignupScreen());

      expect(find.text('전화번호'), findsOneWidget);
      expect(find.text('8자 이상의 비밀번호'), findsOneWidget);
    });

    testWidgets('가입 화면: 7자 비밀번호는 서버를 부르지 않고 막는다', (tester) async {
      var called = false;
      NulbomApi.client = MockClient((request) async {
        called = true;
        return json(profile);
      });
      await pump(tester, const GuardianSignupScreen());

      final fields = find.byType(TextField);
      await tester.enterText(fields.at(0), '김보호');
      await tester.enterText(fields.at(1), 'kim@example.com');
      await tester.enterText(fields.at(2), '010-1111-2222');
      await tester.enterText(fields.at(3), '1234567');
      await tester.enterText(fields.at(4), '1234567');
      await tester.tap(find.text('회원가입 완료'));
      await tester.pumpAndSettle();

      expect(find.text('비밀번호는 8자 이상이어야 합니다.'), findsOneWidget);
      expect(called, isFalse);
    });

    testWidgets('로그인 화면: 서버가 거절하면 그 문장을 보여 준다', (tester) async {
      NulbomApi.client = MockClient(
          (request) async => json({'detail': '이메일이나 비밀번호를 확인해 주세요'}, 401));
      await pump(tester, const GuardianLoginScreen());

      final fields = find.byType(TextField);
      await tester.enterText(fields.at(0), 'kim@example.com');
      await tester.enterText(fields.at(1), 'wrong');
      await tester.tap(find.text('로그인').last);
      await tester.pumpAndSettle();

      expect(find.text('이메일이나 비밀번호를 확인해 주세요'), findsOneWidget);
    });

    testWidgets('계정 화면: 서버의 이름·이메일·전화를 보여 준다', (tester) async {
      NulbomApi.guardianKey = 'nlb_test';
      NulbomApi.client = MockClient((request) async {
        expect(request.url.path, '/v1/guardian/me');
        return json({'name': '김보호', 'email': 'kim@example.com', 'phone': '010-1111-2222'});
      });

      await pump(tester, const GuardianAccountScreen());

      expect(find.text('kim@example.com'), findsWidgets);
      expect(find.text('010-1111-2222'), findsOneWidget);
    });

    testWidgets('계정 화면: 비밀번호를 바꾸고 다른 폰이 로그아웃된다고 알려 준다', (tester) async {
      NulbomApi.guardianKey = 'nlb_test';
      late http.Request changed;
      NulbomApi.client = MockClient((request) async {
        if (request.url.path == '/v1/guardian/password') {
          changed = request;
          return json({'revoked_others': 2});
        }
        return json({'name': '김보호', 'email': 'kim@example.com', 'phone': '010-1111-2222'});
      });
      await pump(tester, const GuardianAccountScreen());

      await tester.ensureVisible(find.text('비밀번호 변경'));
      await tester.tap(find.text('비밀번호 변경'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('current-password')), 'correct-horse-1');
      await tester.enterText(find.byKey(const Key('new-password')), 'brand-new-pass-2');
      await tester.tap(find.text('변경'));
      await tester.pumpAndSettle();

      final sent = jsonDecode(changed.body) as Map<String, dynamic>;
      expect(sent, {'current': 'correct-horse-1', 'new': 'brand-new-pass-2'});
      expect(changed.headers['Authorization'], 'Bearer nlb_test');
      expect(find.textContaining('다른 폰 2대는 로그아웃됐어요'), findsOneWidget);
    });

    testWidgets('계정 화면: 현재 비밀번호가 틀리면 대화상자에 서버 문장을 보여 준다', (tester) async {
      NulbomApi.guardianKey = 'nlb_test';
      NulbomApi.client = MockClient((request) async {
        if (request.url.path == '/v1/guardian/password') {
          return json({'detail': '현재 비밀번호를 확인해 주세요'}, 403);
        }
        return json({'name': '김보호', 'email': 'kim@example.com', 'phone': '010-1111-2222'});
      });
      await pump(tester, const GuardianAccountScreen());

      await tester.ensureVisible(find.text('비밀번호 변경'));
      await tester.tap(find.text('비밀번호 변경'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('current-password')), 'nope-nope-1');
      await tester.enterText(find.byKey(const Key('new-password')), 'brand-new-pass-2');
      await tester.tap(find.text('변경'));
      await tester.pumpAndSettle();

      expect(find.text('현재 비밀번호를 확인해 주세요'), findsOneWidget);
      expect(find.byKey(const Key('new-password')), findsOneWidget); // 대화상자가 그대로 열려 있다
    });
  });
}

void rejectedKeyTests() {
  group('열쇠가 거절되면', () {
    setUp(() {
      SharedPreferences.setMockInitialValues({'guardian_key': 'nlb_old'});
      NulbomApi.guardianKey = 'nlb_old';
    });
    tearDown(() {
      NulbomApi.onGuardianKeyRejected = null;
      NulbomApi.guardianKey = '';
    });

    test('저장된 열쇠를 지우고 알려 준다', () async {
      var notified = 0;
      NulbomApi.onGuardianKeyRejected = () => notified++;
      NulbomApi.client =
          MockClient((request) async => json({'detail': '열쇠가 필요합니다'}, 401));

      await expectLater(NulbomApi.guardianMe(), throwsA(isA<ApiException>()));

      await Future<void>.delayed(Duration.zero); // 폰 저장소 정리가 끝나길 기다린다
      expect(notified, 1);
      expect(NulbomApi.guardianKey, isEmpty);
      expect(await NulbomApi.loadGuardianKey(), isEmpty);
    });

    test('로그인 실패(열쇠 없는 요청의 401)는 알리지 않는다', () async {
      var notified = 0;
      NulbomApi.onGuardianKeyRejected = () => notified++;
      NulbomApi.client = MockClient(
          (request) async => json({'detail': '이메일이나 비밀번호를 확인해 주세요'}, 401));

      await AuthService.guardianLogin(email: 'a@b.co', password: 'wrong-pass');

      expect(notified, 0);
      expect(NulbomApi.guardianKey, 'nlb_old');
    });
  });
}

void pendingTests() {
  group('운영자 확인 대기', () {
    testWidgets('계정 화면에 확인 대기라고 보여 준다', (tester) async {
      GoogleFonts.config.allowRuntimeFetching = false;
      SharedPreferences.setMockInitialValues({});
      NulbomApi.guardianKey = 'nlb_test';
      addTearDown(() => NulbomApi.guardianKey = '');
      NulbomApi.client = MockClient((request) async => json({
            'name': '김보호',
            'email': 'kim@example.com',
            'phone': '010-1111-2222',
            'activated': false,
          }));
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);

      await tester.pumpWidget(const MaterialApp(home: GuardianAccountScreen()));
      await tester.pumpAndSettle();

      expect(find.text('운영자 확인 대기 중'), findsOneWidget);
      expect(find.text('활성 중'), findsNothing);
    });

    test('activated가 없는 옛 응답은 열린 것으로 읽는다', () {
      final p = GuardianProfile.fromJson(
          {'name': '가', 'email': 'a@b.co', 'phone': '010-0000-0000'});
      expect(p.activated, isTrue);
    });
  });
}

/// Firebase 대신 쓰는 가짜 — 이 폰에 kim@example.com의 세션이 있고, 링크를 눌렀으면 [token]을 준다.
class FakeProof implements EmailProof {
  FakeProof({this.token, this.signOutError, this.signOutHangs = false});
  final String? token;
  final Object? signOutError;
  final bool signOutHangs;
  int signedOut = 0;

  @override
  bool get hasSession => true;

  @override
  String? get sessionEmail => 'kim@example.com';

  @override
  Future<void> signOut() {
    signedOut++;
    if (signOutError != null) throw signOutError!; // 기다리기 전에 바로 터지는 경우
    if (signOutHangs) return Completer<void>().future; // 끝나지 않는 경우
    return Future.value();
  }

  @override
  Future<void> sendVerification({required String email, required String password}) async {}

  @override
  Future<void> resend() async {}

  @override
  Future<String?> verifiedIdToken() async => token;
}

void emailPendingTests() {
  group('이메일 인증 대기', () {
    Map<String, dynamic> me({required bool emailVerified}) => {
          'name': '김보호',
          'email': 'kim@example.com',
          'phone': '010-1111-2222',
          'activated': true,
          'email_verified': emailVerified,
        };

    Future<void> pump(WidgetTester tester, Widget home) async {
      GoogleFonts.config.allowRuntimeFetching = false;
      SharedPreferences.setMockInitialValues({});
      NulbomApi.guardianKey = 'nlb_test';
      addTearDown(() => NulbomApi.guardianKey = '');
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      await tester.pumpWidget(MaterialApp(home: home));
      await tester.pumpAndSettle();
    }

    testWidgets('인증 전이면 대기 표시와 인증하기 버튼을 보여 준다', (tester) async {
      NulbomApi.client = MockClient((request) async => json(me(emailVerified: false)));

      await pump(tester, const GuardianAccountScreen());

      expect(find.text('이메일 인증 대기 중'), findsOneWidget);
      expect(find.text('이메일 인증하기'), findsOneWidget);
      expect(find.text('활성 중'), findsOneWidget); // 운영자 확인 표시는 그대로 있다
    });

    testWidgets('인증됐으면(또는 옛 응답이면) 표시와 버튼이 없다', (tester) async {
      NulbomApi.client = MockClient((request) async => json(me(emailVerified: true)));

      await pump(tester, const GuardianAccountScreen());

      expect(find.text('이메일 인증 대기 중'), findsNothing);
      expect(find.text('이메일 인증하기'), findsNothing);
    });

    testWidgets('인증하기 → 인증을 마치고 돌아오면 서버에서 새로 읽어 표시를 내린다', (tester) async {
      var verified = false;
      var meCalls = 0;
      NulbomApi.client = MockClient((request) async {
        if (request.url.path == '/v1/guardian/email/verify') {
          expect(jsonDecode(request.body), {'id_token': 'firebase-id-token'});
          verified = true;
          return json({'email_verified': true});
        }
        meCalls++;
        return json(me(emailVerified: verified));
      });

      await pump(tester,
          GuardianAccountScreen(emailProof: FakeProof(token: 'firebase-id-token')));
      expect(meCalls, 1);

      await tester.tap(find.text('이메일 인증하기'));
      await tester.pumpAndSettle();
      expect(find.byType(EmailVerificationScreen), findsOneWidget);
      expect(find.textContaining('kim@example.com로 인증 메일을 보냈어요'), findsOneWidget);

      await tester.tap(find.text('인증했어요'));
      await tester.pumpAndSettle();

      expect(find.byType(EmailVerificationScreen), findsNothing);
      expect(meCalls, 2);
      expect(find.text('이메일 인증 대기 중'), findsNothing);
      expect(find.text('이메일 인증하기'), findsNothing);
    });

    testWidgets('나중에 하기로 돌아와도 서버에서 새로 읽고, 인증 전이면 표시가 남는다', (tester) async {
      var meCalls = 0;
      NulbomApi.client = MockClient((request) async {
        meCalls++;
        return json(me(emailVerified: false));
      });

      await pump(tester, GuardianAccountScreen(emailProof: FakeProof()));
      await tester.tap(find.text('이메일 인증하기'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('나중에 하기'));
      await tester.pumpAndSettle();

      expect(meCalls, 2);
      expect(find.text('이메일 인증 대기 중'), findsOneWidget);
    });

    testWidgets('돌아와 다시 읽기에 실패해도 이미 아는 인증 전 상태를 지켜 표시와 버튼이 남는다', (tester) async {
      var meCalls = 0;
      NulbomApi.client = MockClient((request) async {
        meCalls++;
        if (meCalls == 1) return json(me(emailVerified: false));
        throw http.ClientException('down'); // 돌아온 뒤에는 서버에 닿지 못한다
      });

      await pump(tester, GuardianAccountScreen(emailProof: FakeProof()));
      await tester.tap(find.text('이메일 인증하기'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('나중에 하기'));
      await tester.pumpAndSettle();

      expect(meCalls, 2);
      expect(find.text('이메일 인증 대기 중'), findsOneWidget);
      expect(find.text('이메일 인증하기'), findsOneWidget);
      expect(find.text('kim@example.com'), findsWidgets);

      // 이메일도 그대로라 버튼을 다시 누르면 인증 화면이 열린다.
      await tester.tap(find.text('이메일 인증하기'));
      await tester.pumpAndSettle();
      expect(find.byType(EmailVerificationScreen), findsOneWidget);
    });
  });
}
