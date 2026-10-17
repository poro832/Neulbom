import 'dart:convert';

import 'package:eldercare/screens/email_verification_screen.dart';
import 'package:eldercare/screens/guardian_screen.dart';
import 'package:eldercare/screens/guardian_signup_screen.dart';
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

/// Firebase 대신 쓰는 가짜 — 실제 메일을 보내지 않는다.
class FakeProof implements EmailProof {
  FakeProof({this.token});
  String? token;
  bool session = false;
  String? email;
  final sent = <String>[];

  @override
  bool get hasSession => session;

  @override
  String? get sessionEmail => session ? email : null;

  @override
  Future<void> signOut() async => session = false;

  @override
  Future<void> sendVerification({required String email, required String password}) async {
    sent.add('$email|$password');
    session = true;
    this.email = email;
  }

  @override
  Future<void> resend() async {}

  @override
  Future<String?> verifiedIdToken() async => token;

  @override
  Future<void> sendPasswordReset({required String email}) async {}

  @override
  Future<String> idTokenForReset({required String email, required String password}) async => 'reset-token';
}

Future<void> fillAndSubmit(WidgetTester tester) async {
  final fields = find.byType(TextField);
  await tester.enterText(fields.at(0), '김보호');
  await tester.enterText(fields.at(1), 'kim@example.com');
  await tester.enterText(fields.at(2), '010-1111-2222');
  await tester.enterText(fields.at(3), 'correct-horse-1');
  await tester.enterText(fields.at(4), 'correct-horse-1');
  await tester.tap(find.text('회원가입 완료'));
  await tester.pumpAndSettle();
}

