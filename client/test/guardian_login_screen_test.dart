import 'package:eldercare/screens/guardian_login_screen.dart';
import 'package:eldercare/screens/password_reset_screen.dart';
import 'package:eldercare/services/email_proof.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:shared_preferences/shared_preferences.dart';

const String forgot = '비밀번호를 잊으셨나요?';
const String done = '비밀번호를 바꿨어요. 새 비밀번호로 로그인해 주세요.';
const String newPassword = 'brand-new-pass-3';
const String resetToken = 'firebase-reset-token-0123456789';

/// Firebase 대신 쓰는 가짜 — 재설정 메일을 보내지 않고, 보낸 이메일만 적어 둔다.
class FakeResetProof implements EmailProof {
  final resetMails = <String>[];

  @override
  bool get hasSession => false;

  @override
  String? get sessionEmail => null;

  @override
  Future<void> signOut() async {}

  @override
  Future<void> sendVerification({required String email, required String password}) async {}

  @override
  Future<void> resend() async {}

  @override
  Future<String?> verifiedIdToken() async => null;

  @override
  Future<void> sendPasswordReset({required String email}) async => resetMails.add(email);

  @override
  Future<String> idTokenForReset({required String email, required String password}) async => resetToken;

  @override
  Future<void> rotatePassword({String? knownPassword}) async {}
}

Future<void> open(WidgetTester tester, {EmailProof? proof, Future<void> Function(String, String)? reset}) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(MaterialApp(home: GuardianLoginScreen(emailProof: proof, resetPassword: reset)));
  await tester.pumpAndSettle();
}

TextField loginField(WidgetTester tester, int index) => tester.widget<TextField>(find.byType(TextField).at(index));

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
    NulbomApi.guardianKey = '';
  });

  testWidgets('비밀번호 칸 아래의 링크를 누르면 입력한 이메일로 비밀번호 찾기 화면이 열린다', (tester) async {
    await open(tester, proof: FakeResetProof(), reset: (_, _) async {});
    await tester.enterText(find.byType(TextField).at(0), ' kim@example.com ');

    expect(
      tester.getTopLeft(find.text(forgot)).dy,
      greaterThan(tester.getTopLeft(find.byType(TextField).at(1)).dy),
    );
    await tester.tap(find.text(forgot));
    await tester.pumpAndSettle();

    expect(find.byType(PasswordResetScreen), findsOneWidget);
    final email = tester.widget<TextField>(find.byKey(PasswordResetScreen.emailField));
    expect(email.controller!.text, 'kim@example.com');
  });

  testWidgets('재설정을 마치고 돌아오면 완료 안내를 보이고 비밀번호 칸을 비운다', (tester) async {
    final proof = FakeResetProof();
    final resets = <String>[];
    await open(tester, proof: proof, reset: (token, password) async => resets.add('$token|$password'));
    await tester.enterText(find.byType(TextField).at(0), 'kim@example.com');
    await tester.enterText(find.byType(TextField).at(1), 'old-forgotten-1');

    await tester.tap(find.text(forgot));
    await tester.pumpAndSettle();
    await tester.tap(find.text('재설정 메일 보내기'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(PasswordResetScreen.newPasswordField), newPassword);
    await tester.enterText(find.byKey(PasswordResetScreen.confirmPasswordField), newPassword);
    await tester.pump();
    await tester.tap(find.text('비밀번호 바꾸기'));
    await tester.pumpAndSettle();

    expect(proof.resetMails, ['kim@example.com']);
    expect(resets, ['$resetToken|$newPassword']);
    expect(find.byType(PasswordResetScreen), findsNothing);
    expect(find.text(done), findsOneWidget);
    expect(loginField(tester, 1).controller!.text, isEmpty);
    expect(loginField(tester, 0).controller!.text, 'kim@example.com');
  });

  testWidgets('바꾸지 않고 돌아오면 안내 없이 입력한 비밀번호도 그대로다', (tester) async {
    await open(tester, proof: FakeResetProof(), reset: (_, _) async {});
    await tester.enterText(find.byType(TextField).at(1), 'typed-password-1');

    await tester.tap(find.text(forgot));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.arrow_back_rounded));
    await tester.pumpAndSettle();

    expect(find.byType(PasswordResetScreen), findsNothing);
    expect(find.text(done), findsNothing);
    expect(loginField(tester, 1).controller!.text, 'typed-password-1');
  });
}
