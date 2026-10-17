import 'dart:async';

import 'package:eldercare/services/email_proof.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter_test/flutter_test.dart';

FirebaseAuthException failure(String code) => FirebaseAuthException(code: code);

/// rotatePassword만 쓰는 가짜. [rotate]가 그 동작을 정한다.
class RotatingProof implements EmailProof {
  RotatingProof(this.rotate);
  final Future<void> Function() rotate;
  int calls = 0;
  final knownPasswords = <String?>[];

  @override
  Future<void> rotatePassword({String? knownPassword}) {
    calls++;
    knownPasswords.add(knownPassword);
    return rotate();
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => throw UnimplementedError();
}

/// Firebase 사용자 가짜 — 다시 로그인·비밀번호 바꾸기 요청만 적어 둔다.
class FakeUser implements User {
  FakeUser({this.email = 'kim@example.com'});

  @override
  final String? email;
  final calls = <String>[];
  EmailAuthCredential? reauthWith;
  String? newPassword;
  Object? reauthError;
  Object? updateError;

  @override
  Future<UserCredential> reauthenticateWithCredential(AuthCredential credential) async {
    calls.add('reauth');
    reauthWith = credential as EmailAuthCredential;
    if (reauthError != null) throw reauthError!;
    return FakeUserCredential();
  }

  @override
  Future<void> updatePassword(String newPassword) async {
    calls.add('update');
    this.newPassword = newPassword;
    if (updateError != null) throw updateError!;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class FakeUserCredential implements UserCredential {
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class FakeAuth implements FirebaseAuth {
  FakeAuth(this.user, {this.brokenApp = false});
  final User? user;
  final bool brokenApp;

  @override
  User? get currentUser {
    if (brokenApp) throw StateError('Firebase가 초기화되지 않았다');
    return user;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  group('FirebaseEmailProof.rotatePassword', () {
    test('아는 비밀번호가 있으면 그 비밀번호로 다시 로그인한 뒤 무작위 40자로 바꾼다', () async {
      final user = FakeUser();

      await FirebaseEmailProof(auth: FakeAuth(user)).rotatePassword(knownPassword: 'correct-horse-1');

      expect(user.calls, ['reauth', 'update']);
      expect(user.reauthWith!.email, 'kim@example.com');
      expect(user.reauthWith!.password, 'correct-horse-1');
      expect(user.newPassword, hasLength(FirebaseEmailProof.rotatedPasswordLength));
      expect(user.newPassword, isNot('correct-horse-1'));
    });

    test('다시 로그인이 실패해도(이미 다른 비밀번호) 바꾸기는 해 보고, 던지지 않는다', () async {
      final user = FakeUser()..reauthError = FirebaseAuthException(code: 'wrong-password');

      await FirebaseEmailProof(auth: FakeAuth(user)).rotatePassword(knownPassword: 'old-password-1');

      expect(user.calls, ['reauth', 'update']);
    });

    test('아는 비밀번호가 없으면(또는 빈 값) 다시 로그인 없이 바꾸기만 해 본다', () async {
      for (final known in [null, '']) {
        final user = FakeUser();

        await FirebaseEmailProof(auth: FakeAuth(user)).rotatePassword(knownPassword: known);

        expect(user.calls, ['update'], reason: '$known');
      }
    });

    test('세션 이메일을 모르면 다시 로그인하지 않는다', () async {
      final user = FakeUser(email: null);

      await FirebaseEmailProof(auth: FakeAuth(user)).rotatePassword(knownPassword: 'correct-horse-1');

      expect(user.calls, ['update']);
    });

    test('바꾸기가 거절돼도(최근 로그인 아님 등) 던지지 않는다', () async {
      final user = FakeUser()..updateError = FirebaseAuthException(code: 'requires-recent-login');

      await FirebaseEmailProof(auth: FakeAuth(user)).rotatePassword(knownPassword: 'correct-horse-1');

      expect(user.calls, ['reauth', 'update']);
    });

    test('세션이 없거나 Firebase가 없으면 아무것도 하지 않고 던지지 않는다', () async {
      await FirebaseEmailProof(auth: FakeAuth(null)).rotatePassword(knownPassword: 'correct-horse-1');
      await FirebaseEmailProof(auth: FakeAuth(null, brokenApp: true)).rotatePassword(knownPassword: 'x' * 8);
    });
  });

  group('Firebase 비밀번호 바꾸기(아무도 모르는 값)', () {
    test('무작위 값은 32자 이상의 영문·숫자이고 매번 다르다', () {
      final values = List.generate(20, (_) => FirebaseEmailProof.newRandomPassword());

      for (final value in values) {
        expect(value.length, greaterThanOrEqualTo(32));
        expect(RegExp(r'^[A-Za-z0-9]+$').hasMatch(value), isTrue, reason: value);
      }
      expect(values.toSet(), hasLength(values.length));
    });

    test('조용히 바꾸기: 성공하면 한 번 부르고 끝난다, 아는 비밀번호를 그대로 넘긴다', () async {
      final proof = RotatingProof(() async {});

      await rotatePasswordQuietly(proof);
      await rotatePasswordQuietly(proof, knownPassword: 'correct-horse-1');

      expect(proof.calls, 2);
      expect(proof.knownPasswords, [null, 'correct-horse-1']);
    });

    test('조용히 바꾸기: 실패해도(바로 던지든 나중에 던지든) 밖으로 내지 않는다', () async {
      await rotatePasswordQuietly(RotatingProof(() => throw StateError('바로')));
      await rotatePasswordQuietly(RotatingProof(() async => throw StateError('나중')));
    });

    testWidgets('조용히 바꾸기: 끝나지 않으면 5초까지만 기다린다', (tester) async {
      var finished = false;
      unawaited(rotatePasswordQuietly(RotatingProof(() => Completer<void>().future)).then((_) => finished = true));

      await tester.pump(const Duration(seconds: 4));
      expect(finished, isFalse);
      await tester.pump(const Duration(seconds: 1));
      expect(finished, isTrue);
      expect(rotatePasswordWait, const Duration(seconds: 5));
    });
  });

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
