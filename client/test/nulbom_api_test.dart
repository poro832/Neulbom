import 'dart:convert';

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
}
