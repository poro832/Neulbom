import 'dart:convert';

import 'package:eldercare/screens/guardian_account_screen.dart';
import 'package:eldercare/screens/guardian_login_screen.dart';
import 'package:eldercare/screens/guardian_signup_screen.dart';
import 'package:eldercare/services/auth_service.dart';
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
  tearDown(() => NulbomApi.guardianKey = '');

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
