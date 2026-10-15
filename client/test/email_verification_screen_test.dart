import 'package:eldercare/screens/email_verification_screen.dart';
import 'package:eldercare/services/email_proof.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeProof implements EmailProof {
  FakeProof({this.session = false, this.token});
  bool session;
  String? token;
  final sent = <String>[];
  int resent = 0;
  Object? sendError;

  @override
  bool get hasSession => session;

  @override
  Future<void> sendVerification({required String email, required String password}) async {
    if (sendError != null) throw sendError!;
    sent.add('$email|$password');
    session = true;
  }

  @override
  Future<void> resend() async => resent++;

  @override
  Future<String?> verifiedIdToken() async => token;
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
}
