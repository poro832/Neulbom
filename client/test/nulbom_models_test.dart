import 'package:eldercare/models/nulbom_models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('어르신 요약: 통화 없는 어르신은 시각과 점수가 null이다', () {
    final s = ElderSummary.fromJson({
      'elder_id': 13,
      'name': '어르신 13',
      'last_call_at': null,
      'last_status': null,
      'week_calls': 0,
      'week_avg_score': null,
      'week_alerts': 0,
    });
    expect(s.elderId, 13);
    expect(s.lastCallAt, isNull);
    expect(s.weekAvgScore, isNull);
  });

  test('어르신 요약: 정수로 온 점수도 double로 읽는다', () {
    final s = ElderSummary.fromJson({
      'elder_id': 12,
      'name': '어르신 12',
      'last_call_at': '2026-10-07T09:00:00+09:00',
      'last_status': 'completed',
      'week_calls': 2,
      'week_avg_score': 20,
      'week_alerts': 1,
    });
    expect(s.weekAvgScore, 20.0);
    expect(s.lastCallAt!.toUtc().toIso8601String(), '2026-10-07T00:00:00.000Z');
  });

  test('주간 통계: 7일과 합계를 읽는다', () {
    final w = WeeklyStats.fromJson({
      'week_start': '2026-10-04',
      'days': [
        for (var i = 4; i <= 10; i++)
          {'date': '2026-10-${i.toString().padLeft(2, '0')}', 'calls': i == 5 ? 1 : 0, 'avg_score': i == 5 ? 10.0 : null},
      ],
      'total_calls': 1,
      'avg_score': 10.0,
    });
    expect(w.days.length, 7);
    expect(w.days[1].calls, 1);
    expect(w.days[1].avgScore, 10.0);
    expect(w.days[0].avgScore, isNull);
    expect(w.avgScore, 10.0);
  });

  test('알림과 통화 줄과 연락처', () {
    final a = AlertItem.fromJson({
      'alert_id': 1,
      'elder_id': 12,
      'elder_name': '어르신 12',
      'type': 'risk_rise',
      'severity': 'critical',
      'message': '문구',
      'created_at': '2026-10-08T10:00:00+09:00',
    });
    expect(a.type, 'risk_rise');
    final c = AiCall.fromJson({
      'call_id': 1,
      'started_at': '2026-10-05T09:00:00+09:00',
      'duration_s': null,
      'status': 'no_answer',
    });
    expect(c.durationS, isNull);
    final m = MyContacts.fromJson({
      'guardians': [
        {'name': '보호자1', 'relation': '보호자', 'phone': '010-0000-0001'}
      ],
      'contacts': [
        {'contact_id': 3, 'name': '이웃', 'relation': '이웃', 'phone': '010-1'}
      ],
    });
    expect(m.guardians.single.name, '보호자1');
    expect(m.contacts.single.contactId, 3);
  });

  test('연결 결과와 연결 코드', () {
    expect(PairResult.fromJson({'elder_key': 'nle_x', 'elder_name': '어르신'}).elderName, '어르신');
    final p = PairingCode.fromJson({'code': '000123', 'expires_at': '2026-10-09T09:00:00+09:00'});
    expect(p.code, '000123'); // 앞자리 0이 살아 있어야 한다
  });

  test('어르신 요약: 상태가 없으면 활성이고, 승인 대기는 번호가 있다', () {
    final active = ElderSummary.fromJson({
      'elder_id': 12,
      'name': '어르신 12',
      'last_call_at': null,
      'last_status': null,
      'week_calls': 0,
      'week_avg_score': null,
      'week_alerts': 0,
    });
    expect(active.status, 'active');
    expect(active.phone, isNull);

    final pending = ElderSummary.fromJson({
      'elder_id': 20,
      'name': '새 어르신',
      'last_call_at': null,
      'last_status': null,
      'week_calls': 0,
      'week_avg_score': null,
      'week_alerts': 0,
      'status': 'pending',
      'phone': '010-9999-1111',
    });
    expect(pending.status, 'pending');
    expect(pending.phone, '010-9999-1111');
  });

  test('가입 결과, 내 상태, 개인 코드', () {
    expect(SignupResult.fromJson({'elder_key': 'nle_x', 'status': 'pending'}).status, 'pending');
    final me = MyStatus.fromJson({'status': 'active', 'name': '홍길동'});
    expect(me.status, 'active');
    expect(me.name, '홍길동');
    expect(InviteCode.fromJson({'code': '00001234'}).code, '00001234'); // 앞자리 0이 살아 있다
  });
}
