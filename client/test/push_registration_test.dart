import 'dart:async';
import 'dart:convert';

import 'package:eldercare/services/auth_service.dart';
import 'package:eldercare/services/email_proof.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:eldercare/services/push_registration.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

class FakeSource implements PushTokenSource {
  FakeSource(this.token, {this.throws = false});
  final String? token;
  final bool throws;
  final refresh = StreamController<String>.broadcast();
  int asked = 0;

  @override
  Future<String?> getToken() async {
    asked++;
    if (throws) throw StateError('Firebase 없음');
    return token;
  }

  @override
  Stream<String> get onTokenRefresh => refresh.stream;
}

class QuietProof implements EmailProof {
  @override
  dynamic noSuchMethod(Invocation invocation) => Future<void>.value();
}

void main() {
  late List<http.Request> seen;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await PushRegistration.resetForTest();
    NulbomApi.guardianKey = '';
    seen = [];
    NulbomApi.client = MockClient((request) async {
      seen.add(request);
      return http.Response('', 204);
    });
  });

  tearDown(() async {
    await PushRegistration.resetForTest();
    NulbomApi.guardianKey = '';
  });

  test('열쇠가 없으면(어르신 폰 포함) 등록하지 않는다', () async {
    final source = FakeSource('tok-1');
    PushRegistration.source = source;

    await PushRegistration.registerIfGuardian();

    expect(seen, isEmpty);
    expect(source.asked, 0);
  });

  test('보호자 열쇠가 있으면 토큰을 등록한다', () async {
    NulbomApi.guardianKey = 'nlb_g';
    PushRegistration.source = FakeSource('tok-1');

    await PushRegistration.registerIfGuardian();

    expect(seen, hasLength(1));
    expect(seen.single.url.path, '/v1/guardian/devices');
    expect(seen.single.headers['Authorization'], 'Bearer nlb_g');
    expect(jsonDecode(seen.single.body), {'token': 'tok-1'});
  });

  test('서버가 403을 주어도 던지지 않고 넘어간다', () async {
    NulbomApi.guardianKey = 'nlb_g';
    PushRegistration.source = FakeSource('tok-1');
    NulbomApi.client = MockClient((r) async =>
        http.Response(jsonEncode({'detail': '이메일 인증이 필요해요'}), 403, headers: {'content-type': 'application/json'}));

    await PushRegistration.registerIfGuardian();
  });

  test('네트워크 예외와 토큰 소스 예외도 삼킨다', () async {
    NulbomApi.guardianKey = 'nlb_g';
    PushRegistration.source = FakeSource('tok-1');
    NulbomApi.client = MockClient((r) async => throw http.ClientException('down'));
    await PushRegistration.registerIfGuardian();

    PushRegistration.source = FakeSource(null, throws: true);
    await PushRegistration.registerIfGuardian();

    PushRegistration.source = null;
    await PushRegistration.registerIfGuardian();
  });

  test('토큰 갱신도 같은 등록을 부른다', () async {
    NulbomApi.guardianKey = 'nlb_g';
    final source = FakeSource('tok-1');
    PushRegistration.source = source;
    PushRegistration.listenToRefresh();
    PushRegistration.listenToRefresh(); // 두 번 걸리지 않는다

    source.refresh.add('tok-2');
    await Future<void>.delayed(Duration.zero);
    await Future<void>.delayed(Duration.zero);

    expect(seen, hasLength(1));
    expect(jsonDecode(seen.single.body), {'token': 'tok-2'});
  });

  test('로그아웃은 해제를 먼저 부르고, 그 뒤 로그아웃·키 정리가 이어진다', () async {
    await NulbomApi.saveGuardianKey('nlb_g');
    AuthService.emailProof = QuietProof();
    PushRegistration.source = FakeSource('tok-1');
    await PushRegistration.registerIfGuardian();
    seen.clear();

    expect(await AuthService.logout(), isTrue);

    expect(seen.map((r) => r.url.path), ['/v1/guardian/devices/unregister', '/v1/guardian/logout']);
    expect(seen.first.headers['Authorization'], 'Bearer nlb_g');
    expect(jsonDecode(seen.first.body), {'token': 'tok-1'});
    expect(NulbomApi.guardianKey, isEmpty);
    expect(await NulbomApi.loadGuardianKey(), isEmpty);
  });

  test('해제가 실패해도 로그아웃은 끝난다', () async {
    await NulbomApi.saveGuardianKey('nlb_g');
    AuthService.emailProof = QuietProof();
    PushRegistration.source = FakeSource('tok-1');
    NulbomApi.client = MockClient((r) async {
      seen.add(r);
      if (r.url.path.endsWith('unregister')) throw http.ClientException('down');
      return http.Response('', 204);
    });

    expect(await AuthService.logout(), isTrue);

    expect(seen.map((r) => r.url.path), ['/v1/guardian/devices/unregister', '/v1/guardian/logout']);
    expect(await NulbomApi.loadGuardianKey(), isEmpty);
  });

  test('보호자 로그인 성공 직후 등록을 시도한다', () async {
    PushRegistration.source = FakeSource('tok-9');
    NulbomApi.client = MockClient((r) async {
      seen.add(r);
      if (r.url.path == '/v1/guardian/login') {
        return http.Response(
          jsonEncode({
            'key': 'nlb_new',
            'name': '홍',
            'email': 'a@b.c',
            'phone': '010',
            'activated': true,
            'email_verified': true,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      return http.Response('', 204);
    });

    final r = await AuthService.guardianLogin(email: 'a@b.c', password: 'password1');
    await Future<void>.delayed(Duration.zero);
    await Future<void>.delayed(Duration.zero);

    expect(r['success'], isTrue);
    expect(seen.map((x) => x.url.path), contains('/v1/guardian/devices'));
  });
}
