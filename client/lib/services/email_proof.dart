import 'dart:async';
import 'dart:math';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart' show visibleForTesting;

/// Firebase 비밀번호 바꾸기를 기다리는 최대 시간. 넘으면 기다리지 않고 화면을 닫는다.
const Duration rotatePasswordWait = Duration(seconds: 5);

/// [EmailProof.rotatePassword]를 [rotatePasswordWait]까지만 기다린다. 실패·멈춤 무엇도 밖으로 내지 않는다 —
/// 인증·재설정·변경은 이미 서버에 기록됐고, 이 일은 할 수 있는 만큼만 한다. [knownPassword]는 그대로 넘긴다.
Future<void> rotatePasswordQuietly(EmailProof proof, {String? knownPassword}) async {
  try {
    await proof.rotatePassword(knownPassword: knownPassword).timeout(rotatePasswordWait);
  } catch (_) {}
}

/// 이 이메일의 Firebase 계정이 없을 때(운영 도구로 만든 보호자 등). 운영자가 `guardian set-login`으로 바꿔 준다.
const String noResetAccountMessage = '이 이메일로는 비밀번호 재설정 메일을 보낼 수 없어요. 운영자에게 문의해 주세요.';

/// 앱에 입력한 새 비밀번호가 재설정 메일의 링크에서 정한 것과 다를 때.
const String resetPasswordMismatchMessage = '메일의 링크에서 정한 새 비밀번호와 같게 입력해 주세요.';

const String _resetMailFailed = '비밀번호 재설정 메일을 보내지 못했어요. 운영자에게 문의해 주세요.';
const String _resetCheckFailed = '비밀번호 재설정을 확인하지 못했어요. 잠시 뒤에 다시 해 주세요.';
const String _badEmail = '이메일을 확인해 주세요.';

/// 화면이 Firebase를 직접 부르지 않도록 감싼다 — 화면 테스트는 가짜로 바꾼다.
class EmailProofException implements Exception {
  final String message;
  const EmailProofException(this.message);
  @override
  String toString() => message;
}

abstract class EmailProof {
  /// 이 폰에 Firebase 로그인 세션이 있는가(없으면 재발송에 비밀번호가 필요하다).
  bool get hasSession;

  /// 이 폰의 Firebase 세션 주인 이메일(세션이 없거나 알 수 없으면 null). 같은 폰을 다른
  /// 보호자가 썼다면 앞 사람의 것일 수 있다 — 화면은 자기 이메일과 다르면 세션이 없는 것으로 본다.
  String? get sessionEmail;

  /// 이 폰의 Firebase 세션을 끝낸다(앱에서 로그아웃할 때). Firebase가 없거나 실패해도 던지지 않는다.
  Future<void> signOut();

  /// Firebase 계정을 만들거나(이미 있으면 로그인하고) 인증 메일을 보낸다.
  Future<void> sendVerification({required String email, required String password});

  Future<void> resend();

  /// 메일 링크를 눌러 인증됐으면 서버에 보낼 ID 토큰, 아직이면 null.
  Future<String?> verifiedIdToken();

  /// [email]로 Firebase 비밀번호 재설정 메일(한국어)을 보낸다. 보호자는 메일의 링크에서 새 비밀번호를 정한다.
  /// 이 이메일의 Firebase 계정이 없으면 [noResetAccountMessage]의 [EmailProofException].
  Future<void> sendPasswordReset({required String email});

  /// 메일의 링크에서 정한 새 비밀번호로 Firebase에 로그인해, 서버에 보낼 **방금 받은** ID 토큰을 준다.
  /// 비밀번호가 다르면 [resetPasswordMismatchMessage]의 [EmailProofException]. 비밀번호는 저장하지 않는다.
  Future<String> idTokenForReset({required String email, required String password});

  /// 이 폰에 Firebase 로그인 세션이 있으면 Firebase 비밀번호를 아무도 모르는 무작위 값으로 바꾼다(앱도 기억하지 않는다).
  /// 서버가 이메일 인증·비밀번호 재설정을 받아들인 뒤 부른다. 그 뒤 재설정에 쓸 증명서는 재설정 메일의 링크에서
  /// 새 비밀번호를 정한 사람(메일함 주인)만 얻는다 — 가입·옛 비밀번호를 아는 것만으로는 얻지 못한다.
  /// [knownPassword]는 부르는 화면이 아는 지금의 Firebase 비밀번호(가입·입력한 비밀번호, 재설정에서 방금 정한 것,
  /// 앱 안 변경의 옛 비밀번호)다. 주면 먼저 그것으로 다시 로그인해 "최근 로그인"을 채운다 — 오래된 세션이면 Firebase가
  /// 바꾸기를 거절하기 때문이다. 다시 로그인이 실패해도 바꾸기는 해 본다.
  /// 할 수 있는 만큼만 한다: 세션이 없거나 실패해도 던지지 않는다. 부르는 쪽은 [rotatePasswordQuietly]를 쓴다.
  Future<void> rotatePassword({String? knownPassword});
}

