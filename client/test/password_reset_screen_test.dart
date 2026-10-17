import 'dart:async';
import 'dart:convert';

import 'package:eldercare/screens/password_reset_screen.dart';
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

const String mismatch = '비밀번호가 동일하지 않습니다.';
const String guide = '메일의 링크를 눌러 새 비밀번호를 정한 뒤, 같은 비밀번호를 아래에 입력해 주세요.';
const String tooShort = '비밀번호는 8자 이상이어야 합니다.';
const String newPassword = 'brand-new-pass-3';
const String resetToken = 'firebase-reset-token-0123456789';

/// Firebase 대신 쓰는 가짜 — 재설정 메일을 보내지 않고, 받은 요청만 적어 둔다.
class FakeResetProof implements EmailProof {
  final resetMails = <String>[];
  final signIns = <String>[];
  Object? sendError;
  Object? signInError;
  Completer<String>? pendingToken;
  int rotated = 0;
  bool rotateHangs = false;
  Object? rotateError;

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
  Future<void> sendPasswordReset({required String email}) async {
    if (sendError != null) throw sendError!;
    resetMails.add(email);
  }

  @override
  Future<String> idTokenForReset({required String email, required String password}) async {
    signIns.add('$email|$password');
    if (signInError != null) throw signInError!;
    if (pendingToken != null) return pendingToken!.future;
    return resetToken;
  }

  @override
  Future<void> rotatePassword() {
    rotated++;
    if (rotateHangs) return Completer<void>().future;
    if (rotateError != null) return Future.error(rotateError!);
    return Future.value();
  }
}

/// 서버 대신 쓰는 재설정 — 받은 (증명서, 새 비밀번호)를 적어 둔다.
class FakeReset {
  final calls = <String>[];
  Object? error;

  Future<void> call(String idToken, String newPassword) async {
    calls.add('$idToken|$newPassword');
    if (error != null) throw error!;
  }
}

Future<void> open(WidgetTester tester, PasswordResetScreen screen, {List<bool>? result}) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
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

/// 1단계에서 메일을 보내 2단계로 넘어간다.
Future<void> sendMail(WidgetTester tester) async {
  await tester.tap(find.text('재설정 메일 보내기'));
  await tester.pumpAndSettle();
}

Future<void> typePasswords(WidgetTester tester, String first, String second) async {
  await tester.enterText(find.byKey(PasswordResetScreen.newPasswordField), first);
  await tester.enterText(find.byKey(PasswordResetScreen.confirmPasswordField), second);
  await tester.pump();
}

