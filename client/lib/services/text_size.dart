import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 앱 전체 글자 크기 — 어르신·보호자 모두 이 기기에서 4단계 중 하나를 고른다.
///
/// 앱 맨 위(main.dart)에서 글자 배율을 한 번 걸기 때문에, 화면마다 정해 둔 글자 크기는 그대로 두고
/// 모든 글자가 같은 비율로 커지고 줄어든다.
class TextSizeOption {
  final String label;
  final double scale;
  const TextSizeOption(this.label, this.scale);
}

const List<TextSizeOption> textSizeOptions = [
  TextSizeOption('작게', 0.85),
  TextSizeOption('보통', 1.0),
  TextSizeOption('크게', 1.2),
  TextSizeOption('아주 크게', 1.45),
];

const int textSizeDefaultIndex = 1;

/// 폰 설정의 글자 크기까지 곱한 최종 배율의 범위. 너무 커지면 화면이 깨진다.
const double _minScale = 0.5;
const double _maxScale = 1.8;

const String _prefKey = 'app_text_size_index';
// 예전에 AI 채팅에만 있던 글자 크기(작게·보통·크게·아주 크게 순서가 같다). 새 설정이 없을 때만 옮겨 온다.
const String _oldChatPrefKey = 'chat_font_size_index';

/// 지금 고른 단계. 바뀌면 앱 맨 위가 다시 그려진다.
final ValueNotifier<int> textSizeIndex = ValueNotifier<int>(textSizeDefaultIndex);

bool _valid(int? index) => index != null && index >= 0 && index < textSizeOptions.length;

/// 저장된 단계를 읽어 [textSizeIndex]에 넣는다. 저장소를 못 읽거나 값이 이상하면 보통으로 시작한다.
Future<void> loadTextSize() async {
  var index = textSizeDefaultIndex;
  try {
    final prefs = await SharedPreferences.getInstance();
    final saved = _readInt(prefs, _prefKey);
    if (_valid(saved)) {
      index = saved!;
    } else if (saved == null) {
      final old = _readInt(prefs, _oldChatPrefKey);
      if (_valid(old)) index = old!;
    }
  } catch (_) {
    // 저장소를 못 읽어도 앱은 기본 크기로 뜬다.
  }
  textSizeIndex.value = index;
}

int? _readInt(SharedPreferences prefs, String key) {
  try {
    return prefs.getInt(key);
  } catch (_) {
    return null; // 정수가 아닌 값이 들어 있으면 없는 것으로 본다.
  }
}

/// 단계를 바꾸고 저장한다. 범위를 벗어난 번호는 무시한다. 저장이 안 되어도 이번 실행에서는 바뀐다.
Future<void> setTextSize(int index) async {
  if (!_valid(index)) return;
  textSizeIndex.value = index;
  try {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_prefKey, index);
  } catch (_) {
    // 저장 실패는 조용히 넘어간다.
  }
}

/// 앱 글자 배율 = 고른 단계 × 폰 시스템 배율, 0.5~1.8배로 제한한다. 범위를 벗어난 단계는 보통으로 본다.
double effectiveTextScale(int index, double systemScale) {
  final option = textSizeOptions[_valid(index) ? index : textSizeDefaultIndex];
  return (option.scale * systemScale).clamp(_minScale, _maxScale).toDouble();
}

/// `MaterialApp.builder`에 그대로 넣는다. 고른 단계가 바뀌면 앱 전체 글자 배율이 바로 바뀐다.
Widget textSizeBuilder(BuildContext context, Widget? child) {
  return ValueListenableBuilder<int>(
    valueListenable: textSizeIndex,
    builder: (context, index, _) {
      final data = MediaQuery.of(context);
      return MediaQuery(
        data: data.copyWith(textScaler: TextScaler.linear(effectiveTextScale(index, data.textScaler.scale(1)))),
        child: child ?? const SizedBox.shrink(),
      );
    },
  );
}