class FirebaseEmailProof implements EmailProof {
  /// Firebase가 보내는 인증 메일과 링크 안내 페이지의 언어. 우리 앱은 한국어만 쓴다.
  static const String mailLanguageCode = 'ko';

  /// 바꾼 Firebase 비밀번호의 길이와 글자(영문 대소문자·숫자 62가지, 40자 ≈ 238비트).
  static const int rotatedPasswordLength = 40;
  static const String _rotatedPasswordChars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';

  /// [auth]는 시험용이다. 없으면 앱의 [FirebaseAuth.instance]를 쓴다(쓸 때 처음 찾는다 — 만들 때는 Firebase가 없어도 된다).
  FirebaseEmailProof({FirebaseAuth? auth}) : _injectedAuth = auth;

  final FirebaseAuth? _injectedAuth;

  FirebaseAuth get _auth => _injectedAuth ?? FirebaseAuth.instance;

  @override
  bool get hasSession => _auth.currentUser != null;

  @override
  String? get sessionEmail {
    try {
      return _auth.currentUser?.email;
    } catch (_) {
      return null; // Firebase가 초기화되지 않은 폰
    }
  }

  @override
  Future<void> signOut() async {
    try {
      await _auth.signOut();
    } catch (_) {
      // Firebase가 초기화되지 않았거나 세션이 이미 없다 — 앱 로그아웃은 그대로 끝난다.
    }
  }

  static String _message(FirebaseAuthException e) {
    switch (e.code) {
      case 'too-many-requests':
        return '요청이 많아요. 잠시 뒤에 다시 해 주세요.';
      case 'wrong-password':
      case 'invalid-credential':
        return '비밀번호를 확인해 주세요.';
      case 'network-request-failed':
        return '인터넷 연결을 확인해 주세요.';
      case 'operation-not-allowed':
        return '이메일 인증을 아직 쓸 수 없어요. 운영자에게 문의해 주세요.';
      default:
        return '인증 메일을 보내지 못했어요. 운영자에게 문의해 주세요.';
    }
  }

  @override
  Future<void> sendVerification({required String email, required String password}) async {
    try {
      await _auth.setLanguageCode(mailLanguageCode);
      UserCredential credential;
      try {
        credential = await _auth.createUserWithEmailAndPassword(email: email, password: password);
      } on FirebaseAuthException catch (e) {
        if (e.code != 'email-already-in-use') rethrow;
        credential = await _auth.signInWithEmailAndPassword(email: email, password: password);
      }
      await credential.user?.sendEmailVerification();
    } on FirebaseAuthException catch (e) {
      throw EmailProofException(_message(e));
    }
  }

  @override
  Future<void> resend() async {
    final user = _auth.currentUser;
    if (user == null) throw const EmailProofException('다시 로그인이 필요해요.');
    try {
      await _auth.setLanguageCode(mailLanguageCode);
      await user.sendEmailVerification();
    } on FirebaseAuthException catch (e) {
      throw EmailProofException(_message(e));
    }
  }

  @override
  Future<String?> verifiedIdToken() async {
    final user = _auth.currentUser;
    if (user == null) return null;
    try {
      await user.reload();
      final fresh = _auth.currentUser;
      if (fresh == null || !fresh.emailVerified) return null;
      return await fresh.getIdToken(true);
    } on FirebaseAuthException catch (e) {
      throw EmailProofException(_message(e));
    }
  }

  /// 재설정 메일 보내기의 오류 문장.
  @visibleForTesting
  static String resetMailMessage(FirebaseAuthException e) {
    switch (e.code) {
      case 'user-not-found':
        return noResetAccountMessage;
      case 'invalid-email':
        return _badEmail;
      case 'too-many-requests':
      case 'network-request-failed':
      case 'operation-not-allowed':
        return _message(e);
      default:
        return _resetMailFailed;
    }
  }

