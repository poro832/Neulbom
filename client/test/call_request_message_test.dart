import 'package:flutter_test/flutter_test.dart';

import 'package:eldercare/services/nulbom_api.dart';

void main() {
  test('거절 이유마다 보호자가 알아볼 말이 나온다', () {
    expect(NulbomApi.callRequestMessage(401), '보호자 열쇠가 없거나 올바르지 않습니다');
    expect(NulbomApi.callRequestMessage(403), '어르신의 동의가 아직 없습니다');
    expect(NulbomApi.callRequestMessage(404), '등록되지 않은 어르신입니다');
    expect(NulbomApi.callRequestMessage(429), '오늘 요청 횟수를 넘었습니다');
  });

  test('모르는 코드는 코드를 그대로 보여 준다', () {
    expect(NulbomApi.callRequestMessage(500), '전화 요청 실패 (500)');
  });
}
