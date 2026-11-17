import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';

/// 글을 소리로 읽어 주는 것. 기기 안의 음성 합성(Android TTS)을 쓴다 — 요금도 서버도 필요 없다.
///
/// 테스트에서는 가짜로 바꾼다(실제 음성 엔진은 단위 시험에서 못 쓴다).
abstract class Speaker {
  /// [text]를 [language](예: 'ko-KR', 'en-US')로 읽는다. **다 읽거나 [stop]으로 멈출 때까지 끝나지 않는다.**
  /// 이 기기에서 그 언어의 음성을 쓸 수 없으면 읽지 않고 [SpeakOutcome.unavailable]을 돌려준다.
  Future<SpeakOutcome> speak(String text, {String language = kSpeechLanguage});

  /// 읽던 것을 멈춘다. 읽는 중이 아니어도 안전하다.
  Future<void> stop();
}

enum SpeakOutcome { finished, unavailable }

/// 어르신이 천천히 듣기 편하도록 보통(0.5)보다 느리게 읽는다.
const double kSpeechRate = 0.42;
const String kSpeechLanguage = 'ko-KR';

/// 한국어 음성이 없을 때 어르신께 보이는 안내.
const String kNoKoreanVoice = '이 폰에서는 한국어 음성을 쓸 수 없어요. 가족에게 폰 설정에서 음성 합성을 확인해 달라고 해 주세요.';

/// 번역 언어([languageLabel], 예: "영어")의 음성이 없을 때 보이는 안내.
String noVoiceMessage(String languageLabel) =>
    '이 폰에서는 $languageLabel 음성을 쓸 수 없어요. 번역한 글은 화면에서 읽을 수 있어요.';

class FlutterTtsSpeaker implements Speaker {
  final FlutterTts _tts = FlutterTts();
  final Map<String, bool> _available = {};
  bool _handlersSet = false;
  Completer<void>? _current;

  Future<bool> _prepare(String language) async {
    try {
      var ok = _available[language];
      if (ok == null) {
        final available = await _tts.isLanguageAvailable(language);
        ok = available == true || available == 1;
        // 못 쓴다는 답은 기억하지 않는다 — 설정에서 음성을 설치한 뒤 다시 눌러 보면 새로 확인한다.
        if (ok) _available[language] = true;
      }
      if (!ok) return false;
      await _tts.setLanguage(language);
      await _tts.setSpeechRate(kSpeechRate);
      await _tts.setPitch(1.0);
      if (!_handlersSet) {
        // 끝남·멈춤·오류 중 무엇이 오든 기다리던 speak()를 풀어 준다. 풀리지 않으면 "읽는 중" 표시가 남는다.
        _tts.setCompletionHandler(_release);
        _tts.setCancelHandler(_release);
        _tts.setErrorHandler((_) => _release());
        _handlersSet = true;
      }
      return true;
    } catch (e) {
      debugPrint('음성 합성을 준비하지 못했다: ${e.runtimeType}');
      return false;
    }
  }

  void _release() {
    final current = _current;
    if (current != null && !current.isCompleted) current.complete();
  }

  @override
  Future<SpeakOutcome> speak(String text, {String language = kSpeechLanguage}) async {
    if (!await _prepare(language)) return SpeakOutcome.unavailable;
    _release(); // 앞서 읽던 것이 있으면 기다림을 푼다.
    final done = _current = Completer<void>();
    try {
      await _tts.speak(text);
    } catch (e) {
      debugPrint('음성 읽기를 시작하지 못했다: ${e.runtimeType}');
      _release();
    }
    await done.future;
    return SpeakOutcome.finished;
  }

  @override
  Future<void> stop() async {
    try {
      await _tts.stop();
    } catch (_) {
      // 멈추기가 실패해도 아래에서 기다림은 푼다.
    }
    _release();
  }
}

/// 번역문을 읽을 때 쓰는 번호의 시작. 말풍선 번호에 더해 쓴다 — 원문(번호 그대로)과 번역문이 서로 다른 번호라서
/// 한쪽을 읽는 중에 다른 쪽 버튼이 "멈추기"로 바뀌지 않는다.
const int kTranslationSpeakBase = 100000;

/// 화면 하나의 "소리로 듣기" 상태. **한 번에 하나만** 읽는다.
///
/// 말풍선마다 번호(id)를 주고 [toggle]을 부른다. 읽는 중인 말풍선을 다시 누르면 멈추고,
/// 다른 말풍선을 누르면 앞의 것을 멈추고 새로 읽는다.
class ReadAloud {
  ReadAloud({Speaker? speaker}) : _speaker = speaker;

  Speaker? _speaker;
  int _token = 0;

  /// 지금 읽는 말풍선 번호. 없으면 null.
  final ValueNotifier<int?> speaking = ValueNotifier<int?>(null);

  Speaker get _s => _speaker ??= FlutterTtsSpeaker();

  /// 읽거나 멈춘다. 어르신께 알릴 문장이 있으면 돌려준다(없으면 null).
  /// [language]는 읽을 언어(기본 한국어), [unavailableMessage]는 그 언어 음성이 없을 때 돌려줄 문장이다.
  Future<String?> toggle(
    int id,
    String text, {
    String language = kSpeechLanguage,
    String unavailableMessage = kNoKoreanVoice,
  }) async {
    if (speaking.value == id) {
      await stop();
      return null;
    }
    final token = ++_token;
    speaking.value = id;
    final speaker = _s;
    await speaker.stop(); // 앞에 읽던 것
    if (token != _token) return null; // 기다리는 사이 다른 것을 눌렀거나 멈췄다
    final outcome = await speaker.speak(text, language: language);
    // 내가 시작한 읽기일 때만 표시를 지운다 — 뒤에 누른 다른 말풍선의 표시를 지우면 안 된다.
    if (token == _token) speaking.value = null;
    return outcome == SpeakOutcome.unavailable ? unavailableMessage : null;
  }

  /// 읽던 것을 멈춘다(새 말을 보낼 때, 화면을 나갈 때).
  Future<void> stop() async {
    _token++;
    speaking.value = null;
    await _speaker?.stop(); // 아직 한 번도 안 읽었으면 엔진을 만들지 않는다
  }

  void dispose() {
    _token++;
    _speaker?.stop();
    speaking.dispose();
  }
}