  /// 새 비밀번호로 Firebase에 로그인할 때의 오류 문장.
  @visibleForTesting
  static String resetSignInMessage(FirebaseAuthException e) {
    switch (e.code) {
      case 'wrong-password':
      case 'invalid-credential':
        return resetPasswordMismatchMessage;
      case 'user-not-found':
        return noResetAccountMessage;
      case 'invalid-email':
        return _badEmail;
      case 'too-many-requests':
      case 'network-request-failed':
        return _message(e);
      default:
        return _resetCheckFailed;
    }
  }

  @override
  Future<void> sendPasswordReset({required String email}) async {
    try {
      await _auth.setLanguageCode(mailLanguageCode);
      await _auth.sendPasswordResetEmail(email: email);
    } on FirebaseAuthException catch (e) {
      throw EmailProofException(resetMailMessage(e));
    }
  }

  @override
  Future<String> idTokenForReset({required String email, required String password}) async {
    try {
      // 새로 로그인해야 토큰의 로그인 시각(auth_time)이 지금이 된다 — 서버는 5분이 지난 로그인을 받지 않는다.
      final credential = await _auth.signInWithEmailAndPassword(email: email, password: password);
      final token = await credential.user?.getIdToken(true);
      if (token == null || token.isEmpty) throw const EmailProofException(_resetCheckFailed);
      return token;
    } on FirebaseAuthException catch (e) {
      throw EmailProofException(resetSignInMessage(e));
    }
  }

  /// 아무도 모르는 Firebase 비밀번호. 암호학적 난수([Random.secure])로 고른다.
  @visibleForTesting
  static String newRandomPassword() {
    final random = Random.secure();
    return String.fromCharCodes(List.generate(
      rotatedPasswordLength,
      (_) => _rotatedPasswordChars.codeUnitAt(random.nextInt(_rotatedPasswordChars.length)),
    ));
  }

  @override
  Future<void> rotatePassword({String? knownPassword}) async {
    try {
      final user = _auth.currentUser;
      if (user == null) return;
      final email = user.email;
      if (knownPassword != null && knownPassword.isNotEmpty && email != null && email.isNotEmpty) {
        try {
          await user.reauthenticateWithCredential(
            EmailAuthProvider.credential(email: email, password: knownPassword),
          );
        } catch (_) {
          // Firebase 비밀번호가 이미 다른 값이면 여기서 실패한다. 세션이 최근이면 바꾸기는 그래도 된다.
        }
      }
      // 새 값은 이 호출 안에만 있다 — 저장·기록하지 않고, 오류 문장에도 싣지 않는다.
      await user.updatePassword(newRandomPassword());
    } catch (_) {
      // 할 수 있는 만큼만 한다(로그인이 오래돼 거절, Firebase 미초기화, 인터넷 끊김 등). 서버 쪽 일은 이미 끝났다.
    }
  }
}

/// 서버가 계정을 지운 뒤 Firebase 쪽 계정을 기다리는 최대 시간.
const Duration deleteFirebaseAccountWait = Duration(seconds: 6);

/// 서버에서 보호자 계정을 지운 뒤 같은 이메일의 Firebase 계정도 최선으로 지운다(서버에는 Firebase 관리자 권한이 없다).
/// 이 폰에 그 보호자의 Firebase 세션이 있으면 그것으로, 없으면 [email]과 [knownPassword]로 로그인해 지운다.
/// 인증을 마친 계정은 Firebase 비밀번호를 아무도 모르는 값으로 바꿔 두기 때문에 로그인이 실패해 계정이 남을 수 있다 —
/// 그때는 Firebase 콘솔에서 지운다. 다른 사람의 세션은 건드리지 않고, 실패·멈춤은 밖으로 내지 않는다.
Future<void> deleteFirebaseAccountQuietly({
  String? knownPassword,
  String? email,
  FirebaseAuth? auth,
}) async {
  try {
    await _deleteFirebaseAccount(auth ?? FirebaseAuth.instance, knownPassword, email)
        .timeout(deleteFirebaseAccountWait);
  } catch (_) {}
}

Future<void> _deleteFirebaseAccount(FirebaseAuth auth, String? password, String? email) async {
  var user = auth.currentUser;
  if (user != null && email != null && (user.email ?? '').toLowerCase() != email.toLowerCase()) {
    return; // 다른 사람의 세션이다.
  }
  if (user == null) {
    if (email == null || password == null || password.isEmpty) return;
    user = (await auth.signInWithEmailAndPassword(email: email, password: password)).user;
  } else if (password != null && password.isNotEmpty && user.email != null) {
    try {
      await user.reauthenticateWithCredential(
          EmailAuthProvider.credential(email: user.email!, password: password));
    } catch (_) {}
  }
  await user?.delete();
}
