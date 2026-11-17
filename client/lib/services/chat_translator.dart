import 'package:flutter/foundation.dart';

import 'nulbom_api.dart';

/// 번역한 말풍선을 기억한다. 화면 하나가 하나씩 갖는다.
///
/// 번역문은 서버에 저장되지 않는다 — 화면을 나가면 사라진다. 같은 말풍선을 같은 언어로 다시 누르면
/// 서버를 부르지 않고 여기서 바로 돌려준다.
class ChatTranslator extends ChangeNotifier {
  ChatTranslator({Future<String> Function(String text, String language)? translate})
      : _translate = translate ?? ((text, language) => NulbomApi.translate(text, language: language));

  final Future<String> Function(String text, String language) _translate;
  final Map<String, String> _results = {};
  final Set<String> _pending = {};
  bool _disposed = false;

  static String _key(int id, String language) => '$id|$language';

  /// 그 말풍선의 [language] 번역문. 아직 없으면 null.
  String? resultFor(int id, String language) => _results[_key(id, language)];

  /// 번역을 기다리는 중인가.
  bool isPending(int id, String language) => _pending.contains(_key(id, language));

  /// 번역문을 돌려준다(이미 있으면 서버를 부르지 않는다). 실패하면 예외를 그대로 던진다.
  Future<String> obtain(int id, String text, String language) async {
    final key = _key(id, language);
    final have = _results[key];
    if (have != null) return have;
    _pending.add(key);
    _notify();
    try {
      final translated = await _translate(text, language);
      _results[key] = translated;
      return translated;
    } finally {
      _pending.remove(key);
      _notify();
    }
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
