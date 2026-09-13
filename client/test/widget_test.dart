import 'package:eldercare/auth/role.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('저장된 역할 키를 다시 읽어 같은 역할로 복원한다', () {
    for (final role in AppRole.values) {
      expect(AppRole.fromKey(role.key), role);
    }
  });

  test('저장된 값이 없거나 알 수 없으면 null — 역할 선택 화면을 띄운다', () {
    expect(AppRole.fromKey(null), isNull);
    expect(AppRole.fromKey('doctor'), isNull);
  });
}
