import 'package:eldercare/services/email_proof.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter_test/flutter_test.dart';

FirebaseAuthException failure(String code) => FirebaseAuthException(code: code);

void main() {
  group('비밀번호 재설정 메일 보내기 오류 문장', () {
    test('Firebase 계정이 없는 이메일은 운영자에게 문의하라고 한다', () {
      expect(FirebaseEmailProof.resetMailMessage(failure('user-not-found')),
          '이 이메일로는 비밀번호 재설정 메일을 보낼 수 없어요. 운영자에게 문의해 주세요.');
      expect(FirebaseEmailProof.resetMailMessage(failure('user-not-found')), noResetAccountMessage);
    });

    test('요청이 많거나 인터넷이 끊기면 다른 Firebase 호출과 같은 문장이다', () {
      expect(FirebaseEmailProof.resetMailMessage(failure('too-many-requests')), '요청이 많아요. 잠시 뒤에 다시 해 주세요.');
      expect(FirebaseEmailProof.resetMailMessage(failure('network-request-failed')), '인터넷 연결을 확인해 주세요.');
    });

    test('형식이 틀린 이메일과 그 밖의 오류', () {
      expect(FirebaseEmailProof.resetMailMessage(failure('invalid-email')), '이메일을 확인해 주세요.');
      expect(FirebaseEmailProof.resetMailMessage(failure('internal-error')),
          '비밀번호 재설정 메일을 보내지 못했어요. 운영자에게 문의해 주세요.');
    });
  });

  group('새 비밀번호로 Firebase 로그인 오류 문장', () {
    test('비밀번호가 다르면 메일의 링크에서 정한 것과 같게 입력하라고 한다', () {
      for (final code in ['wrong-password', 'invalid-credential']) {
        expect(FirebaseEmailProof.resetSignInMessage(failure(code)), '메일의 링크에서 정한 새 비밀번호와 같게 입력해 주세요.',
            reason: code);
        expect(FirebaseEmailProof.resetSignInMessage(failure(code)), resetPasswordMismatchMessage, reason: code);
      }
    });

    test('계정이 없으면 운영자 문의, 요청이 많거나 인터넷이 끊기면 같은 문장', () {
      expect(FirebaseEmailProof.resetSignInMessage(failure('user-not-found')), noResetAccountMessage);
      expect(FirebaseEmailProof.resetSignInMessage(failure('too-many-requests')), '요청이 많아요. 잠시 뒤에 다시 해 주세요.');
      expect(FirebaseEmailProof.resetSignInMessage(failure('network-request-failed')), '인터넷 연결을 확인해 주세요.');
      expect(FirebaseEmailProof.resetSignInMessage(failure('internal-error')),
          '비밀번호 재설정을 확인하지 못했어요. 잠시 뒤에 다시 해 주세요.');
    });
  });
}
