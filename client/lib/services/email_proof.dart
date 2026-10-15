import 'package:firebase_auth/firebase_auth.dart';

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
}

class FirebaseEmailProof implements EmailProof {
  /// Firebase가 보내는 인증 메일과 링크 안내 페이지의 언어. 우리 앱은 한국어만 쓴다.
  static const String mailLanguageCode = 'ko';

  FirebaseAuth get _auth => FirebaseAuth.instance;

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

  String _message(FirebaseAuthException e) {
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
}
