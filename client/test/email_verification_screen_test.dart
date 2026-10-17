import 'package:eldercare/screens/email_verification_screen.dart';
import 'package:eldercare/services/email_proof.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeProof implements EmailProof {
  /// [email]은 이 폰의 Firebase 세션 주인이다. 기본은 아래 시험들이 화면에 주는 'a@b.co'.
  FakeProof({this.session = false, this.token, this.email = 'a@b.co'});
  bool session;
  String? token;
  String? email;
  final sent = <String>[];
  int resent = 0;
  int signedOut = 0;
  Object? sendError;
  Object? resendError;

  @override
  bool get hasSession => session;

  @override
  String? get sessionEmail => session ? email : null;

  @override
  Future<void> sendVerification({required String email, required String password}) async {
    if (sendError != null) throw sendError!;
    sent.add('$email|$password');
    session = true;
    this.email = email; // Firebase는 이 이메일로 로그인한다(앞 사람 세션은 바뀐다)
  }

  @override
  Future<void> resend() async {
    if (resendError != null) {
      session = false; // 세션이 끊겨 다시 보내지 못했다
      throw resendError!;
    }
    resent++;
  }

  @override
  Future<String?> verifiedIdToken() async => token;

  @override
  Future<void> signOut() async {
    signedOut++;
    session = false;
  }

  @override
  Future<void> sendPasswordReset({required String email}) async {}

  @override
  Future<String> idTokenForReset({required String email, required String password}) async => 'reset-token';
}

