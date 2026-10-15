import 'package:eldercare/utils/kst.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('UTC 2026-10-10 16:00은 한국 날짜로 2026-10-11 일요일이다', () {
    final k = kstNow(() => DateTime.utc(2026, 10, 10, 16));

    expect([k.year, k.month, k.day], [2026, 10, 11]);
    expect(k.weekday, DateTime.sunday);
    expect(k.hour, 1);
  });

  test('한국 자정 바로 전은 아직 그 전날이다', () {
    final k = kstNow(() => DateTime.utc(2026, 10, 10, 14, 59));

    expect([k.year, k.month, k.day, k.hour, k.minute], [2026, 10, 10, 23, 59]);
    expect(k.weekday, DateTime.saturday);
  });

  test('폰 시간대의 시각을 받아도 같은 순간의 한국 날짜를 낸다', () {
    final instant = DateTime.utc(2026, 10, 10, 16);

    final fromLocal = kstNow(() => instant.toLocal());

    expect([fromLocal.year, fromLocal.month, fromLocal.day, fromLocal.hour], [2026, 10, 11, 1]);
  });

  test('인자 없이 부르면 지금 시각을 쓴다', () {
    final expected = DateTime.now().toUtc().add(const Duration(hours: 9));

    final k = kstNow();

    expect(k.difference(expected).inSeconds.abs(), lessThan(5));
  });
}
