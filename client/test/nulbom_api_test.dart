import 'dart:convert';

import 'package:eldercare/models/nulbom_models.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Response json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('보호자 어르신 목록: 열쇠를 Bearer로 실어 보낸다', () async {
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return json({
        'week_start': '2026-10-04',
        'elders': [
          {
            'elder_id': 12,
            'name': '어르신 12',
            'last_call_at': null,
            'last_status': null,
            'week_calls': 0,
            'week_avg_score': null,
            'week_alerts': 0,
          }
        ],
      });
    });

    final elders = await NulbomApi.guardianElders(key: 'nlb_test');

    expect(elders.single.name, '어르신 12');
    expect(seen.headers['Authorization'], 'Bearer nlb_test');
    expect(seen.url.path, '/v1/guardian/elders');
  });

  test('열쇠가 없으면 서버를 부르지 않고 401 예외를 낸다', () async {
    var called = false;
    NulbomApi.client = MockClient((request) async {
      called = true;
      return json({});
    });

    await expectLater(
      NulbomApi.myCalls(),
      throwsA(isA<ApiException>().having((e) => e.statusCode, 'status', 401)),
    );
    expect(called, isFalse);
  });

  test('서버의 거절 문구를 그대로 예외 메시지로 쓴다', () async {
    NulbomApi.client = MockClient((request) async => json({'detail': '연결 코드를 확인해 주세요'}, 401));

    await expectLater(
      NulbomApi.pair(code: '123456', phone: '070-1111-2222'),
      throwsA(isA<ApiException>().having((e) => e.message, 'message', '연결 코드를 확인해 주세요')),
    );
    expect(await NulbomApi.elderKey(), isNull);
  });

  test('연결에 성공하면 어르신 열쇠를 폰에 저장한다', () async {
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return json({'elder_key': 'nle_abc', 'elder_name': '어르신 12'});
    });

    final result = await NulbomApi.pair(code: '000123', phone: '070-1111-2222');

    expect(result.elderName, '어르신 12');
    expect(await NulbomApi.elderKey(), 'nle_abc');
    expect(jsonDecode(seen.body), {'code': '000123', 'phone': '070-1111-2222'});
  });

  test('저장된 어르신 열쇠로 내 통화 기록을 읽는다', () async {
    SharedPreferences.setMockInitialValues({'elder_key': 'nle_saved'});
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return json({
        'calls': [
          {'call_id': 1, 'started_at': '2026-10-05T09:00:00+09:00', 'duration_s': 52, 'status': 'completed'}
        ]
      });
    });

    final calls = await NulbomApi.myCalls();

    expect(calls.single.durationS, 52);
    expect(seen.headers['Authorization'], 'Bearer nle_saved');
  });

  test('연락처 추가와 삭제', () async {
    SharedPreferences.setMockInitialValues({'elder_key': 'nle_saved'});
    final methods = <String>[];
    NulbomApi.client = MockClient((request) async {
      methods.add('${request.method} ${request.url.path}');
      if (request.method == 'DELETE') return http.Response('', 204);
      return json({'contact_id': 7, 'name': '이웃', 'relation': '이웃', 'phone': '010-1'}, 201);
    });

    final added = await NulbomApi.addContact(name: '이웃', relation: '이웃', phone: '010-1');
    await NulbomApi.deleteContact(added.contactId);

    expect(methods, ['POST /v1/me/contacts', 'DELETE /v1/me/contacts/7']);
  });

  test('연결 코드 발급은 코드를 문자열로 받는다', () async {
    NulbomApi.client = MockClient(
        (request) async => json({'code': '000123', 'expires_at': '2026-10-09T09:00:00+09:00'}));

    final code = await NulbomApi.issuePairingCode(12, key: 'nlb_test');

    expect(code.code, '000123');
  });

  test('가입: 본문을 보내고 어르신 열쇠를 폰에 저장한다', () async {
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return json({'elder_key': 'nle_new', 'status': 'pending'});
    });

    final result = await NulbomApi.signup(
      code: '00001234',
      name: '홍길동',
      phone: '010-9999-1111',
      agreed: true,
    );

    expect(result.status, 'pending');
    expect(await NulbomApi.elderKey(), 'nle_new');
    expect(seen.url.path, '/v1/signup');
    expect(jsonDecode(seen.body), {
      'code': '00001234',
      'name': '홍길동',
      'phone': '010-9999-1111',
      'agreed': true,
    });
  });

  test('가입이 거절되면 서버 문장을 보여 주고 열쇠를 저장하지 않는다', () async {
    NulbomApi.client =
        MockClient((request) async => json({'detail': '가입 코드를 확인해 주세요'}, 401));

    await expectLater(
      NulbomApi.signup(code: '12345678', name: '가', phone: '010-1234-5678', agreed: true),
      throwsA(isA<ApiException>().having((e) => e.message, 'message', '가입 코드를 확인해 주세요')),
    );
    expect(await NulbomApi.elderKey(), isNull);
  });

  test('내 상태는 저장된 어르신 열쇠로 읽는다', () async {
    SharedPreferences.setMockInitialValues({'elder_key': 'nle_saved'});
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return json({'status': 'pending', 'name': '홍길동'});
    });

    final me = await NulbomApi.myStatus();

    expect(me.status, 'pending');
    expect(seen.headers['Authorization'], 'Bearer nle_saved');
    expect(seen.url.path, '/v1/me/status');
  });

  test('보호자: 개인 코드 발급, 승인, 거절', () async {
    final calls = <String>[];
    NulbomApi.client = MockClient((request) async {
      calls.add('${request.method} ${request.url.path}');
      if (request.url.path == '/v1/guardian/invite') return json({'code': '00001234'});
      return json({'status': 'ok'});
    });

    final code = await NulbomApi.issueInvite(key: 'nlb_test');
    await NulbomApi.approveElder(20, key: 'nlb_test');
    await NulbomApi.rejectElder(21, key: 'nlb_test');

    expect(code.code, '00001234');
    expect(calls, [
      'POST /v1/guardian/invite',
      'POST /v1/elders/20/approve',
      'POST /v1/elders/21/reject',
    ]);
  });

  test('어르신 먼저 가입: 본문을 보내고 어르신 열쇠를 저장한다', () async {
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return json({'elder_key': 'nle_first', 'status': 'unlinked'});
    });

    final result = await NulbomApi.elderSignup(name: '홍길동', phone: '010-9999-1111', agreed: true);

    expect(result.status, 'unlinked');
    expect(await NulbomApi.elderKey(), 'nle_first');
    expect(seen.url.path, '/v1/elders/signup');
    expect(jsonDecode(seen.body), {'name': '홍길동', 'phone': '010-9999-1111', 'agreed': true});
  });

  test('연결 코드: 어르신이 발급하고 보호자가 미리보기 후 연결한다', () async {
    SharedPreferences.setMockInitialValues({'elder_key': 'nle_saved'});
    final calls = <String>[];
    final auth = <String?>[];
    NulbomApi.client = MockClient((request) async {
      calls.add('${request.method} ${request.url.path}');
      auth.add(request.headers['Authorization']);
      switch (request.url.path) {
        case '/v1/me/link-code':
          return json({'code': '00001234', 'expires_at': '2026-10-15T09:00:00+09:00'});
        case '/v1/guardian/link/preview':
          return json({'name': '홍길동', 'phone_masked': '010-****-1111'});
        default:
          return json({'elder_id': 7, 'name': '홍길동', 'status': 'active'});
      }
    });

    final issued = await NulbomApi.issueLinkCode();
    final preview = await NulbomApi.previewLink('00001234', key: 'nlb_test');
    final linked = await NulbomApi.linkElder('00001234', key: 'nlb_test');

    expect(issued.code, '00001234');
    expect(preview.name, '홍길동');
    expect(preview.phoneMasked, '010-****-1111');
    expect(linked.elderId, 7);
    expect(calls, ['POST /v1/me/link-code', 'POST /v1/guardian/link/preview', 'POST /v1/guardian/link']);
    expect(auth, ['Bearer nle_saved', 'Bearer nlb_test', 'Bearer nlb_test']);
  });

  group('연결 코드 401은 보호자 열쇠를 지우지 않는다', () {
    Future<void> arrange(Map<String, String> body) async {
      await NulbomApi.saveGuardianKey('nlb_test');
      NulbomApi.client = MockClient((request) async => json(body, 401));
    }

    test('previewLink: 틀린 코드', () async {
      var rejected = 0;
      NulbomApi.onGuardianKeyRejected = () => rejected++;
      addTearDown(() => NulbomApi.onGuardianKeyRejected = null);
      await arrange({'detail': '연결 코드를 확인해 주세요'});

      await expectLater(
        NulbomApi.previewLink('00000000'),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', '연결 코드를 확인해 주세요')),
      );
      await Future<void>.delayed(Duration.zero);
      expect(NulbomApi.guardianKey, 'nlb_test');
      expect(await NulbomApi.loadGuardianKey(), 'nlb_test');
      expect(rejected, 0);
    });

    test('linkElder: 틀린 코드', () async {
      var rejected = 0;
      NulbomApi.onGuardianKeyRejected = () => rejected++;
      addTearDown(() => NulbomApi.onGuardianKeyRejected = null);
      await arrange({'detail': '연결 코드를 확인해 주세요'});

      await expectLater(
        NulbomApi.linkElder('00000000'),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', '연결 코드를 확인해 주세요')),
      );
      await Future<void>.delayed(Duration.zero);
      expect(await NulbomApi.loadGuardianKey(), 'nlb_test');
      expect(rejected, 0);
    });

    test('previewLink: 다른 401은 열쇠 거절이다', () async {
      var rejected = 0;
      NulbomApi.onGuardianKeyRejected = () => rejected++;
      addTearDown(() => NulbomApi.onGuardianKeyRejected = null);
      await arrange({'detail': '로그인이 필요해요'});

      await expectLater(NulbomApi.previewLink('00000000'), throwsA(isA<ApiException>()));
      await Future<void>.delayed(Duration.zero);
      expect(NulbomApi.guardianKey, '');
      expect(await NulbomApi.loadGuardianKey(), '');
      expect(rejected, 1);
    });
  });

  test('이메일 인증: 증명서를 보내고 결과를 읽는다', () async {
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return json({'email_verified': true});
    });

    final ok = await NulbomApi.verifyEmail('t' * 40, key: 'nlb_test');

    expect(ok, isTrue);
    expect(seen.url.path, '/v1/guardian/email/verify');
    expect(seen.headers['Authorization'], 'Bearer nlb_test');
    expect(jsonDecode(seen.body), {'id_token': 't' * 40});
  });

  test('이메일 인증이 거절되면 서버 문장을 예외로 내고 열쇠는 지우지 않는다', () async {
    var rejected = 0;
    NulbomApi.onGuardianKeyRejected = () => rejected++;
    addTearDown(() => NulbomApi.onGuardianKeyRejected = null);
    await NulbomApi.saveGuardianKey('nlb_test');
    NulbomApi.client =
        MockClient((request) async => json({'detail': '이메일 인증을 확인하지 못했어요'}, 401));

    await expectLater(
      NulbomApi.verifyEmail('t' * 40, key: 'nlb_test'),
      throwsA(isA<ApiException>().having((e) => e.message, 'message', '이메일 인증을 확인하지 못했어요')),
    );
    await Future<void>.delayed(Duration.zero);
    expect(await NulbomApi.loadGuardianKey(), 'nlb_test');
    expect(rejected, 0);
  });

  group('비밀번호 재설정', () {
    test('열쇠 없이 증명서와 새 비밀번호를 보낸다 — 이 폰에 열쇠가 있어도 싣지 않는다', () async {
      await NulbomApi.saveGuardianKey('nlb_saved');
      addTearDown(() => NulbomApi.guardianKey = '');
      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return json({'reset': true});
      });

      await NulbomApi.resetPassword('t' * 40, 'brand-new-pass-3');

      expect(seen.method, 'POST');
      expect(seen.url.path, '/v1/guardian/password/reset');
      expect(seen.headers.containsKey('Authorization'), isFalse);
      expect(seen.headers['Content-Type'], startsWith('application/json'));
      expect(jsonDecode(seen.body), {'id_token': 't' * 40, 'new_password': 'brand-new-pass-3'});
    });

    for (final (status, detail) in [
      (401, '비밀번호 재설정을 확인하지 못했어요'),
      (429, '잠시 뒤에 다시 해 주세요'),
      (503, '이메일 인증을 아직 쓸 수 없어요'),
    ]) {
      test('$status: 서버 문장을 그대로 ApiException.message로 주고 저장된 열쇠는 건드리지 않는다', () async {
        var rejected = 0;
        NulbomApi.onGuardianKeyRejected = () => rejected++;
        addTearDown(() => NulbomApi.onGuardianKeyRejected = null);
        await NulbomApi.saveGuardianKey('nlb_saved');
        addTearDown(() => NulbomApi.guardianKey = '');
        NulbomApi.client = MockClient((request) async => json({'detail': detail}, status));

        await expectLater(
          NulbomApi.resetPassword('t' * 40, 'brand-new-pass-3'),
          throwsA(isA<ApiException>()
              .having((e) => e.statusCode, 'status', status)
              .having((e) => e.message, 'message', detail)),
        );
        await Future<void>.delayed(Duration.zero);
        expect(await NulbomApi.loadGuardianKey(), 'nlb_saved');
        expect(rejected, 0);
      });
    }
  });

  test('보호자 정보: email_verified가 없으면 인증된 것으로 읽는다', () {
    final old = GuardianProfile.fromJson(
        {'name': '가', 'email': 'a@b.co', 'phone': '010', 'activated': true});
    final fresh = GuardianProfile.fromJson(
        {'name': '가', 'email': 'a@b.co', 'phone': '010', 'activated': false, 'email_verified': false});

    expect(old.emailVerified, isTrue);
    expect(fresh.emailVerified, isFalse);
  });

  test('월간 통계: 달을 지정하면 month로 실어 보내고, 없으면 붙이지 않는다', () async {
    final seen = <http.Request>[];
    NulbomApi.client = MockClient((request) async {
      seen.add(request);
      return json({
        'month': '2026-10',
        'days': [
          {'date': '2026-10-01', 'calls': 1, 'avg_score': 40.0}
        ],
        'total_calls': 1,
        'avg_score': 40.0,
        'baseline_calls': 7,
      });
    });

    final m = await NulbomApi.monthly(12, month: '2026-10', key: 'nlb_test');
    await NulbomApi.monthly(12, key: 'nlb_test');

    expect(seen[0].url.path, '/v1/elders/12/monthly');
    expect(seen[0].url.query, 'month=2026-10');
    expect(seen[0].headers['Authorization'], 'Bearer nlb_test');
    expect(seen[1].url.toString(), endsWith('/v1/elders/12/monthly'));
    expect(m.days.single.avgScore, 40.0);
    expect(m.baselineCalls, 7);
  });

  test('월간 통계: 열쇠가 없으면 서버를 부르지 않는다', () async {
    NulbomApi.guardianKey = '';
    var called = false;
    NulbomApi.client = MockClient((request) async {
      called = true;
      return json({});
    });

    await expectLater(
      NulbomApi.monthly(12, month: '2026-10'),
      throwsA(isA<ApiException>().having((e) => e.statusCode, 'status', 401)),
    );
    expect(called, isFalse);
  });

  test('건강·기분 언급: 주를 지정해 읽고 분류별 개수와 어르신 말을 받는다', () async {
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return json({
        'share_agreed': true,
        'week_start': '2026-10-04',
        'categories': [
          {
            'category': 'body',
            'negative': 2,
            'neutral': 1,
            'positive': 0,
            'items': [
              {'call_id': 5, 'date': '2026-10-08T09:00:00+09:00', 'said': 'bad', 'quote': '허리가 아파요'}
            ],
          },
        ],
      });
    });

    final m = await NulbomApi.elderMentions(12, weekStart: '2026-10-04', key: 'nlb_test');

    expect(seen.url.path, '/v1/elders/12/mentions');
    expect(seen.url.queryParameters['week_start'], '2026-10-04');
    expect(seen.headers['Authorization'], 'Bearer nlb_test');
    expect(m.shareAgreed, isTrue);
    expect(m.categories.single.label, '몸이 아프거나 불편함');
    expect(m.categories.single.total, 3);
    expect(m.categories.single.items.single.quote, '허리가 아파요');
  });

  group('안부 전화 시간', () {
    test('읽기: 보호자 열쇠로 GET하고 HH:MM 문자열을 받는다', () async {
      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return json({'call_time': '09:00'});
      });

      final value = await NulbomApi.callTime(12, key: 'nlb_test');

      expect(seen.method, 'GET');
      expect(seen.url.path, '/v1/elders/12/call-time');
      expect(seen.headers['Authorization'], 'Bearer nlb_test');
      expect(value, '09:00');
    });

    test('바꾸기: PUT 본문이 {"call_time": "09:30"}이고 서버가 돌려준 값을 준다', () async {
      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return json({'call_time': '09:30'});
      });

      final value = await NulbomApi.setCallTime(12, '09:30', key: 'nlb_test');

      expect(seen.method, 'PUT');
      expect(seen.url.path, '/v1/elders/12/call-time');
      expect(seen.headers['Authorization'], 'Bearer nlb_test');
      expect(seen.headers['Content-Type'], startsWith('application/json'));
      expect(jsonDecode(seen.body), {'call_time': '09:30'});
      expect(value, '09:30');
    });

    for (final (status, detail) in [
      (409, '방금 지난 시간이라 곧바로 전화가 걸릴 수 있어요. 지금보다 나중 시간이나 더 일찍 지난 시간(내일부터 걸려요)을 골라 주세요'),
      (422, '안부 전화 시간은 오전 7시부터 오후 9시까지 30분 단위로 고를 수 있어요'),
      (403, '운영자 확인 후 사용할 수 있어요'),
    ]) {
      test('바꾸기 $status: 서버 문장을 그대로 ApiException.message로 준다', () async {
        NulbomApi.client = MockClient((request) async => json({'detail': detail}, status));

        await expectLater(
          NulbomApi.setCallTime(12, '09:00', key: 'nlb_test'),
          throwsA(isA<ApiException>()
              .having((e) => e.statusCode, 'status', status)
              .having((e) => e.message, 'message', detail)),
        );
      });
    }

    test('열쇠가 없으면 서버를 부르지 않는다', () async {
      var called = false;
      NulbomApi.client = MockClient((request) async {
        called = true;
        return json({'call_time': '09:00'});
      });

      await expectLater(NulbomApi.callTime(12), throwsA(isA<ApiException>()));
      await expectLater(NulbomApi.setCallTime(12, '09:30'), throwsA(isA<ApiException>()));
      expect(called, isFalse);
    });
  });
}
