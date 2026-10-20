import 'package:eldercare/utils/korean.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('받침이 있으면 과, 없으면 와', () {
    expect(withWaGwa('엄마'), '엄마와');
    expect(withWaGwa('아들'), '아들과');
    expect(withWaGwa('딸'), '딸과');
    expect(withWaGwa('늘봄이'), '늘봄이와');
    expect(withWaGwa('김순자'), '김순자와');
    expect(withWaGwa('할머니'), '할머니와');
    expect(withWaGwa('손자'), '손자와');
    expect(withWaGwa('아버님'), '아버님과');
  });

  test('한글이 아닌 끝 글자와 빈 이름', () {
    expect(withWaGwa('Mom'), 'Mom와');
    expect(withWaGwa(' 엄마 '), '엄마와');
    expect(withWaGwa(''), '');
  });
}
