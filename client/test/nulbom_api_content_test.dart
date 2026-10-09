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

  test('통화 목록: 요약과 원문 유무를 읽는다', () async {
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return json({
        'share_agreed': true,
        'calls': [
          {
            'call_id': 7,
            'started_at': '2026-10-09T09:00:00+09:00',
            'duration_s': 95,
            'status': 'completed',
            'summary': '점심을 드셨어요.',
            'has_turns': true,
          },
          {
            'call_id': 6,
            'started_at': '2026-10-08T09:00:00+09:00',
            'duration_s': null,
            'status': 'no_answer',
            'summary': null,
            'has_turns': false,
          },
        ],
      });
    });

    final result = await NulbomApi.elderCalls(20, key: 'nlb_test', limit: 3);

    expect(seen.method, 'GET');
    expect(seen.url.path, '/v1/elders/20/calls');
    expect(seen.url.queryParameters['limit'], '3');
    expect(seen.headers['Authorization'], 'Bearer nlb_test');
    expect(result.shareAgreed, isTrue);
    expect(result.calls.first.summary, '점심을 드셨어요.');
    expect(result.calls.first.hasTurns, isTrue);
    expect(result.calls.first.durationS, 95);
    expect(result.calls.last.summary, isNull);
    expect(result.calls.last.hasTurns, isFalse);
  });

  test('원문: 말한 사람을 구분해 읽는다', () async {
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return json({
        'call_id': 7,
        'turns': [
          {'speaker': 'ai', 'text': '안녕하세요'},
          {'speaker': 'elder', 'text': '네 안녕하세요'},
        ],
      });
    });

    final turns = await NulbomApi.callTurns(7, key: 'nlb_test');

    expect(seen.url.path, '/v1/calls/7/turns');
    expect(turns.length, 2);
    expect(turns.first.isAi, isTrue);
    expect(turns.last.isAi, isFalse);
    expect(turns.last.text, '네 안녕하세요');
  });

  test('공유 동의: 어르신 열쇠로 POST한다', () async {
    late http.Request seen;
    NulbomApi.client = MockClient((request) async {
      seen = request;
      return json({'share_agreed': true});
    });

    await NulbomApi.agreeShare(key: 'nle_test');

    expect(seen.method, 'POST');
    expect(seen.url.path, '/v1/me/share-consent');
    expect(seen.headers['Authorization'], 'Bearer nle_test');
  });

  test('내 상태: 공유 동의 여부를 읽고, 없으면 동의 전으로 본다', () async {
    NulbomApi.client = MockClient((request) async =>
        json({'status': 'active', 'name': '홍길동', 'share_agreed': true}));
    expect((await NulbomApi.myStatus(key: 'nle_test')).shareAgreed, isTrue);

    NulbomApi.client = MockClient(
        (request) async => json({'status': 'active', 'name': '홍길동'}));
    expect((await NulbomApi.myStatus(key: 'nle_test')).shareAgreed, isFalse);
  });
}