const unverifiedSignup = {
  'key': 'nlb_new',
  'name': '김보호',
  'email': 'kim@example.com',
  'phone': '010-1111-2222',
  'activated': false,
  'email_verified': false,
};

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
    NulbomApi.guardianKey = '';
  });
  tearDown(() => NulbomApi.guardianKey = '');

  testWidgets('가입하면 완료 화면이 운영자 확인을 알리고, 시작하기는 로그인 없이 보호자 홈으로 간다', (tester) async {
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    NulbomApi.client = MockClient((request) async {
      final path = request.url.path;
      if (path == '/v1/guardian/signup') {
        return json({
          'key': 'nlb_new',
          'name': '김보호',
          'email': 'kim@example.com',
          'phone': '010-1111-2222',
          'activated': false,
        });
      }
      if (path == '/v1/guardian/elders') return json({'elders': []});
      if (path == '/v1/guardian/alerts') return json({'alerts': []});
      return json({'detail': 'x'}, 404);
    });

    await tester.pumpWidget(const MaterialApp(home: GuardianSignupScreen()));
    await fillAndSubmit(tester);

    // 응답에 email_verified가 없으면(옛 서버) 인증된 것으로 보고 인증 화면을 열지 않는다.
    expect(find.byType(EmailVerificationScreen), findsNothing);
    expect(find.text('회원가입이 완료되었습니다'), findsOneWidget);
    expect(find.textContaining('운영자 확인 후 어르신을 연결할 수 있어요'), findsOneWidget);
    expect(find.text('로그인하러 가기'), findsNothing); // 열쇠가 이미 폰에 있다
    expect(NulbomApi.guardianKey, 'nlb_new');

    await tester.tap(find.text('시작하기'));
    await tester.pumpAndSettle();

    expect(find.byType(GuardianScreen), findsOneWidget);
    expect(find.text('관리 중인 어르신이 아직 없어요.'), findsOneWidget);
  });

  testWidgets('이메일 인증 전 가입이면 입력한 이메일·비밀번호로 인증 화면을 열고, 나중에 하기를 누르면 완료 화면으로 간다', (tester) async {
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    NulbomApi.client = MockClient((request) async {
      if (request.url.path == '/v1/guardian/signup') return json(unverifiedSignup);
      return json({'detail': 'x'}, 404);
    });
    final proof = FakeProof();

    await tester.pumpWidget(MaterialApp(home: GuardianSignupScreen(emailProof: proof)));
    await fillAndSubmit(tester);

    expect(find.byType(EmailVerificationScreen), findsOneWidget);
    expect(proof.sent, ['kim@example.com|correct-horse-1']);
    expect(find.textContaining('kim@example.com로 인증 메일을 보냈어요'), findsOneWidget);
    expect(find.text('회원가입이 완료되었습니다'), findsNothing);

    await tester.tap(find.text('나중에 하기'));
    await tester.pumpAndSettle();

    expect(find.byType(EmailVerificationScreen), findsNothing);
    expect(find.text('회원가입이 완료되었습니다'), findsOneWidget);
    expect(find.text('시작하기'), findsOneWidget);
  });

  testWidgets('인증 화면에서 인증을 마치면 서버에 증명서를 보내고 완료 화면으로 간다', (tester) async {
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    late http.Request verified;
    NulbomApi.client = MockClient((request) async {
      if (request.url.path == '/v1/guardian/signup') return json(unverifiedSignup);
      if (request.url.path == '/v1/guardian/email/verify') {
        verified = request;
        return json({'email_verified': true});
      }
      return json({'detail': 'x'}, 404);
    });
    final proof = FakeProof(token: 'firebase-id-token');

    await tester.pumpWidget(MaterialApp(home: GuardianSignupScreen(emailProof: proof)));
    await fillAndSubmit(tester);
    await tester.tap(find.text('인증했어요'));
    await tester.pumpAndSettle();

    expect(jsonDecode(verified.body), {'id_token': 'firebase-id-token'});
    expect(verified.headers['Authorization'], 'Bearer nlb_new'); // 가입으로 받은 열쇠
    expect(find.byType(EmailVerificationScreen), findsNothing);
    expect(find.text('회원가입이 완료되었습니다'), findsOneWidget);
  });

  testWidgets('비밀번호 확인 칸: 입력하는 동안 다르면 바로 알리고, 같아지면 사라진다', (tester) async {
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    await tester.pumpWidget(const MaterialApp(home: GuardianSignupScreen()));
    const mismatch = '비밀번호가 동일하지 않습니다.';
    final fields = find.byType(TextField);

    await tester.enterText(fields.at(3), 'correct-horse-1');
    await tester.pump();
    expect(find.text(mismatch), findsNothing); // 확인 칸을 아직 안 쳤다

    await tester.enterText(fields.at(4), 'correct');
    await tester.pump();
    expect(find.text(mismatch), findsOneWidget);

    await tester.enterText(fields.at(4), 'correct-horse-1');
    await tester.pump();
    expect(find.text(mismatch), findsNothing);

    await tester.enterText(fields.at(3), 'other-password-2'); // 위 칸을 고쳐도 다시 알린다
    await tester.pump();
    expect(find.text(mismatch), findsOneWidget);
  });

  testWidgets('비밀번호가 다르면 서버에 가입 요청을 보내지 않는다', (tester) async {
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    var called = false;
    NulbomApi.client = MockClient((request) async {
      called = true;
      return json({'detail': 'x'}, 500);
    });
    await tester.pumpWidget(const MaterialApp(home: GuardianSignupScreen()));
    final fields = find.byType(TextField);
    await tester.enterText(fields.at(0), '김보호');
    await tester.enterText(fields.at(1), 'kim@example.com');
    await tester.enterText(fields.at(2), '010-1111-2222');
    await tester.enterText(fields.at(3), 'correct-horse-1');
    await tester.enterText(fields.at(4), 'correct-horse-2');
    await tester.tap(find.text('회원가입 완료'));
    await tester.pumpAndSettle();

    expect(called, isFalse);
    expect(find.text('비밀번호가 동일하지 않습니다.'), findsWidgets);
  });
}
