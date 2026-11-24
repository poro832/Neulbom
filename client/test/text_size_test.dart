import 'package:eldercare/services/text_size.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<void> _start(Map<String, Object> saved) async {
  SharedPreferences.setMockInitialValues(saved);
  textSizeIndex.value = 99; // 이전 테스트의 값이 남아 있어도 불러오기가 다시 정한다
  await loadTextSize();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('4단계와 기본값', () {
    expect(textSizeOptions.map((o) => o.label), ['작게', '보통', '크게', '아주 크게']);
    expect(textSizeOptions.map((o) => o.scale), [0.85, 1.0, 1.2, 1.45]);
    expect(textSizeDefaultIndex, 1);
  });

  group('loadTextSize', () {
    test('저장된 값이 없으면 보통', () async {
      await _start({});
      expect(textSizeIndex.value, 1);
    });

    test('저장된 단계를 그대로 쓴다', () async {
      await _start({'app_text_size_index': 3});
      expect(textSizeIndex.value, 3);
    });

    test('범위를 벗어난 값은 보통으로 시작한다', () async {
      await _start({'app_text_size_index': 9});
      expect(textSizeIndex.value, 1);
      await _start({'app_text_size_index': -1});
      expect(textSizeIndex.value, 1);
    });

    test('정수가 아닌 값이 들어 있어도 보통으로 시작한다', () async {
      await _start({'app_text_size_index': 'x'});
      expect(textSizeIndex.value, 1);
    });

    test('옛 채팅 글자 크기만 있으면 같은 번호로 옮겨 온다', () async {
      await _start({'chat_font_size_index': 2});
      expect(textSizeIndex.value, 2);
    });

    test('새 설정과 옛 설정이 둘 다 있으면 새 설정이 우선이다', () async {
      await _start({'app_text_size_index': 0, 'chat_font_size_index': 3});
      expect(textSizeIndex.value, 0);
    });
  });

  group('setTextSize', () {
    test('바꾸고 저장한다', () async {
      await _start({});
      await setTextSize(2);
      expect(textSizeIndex.value, 2);
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getInt('app_text_size_index'), 2);
    });

    test('범위를 벗어나면 무시한다', () async {
      await _start({'app_text_size_index': 3});
      await setTextSize(7);
      await setTextSize(-1);
      expect(textSizeIndex.value, 3);
    });

    test('바꾸면 지켜보던 쪽에 알린다', () async {
      await _start({});
      var told = 0;
      void listener() => told++;
      textSizeIndex.addListener(listener);
      await setTextSize(3);
      textSizeIndex.removeListener(listener);
      expect(told, 1);
    });
  });

  group('effectiveTextScale', () {
    test('단계 배율에 시스템 배율을 곱한다', () {
      expect(effectiveTextScale(1, 1.0), 1.0);
      expect(effectiveTextScale(0, 1.0), 0.85);
      expect(effectiveTextScale(2, 1.5), closeTo(1.8, 1e-9)); // 1.2 × 1.5 = 1.8(상한과 같다)
    });

    test('상한은 1.8배다', () {
      expect(effectiveTextScale(3, 2.0), 1.8);
    });

    test('범위를 벗어난 단계는 보통으로 본다', () {
      expect(effectiveTextScale(9, 1.0), 1.0);
      expect(effectiveTextScale(-3, 1.0), 1.0);
    });
  });
}