Future<void> pump(WidgetTester tester, EmailVerificationScreen screen, {List<bool>? result}) async {
  await tester.pumpWidget(MaterialApp(
    home: Builder(
      builder: (context) => Scaffold(
        body: TextButton(
          onPressed: () async {
            final r = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => screen));
            result?.add(r ?? false);
          },
          child: const Text('열기'),
        ),
      ),
    ),
  ));
  await tester.tap(find.text('열기'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('가입 직후: 비밀번호가 있으면 바로 인증 메일을 보낸다', (tester) async {
    final proof = FakeProof();
    await pump(tester, EmailVerificationScreen(email: 'kim@example.com', password: 'secret-pass-1', proof: proof, verify: (_) async => true));

    expect(proof.sent, ['kim@example.com|secret-pass-1']);
    expect(find.textContaining('kim@example.com'), findsWidgets);
    expect(find.text('인증했어요'), findsOneWidget);
  });

  testWidgets('아직 링크를 안 눌렀으면 안내만 하고 서버를 부르지 않는다', (tester) async {
    final proof = FakeProof(session: true, token: null);
    var called = false;
    await pump(tester, EmailVerificationScreen(email: 'a@b.co', proof: proof, verify: (_) async { called = true; return true; }));

    await tester.tap(find.text('인증했어요'));
    await tester.pumpAndSettle();

    expect(called, isFalse);
    expect(find.textContaining('아직 인증되지 않았어요'), findsOneWidget);
  });

  testWidgets('인증됐으면 증명서를 서버에 보내고 true로 닫힌다', (tester) async {
    final proof = FakeProof(session: true, token: 'tok-' * 10);
    String? sent;
    final result = <bool>[];
    await pump(tester, EmailVerificationScreen(email: 'a@b.co', proof: proof, verify: (t) async { sent = t; return true; }), result: result);

    await tester.tap(find.text('인증했어요'));
    await tester.pumpAndSettle();

    expect(sent, 'tok-' * 10);
    expect(result, [true]);
  });

  testWidgets('세션이 없고 비밀번호도 없으면 비밀번호를 입력받아 메일을 보낸다', (tester) async {
    final proof = FakeProof(session: false);
    await pump(tester, EmailVerificationScreen(email: 'a@b.co', proof: proof, verify: (_) async => true));

    expect(proof.sent, isEmpty);
    await tester.enterText(find.byType(TextField), 'secret-pass-1');
    await tester.tap(find.text('인증 메일 보내기'));
    await tester.pumpAndSettle();

    expect(proof.sent, ['a@b.co|secret-pass-1']);
  });

  testWidgets('다시 보내기와 서버 거절 문장', (tester) async {
    final proof = FakeProof(session: true, token: 'tok-' * 10);
    await pump(tester, EmailVerificationScreen(email: 'a@b.co', proof: proof, verify: (_) async => throw Exception('x')));

    await tester.tap(find.text('다시 보내기'));
    await tester.pumpAndSettle();
    expect(proof.resent, 1);

    await tester.tap(find.text('인증했어요'));
    await tester.pumpAndSettle();
    expect(find.byType(SnackBar), findsNothing); // 오류는 화면 안 문장으로 보여 준다
    expect(find.textContaining('인증을 확인하지 못했어요'), findsOneWidget);
  });

  testWidgets('이 폰의 Firebase 세션이 다른 보호자 것이면 세션이 없는 것으로 보고 비밀번호를 받아 이 이메일로 보낸다', (tester) async {
    // 같은 폰에서 앞 보호자가 인증하다 로그아웃했고, 다른 보호자가 계정 화면에서 인증을 연 경우
    final proof = FakeProof(session: true, email: 'other@example.com', token: 'tok-' * 10);
    var called = false;
    await pump(tester, EmailVerificationScreen(email: 'kim@example.com', proof: proof, verify: (_) async { called = true; return true; }));

    expect(find.byType(TextField), findsOneWidget);
    expect(find.text('인증 메일 보내기'), findsOneWidget);
    expect(find.text('인증했어요'), findsNothing); // 앞 사람의 증명서를 서버에 보내지 않는다
    expect(find.text('다시 보내기'), findsNothing);

    await tester.enterText(find.byType(TextField), 'secret-pass-1');
    await tester.tap(find.text('인증 메일 보내기'));
    await tester.pumpAndSettle();

    expect(proof.sent, ['kim@example.com|secret-pass-1']);
    expect(find.text('인증했어요'), findsOneWidget);
    expect(called, isFalse);
  });

  testWidgets('세션 이메일의 대소문자만 다르면 같은 보호자로 본다', (tester) async {
    final proof = FakeProof(session: true, email: 'Kim@Example.com');
    await pump(tester, EmailVerificationScreen(email: 'kim@example.com', proof: proof, verify: (_) async => true));

    expect(find.byType(TextField), findsNothing);
    expect(find.text('인증했어요'), findsOneWidget);
  });

  testWidgets('세션은 있는데 주인 이메일을 모르면 비밀번호를 받는다', (tester) async {
    final proof = FakeProof(session: true, email: null);
    await pump(tester, EmailVerificationScreen(email: 'kim@example.com', proof: proof, verify: (_) async => true));

    expect(find.byType(TextField), findsOneWidget);
    expect(find.text('인증 메일 보내기'), findsOneWidget);
  });

  testWidgets('가입 직후 보내기가 실패하고 세션도 없으면 오류 문장과 비밀번호 칸을 함께 보여 준다', (tester) async {
    final proof = FakeProof()..sendError = const EmailProofException('비밀번호를 확인해 주세요.');
    await pump(tester, EmailVerificationScreen(email: 'a@b.co', password: 'secret-pass-1', proof: proof, verify: (_) async => true));

    expect(find.text('비밀번호를 확인해 주세요.'), findsOneWidget);
    expect(find.byType(TextField), findsOneWidget);
    expect(find.text('인증 메일 보내기'), findsOneWidget);
  });

  testWidgets('다시 보내기가 세션이 끊겨 실패하면 비밀번호 칸으로 바뀐다', (tester) async {
    final proof = FakeProof(session: true)..resendError = const EmailProofException('다시 로그인이 필요해요.');
    await pump(tester, EmailVerificationScreen(email: 'a@b.co', proof: proof, verify: (_) async => true));
    expect(find.byType(TextField), findsNothing);

    await tester.tap(find.text('다시 보내기'));
    await tester.pumpAndSettle();

    expect(find.text('다시 로그인이 필요해요.'), findsOneWidget);
    expect(find.byType(TextField), findsOneWidget);
    expect(find.text('인증 메일 보내기'), findsOneWidget);
  });
}