String fieldText(WidgetTester tester, Key key) => tester.widget<TextField>(find.byKey(key)).controller!.text;

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
    NulbomApi.guardianKey = '';
  });

  group('1단계: 재설정 메일 보내기', () {
    testWidgets('로그인 화면에서 넘겨받은 이메일이 채워져 있고, 보내면 그 이메일로 메일을 보내고 2단계로 간다', (tester) async {
      final proof = FakeResetProof();
      await open(tester, PasswordResetScreen(email: 'kim@example.com', proof: proof, reset: FakeReset().call));

      expect(find.text('비밀번호 찾기'), findsWidgets);
      expect(fieldText(tester, PasswordResetScreen.emailField), 'kim@example.com');
      expect(find.text('비밀번호 바꾸기'), findsNothing);

      await sendMail(tester);

      expect(proof.resetMails, ['kim@example.com']);
      expect(find.text(guide), findsOneWidget);
      expect(find.byKey(PasswordResetScreen.newPasswordField), findsOneWidget);
      expect(find.byKey(PasswordResetScreen.confirmPasswordField), findsOneWidget);
      expect(find.text('비밀번호 바꾸기'), findsOneWidget);
      expect(find.text('메일 다시 보내기'), findsOneWidget);
    });

    testWidgets('앞뒤 공백을 뺀 이메일로 보낸다', (tester) async {
      final proof = FakeResetProof();
      await open(tester, PasswordResetScreen(proof: proof, reset: FakeReset().call));

      await tester.enterText(find.byKey(PasswordResetScreen.emailField), '  lee@example.com ');
      await sendMail(tester);

      expect(proof.resetMails, ['lee@example.com']);
    });

    testWidgets('Firebase 계정이 없는 이메일이면 운영자 문의 문장을 화면 안에 보이고 1단계에 머문다', (tester) async {
      final proof = FakeResetProof()..sendError = const EmailProofException(noResetAccountMessage);
      await open(tester, PasswordResetScreen(email: 'admin@example.com', proof: proof, reset: FakeReset().call));

      await sendMail(tester);

      expect(find.text('이 이메일로는 비밀번호 재설정 메일을 보낼 수 없어요. 운영자에게 문의해 주세요.'), findsOneWidget);
      expect(find.byType(SnackBar), findsNothing);
      expect(find.text('비밀번호 바꾸기'), findsNothing);
      expect(find.text('재설정 메일 보내기'), findsOneWidget);
    });

    testWidgets('이메일이 비어 있으면 메일을 보내지 않는다', (tester) async {
      final proof = FakeResetProof();
      await open(tester, PasswordResetScreen(proof: proof, reset: FakeReset().call));

      await sendMail(tester);

      expect(proof.resetMails, isEmpty);
      expect(find.text('이메일을 입력해 주세요.'), findsOneWidget);
    });
  });

  group('2단계: 새 비밀번호', () {
    testWidgets('확인 칸이 다르면 입력하는 동안 바로 알리고, 같아지면 사라진다', (tester) async {
      await open(tester, PasswordResetScreen(email: 'kim@example.com', proof: FakeResetProof(), reset: FakeReset().call));
      await sendMail(tester);

      await tester.enterText(find.byKey(PasswordResetScreen.newPasswordField), newPassword);
      await tester.pump();
      expect(find.text(mismatch), findsNothing); // 확인 칸을 아직 안 쳤다

      await tester.enterText(find.byKey(PasswordResetScreen.confirmPasswordField), 'brand');
      await tester.pump();
      expect(find.text(mismatch), findsOneWidget);

      await tester.enterText(find.byKey(PasswordResetScreen.confirmPasswordField), newPassword);
      await tester.pump();
      expect(find.text(mismatch), findsNothing);

      await tester.enterText(find.byKey(PasswordResetScreen.newPasswordField), 'other-password-2'); // 위 칸을 고쳐도 다시 알린다
      await tester.pump();
      expect(find.text(mismatch), findsOneWidget);
    });

    testWidgets('8자 이상이라는 안내가 보이고, 8자 미만이면 Firebase와 서버를 부르지 않는다', (tester) async {
      final proof = FakeResetProof();
      final reset = FakeReset();
      await open(tester, PasswordResetScreen(email: 'kim@example.com', proof: proof, reset: reset.call));
      await sendMail(tester);
      expect(find.textContaining('8자 이상'), findsWidgets);

      await typePasswords(tester, 'short-7', 'short-7');
      await tester.tap(find.text('비밀번호 바꾸기'));
      await tester.pumpAndSettle();

      expect(find.text(tooShort), findsOneWidget);
      expect(proof.signIns, isEmpty);
      expect(reset.calls, isEmpty);
    });

    testWidgets('두 칸이 다르면 눌러도 Firebase와 서버를 부르지 않는다', (tester) async {
      final proof = FakeResetProof();
      final reset = FakeReset();
      await open(tester, PasswordResetScreen(email: 'kim@example.com', proof: proof, reset: reset.call));
      await sendMail(tester);

      await typePasswords(tester, newPassword, 'brand-new-pass-4');
      await tester.tap(find.text('비밀번호 바꾸기'));
      await tester.pumpAndSettle();

      expect(find.text(mismatch), findsWidgets);
      expect(proof.signIns, isEmpty);
      expect(reset.calls, isEmpty);
    });

    testWidgets('성공: 새 비밀번호로 Firebase 증명서를 받아 서버에 {id_token, new_password}를 보내고 true로 닫힌다', (tester) async {
      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return json({'reset': true});
      });
      final proof = FakeResetProof();
      final result = <bool>[];
      // reset을 주지 않으면 NulbomApi.resetPassword를 쓴다
      await open(tester, PasswordResetScreen(email: 'kim@example.com', proof: proof), result: result);
      await sendMail(tester);

      await typePasswords(tester, newPassword, newPassword);
      await tester.tap(find.text('비밀번호 바꾸기'));
      await tester.pumpAndSettle();

      expect(proof.signIns, ['kim@example.com|$newPassword']);
      expect(seen.url.path, '/v1/guardian/password/reset');
      expect(seen.headers.containsKey('Authorization'), isFalse);
      expect(jsonDecode(seen.body), {'id_token': resetToken, 'new_password': newPassword});
      expect(result, [true]);
      expect(find.byType(PasswordResetScreen), findsNothing);
    });

    testWidgets('서버가 401로 거절하면 서버 문장을 화면 안에 보이고 머문다', (tester) async {
      NulbomApi.client = MockClient((request) async => json({'detail': '비밀번호 재설정을 확인하지 못했어요'}, 401));
      final result = <bool>[];
      await open(tester, PasswordResetScreen(email: 'kim@example.com', proof: FakeResetProof()), result: result);
      await sendMail(tester);

      await typePasswords(tester, newPassword, newPassword);
      await tester.tap(find.text('비밀번호 바꾸기'));
      await tester.pumpAndSettle();

      expect(find.text('비밀번호 재설정을 확인하지 못했어요'), findsOneWidget);
      expect(find.byType(SnackBar), findsNothing);
      expect(find.byType(PasswordResetScreen), findsOneWidget);
      expect(result, isEmpty);
      expect(find.text('비밀번호 바꾸기'), findsOneWidget); // 다시 누를 수 있다
    });

    testWidgets('Firebase 비밀번호가 메일에서 정한 것과 다르면 그 문장을 보이고 서버를 부르지 않는다', (tester) async {
      final proof = FakeResetProof()..signInError = const EmailProofException(resetPasswordMismatchMessage);
      final reset = FakeReset();
      await open(tester, PasswordResetScreen(email: 'kim@example.com', proof: proof, reset: reset.call));
      await sendMail(tester);

      await typePasswords(tester, newPassword, newPassword);
      await tester.tap(find.text('비밀번호 바꾸기'));
      await tester.pumpAndSettle();

      expect(find.text('메일의 링크에서 정한 새 비밀번호와 같게 입력해 주세요.'), findsOneWidget);
      expect(reset.calls, isEmpty);
    });

    testWidgets('예상하지 못한 오류도 화면 안 문장으로 보인다', (tester) async {
      final reset = FakeReset()..error = Exception('boom');
      await open(tester, PasswordResetScreen(email: 'kim@example.com', proof: FakeResetProof(), reset: reset.call));
      await sendMail(tester);

      await typePasswords(tester, newPassword, newPassword);
      await tester.tap(find.text('비밀번호 바꾸기'));
      await tester.pumpAndSettle();

      expect(find.text('비밀번호를 바꾸지 못했어요. 잠시 뒤에 다시 해 주세요.'), findsOneWidget);
      expect(find.textContaining('boom'), findsNothing);
    });

    testWidgets('처리 중에 버튼을 거듭 눌러도 Firebase와 서버는 한 번만 부른다', (tester) async {
      final proof = FakeResetProof()..pendingToken = Completer<String>();
      final reset = FakeReset();
      final result = <bool>[];
      await open(tester, PasswordResetScreen(email: 'kim@example.com', proof: proof, reset: reset.call), result: result);
      await sendMail(tester);
      await typePasswords(tester, newPassword, newPassword);

      // 다시 그리기 전에 두 번(빠른 두 번 탭), 그린 뒤에 한 번 더(버튼이 꺼졌다)
      await tester.tap(find.text('비밀번호 바꾸기'));
      await tester.tap(find.text('비밀번호 바꾸기'));
      await tester.pump();
      await tester.tap(find.text('비밀번호 바꾸기'), warnIfMissed: false);
      await tester.pump();
      await tester.tap(find.text('메일 다시 보내기'), warnIfMissed: false); // 처리 중에는 다른 버튼도 막힌다
      await tester.pump();

      expect(proof.signIns, hasLength(1));
      expect(proof.resetMails, hasLength(1)); // 1단계에서 보낸 한 번뿐

      proof.pendingToken!.complete(resetToken);
      await tester.pumpAndSettle();

      expect(reset.calls, ['$resetToken|$newPassword']);
      expect(result, [true]);
    });

    testWidgets('서버가 바꾸면 Firebase 비밀번호도 아무도 모르는 값으로 한 번 바꾼 뒤 닫힌다', (tester) async {
      final proof = FakeResetProof();
      final reset = FakeReset();
      final result = <bool>[];
      await open(tester, PasswordResetScreen(email: 'kim@example.com', proof: proof, reset: reset.call), result: result);
      await sendMail(tester);

      await typePasswords(tester, newPassword, newPassword);
      await tester.tap(find.text('비밀번호 바꾸기'));
      await tester.pumpAndSettle();

      expect(reset.calls, hasLength(1));
      expect(proof.rotated, 1);
      expect(result, [true]);
    });

    testWidgets('Firebase 비밀번호 바꾸기가 실패하거나 끝나지 않아도 5초 안에 true로 닫힌다', (tester) async {
      final proof = FakeResetProof()..rotateHangs = true;
      final result = <bool>[];
      await open(tester, PasswordResetScreen(email: 'kim@example.com', proof: proof, reset: FakeReset().call),
          result: result);
      await sendMail(tester);

      await typePasswords(tester, newPassword, newPassword);
      await tester.tap(find.text('비밀번호 바꾸기'));
      await tester.pump(const Duration(seconds: 4));
      expect(result, isEmpty);
      await tester.pump(const Duration(seconds: 1));
      await tester.pumpAndSettle();

      expect(proof.rotated, 1);
      expect(result, [true]);
    });

    testWidgets('서버가 거절하거나 Firebase 로그인이 틀리면 Firebase 비밀번호를 바꾸지 않는다', (tester) async {
      final proof = FakeResetProof();
      final reset = FakeReset()..error = const ApiException(401, '비밀번호 재설정을 확인하지 못했어요');
      await open(tester, PasswordResetScreen(email: 'kim@example.com', proof: proof, reset: reset.call));
      await sendMail(tester);
      await typePasswords(tester, newPassword, newPassword);

      await tester.tap(find.text('비밀번호 바꾸기'));
      await tester.pumpAndSettle();
      expect(proof.rotated, 0); // 다시 시도할 때 같은 비밀번호로 Firebase에 들어갈 수 있어야 한다

      proof.signInError = const EmailProofException(resetPasswordMismatchMessage);
      await tester.tap(find.text('비밀번호 바꾸기'));
      await tester.pumpAndSettle();
      expect(proof.rotated, 0);
    });

    testWidgets('메일 다시 보내기는 같은 이메일로 다시 보내고 알린다', (tester) async {
      final proof = FakeResetProof();
      await open(tester, PasswordResetScreen(email: 'kim@example.com', proof: proof, reset: FakeReset().call));
      await sendMail(tester);

      await tester.tap(find.text('메일 다시 보내기'));
      await tester.pumpAndSettle();

      expect(proof.resetMails, ['kim@example.com', 'kim@example.com']);
      expect(find.text('재설정 메일을 다시 보냈어요.'), findsOneWidget);
    });

    testWidgets('뒤로 가면 false로 닫히고 아무것도 부르지 않는다', (tester) async {
      final proof = FakeResetProof();
      final reset = FakeReset();
      final result = <bool>[];
      await open(tester, PasswordResetScreen(email: 'kim@example.com', proof: proof, reset: reset.call), result: result);
      await sendMail(tester);

      await tester.tap(find.byIcon(Icons.arrow_back_rounded));
      await tester.pumpAndSettle();

      expect(result, [false]);
      expect(proof.signIns, isEmpty);
      expect(reset.calls, isEmpty);
    });
  });
}
