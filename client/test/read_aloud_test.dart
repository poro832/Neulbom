import 'dart:async';

import 'package:eldercare/models/nulbom_models.dart';
import 'package:eldercare/screens/ai_chat_screen.dart';
import 'package:eldercare/screens/chat_history.dart';
import 'package:eldercare/screens/chat_widgets.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:eldercare/services/chat_translator.dart';
import 'package:eldercare/services/speaker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 실제 음성 엔진 대신 쓰는 가짜. 읽기는 [finish]나 [stop]이 불릴 때까지 끝나지 않는다.
class FakeSpeaker implements Speaker {
  final List<String> spoken = [];
  final List<String> languages = []; // 읽을 때 요청한 언어
  int stops = 0;
  bool unavailable = false;
  final List<Completer<void>> _open = [];

  @override
  Future<SpeakOutcome> speak(String text, {String language = kSpeechLanguage}) async {
    if (unavailable) return SpeakOutcome.unavailable;
    spoken.add(text);
    languages.add(language);
    final done = Completer<void>();
    _open.add(done);
    await done.future;
    return SpeakOutcome.finished;
  }

  @override
  Future<void> stop() async {
    stops++;
    for (final c in _open) {
      if (!c.isCompleted) c.complete();
    }
    _open.clear();
  }

  /// 소리를 끝까지 다 읽었다.
  void finish() {
    for (final c in List.of(_open)) {
      if (!c.isCompleted) c.complete();
    }
    _open.clear();
  }
}

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
  });

  group('ReadAloud (한 번에 하나만 읽는다)', () {
    test('누르면 읽고 표시가 켜지며, 다 읽으면 꺼진다', () async {
      final speaker = FakeSpeaker();
      final read = ReadAloud(speaker: speaker);

      final result = read.toggle(1, '안녕하세요');
      await Future<void>.delayed(Duration.zero);
      expect(speaker.spoken, ['안녕하세요']);
      expect(read.speaking.value, 1);

      speaker.finish();
      expect(await result, isNull);
      expect(read.speaking.value, isNull);
    });

    test('읽는 말풍선을 다시 누르면 멈춘다', () async {
      final speaker = FakeSpeaker();
      final read = ReadAloud(speaker: speaker);
      unawaited(read.toggle(1, '안녕하세요'));
      await Future<void>.delayed(Duration.zero);

      await read.toggle(1, '안녕하세요');

      expect(read.speaking.value, isNull);
      expect(speaker.spoken.length, 1); // 다시 읽지 않았다
    });

    test('다른 말풍선을 누르면 앞의 것을 멈추고 새로 읽으며, 앞의 끝남이 새 표시를 지우지 않는다', () async {
      final speaker = FakeSpeaker();
      final read = ReadAloud(speaker: speaker);
      unawaited(read.toggle(1, '첫째'));
      await Future<void>.delayed(Duration.zero);

      unawaited(read.toggle(2, '둘째'));
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);

      expect(speaker.spoken, ['첫째', '둘째']);
      expect(read.speaking.value, 2); // 첫째가 멈추며 끝났어도 둘째의 표시는 그대로다
    });

    test('한국어 음성이 없으면 읽지 않고 안내 문장을 돌려주며 표시를 끈다', () async {
      final speaker = FakeSpeaker()..unavailable = true;
      final read = ReadAloud(speaker: speaker);

      final message = await read.toggle(1, '안녕하세요');

      expect(message, kNoKoreanVoice);
      expect(read.speaking.value, isNull);
    });

    test('아직 한 번도 읽지 않았다면 멈추기와 닫기는 음성 엔진을 만들지 않고 안전하다', () async {
      final read = ReadAloud(); // 기본 엔진은 첫 읽기 때 처음 만든다
      await read.stop();
      read.dispose();
    });
  });

  group('어르신 채팅 화면의 스피커', () {
    Future<FakeSpeaker> open(WidgetTester tester, {Future<ChatAnswer> Function(String)? send}) async {
      tester.view.physicalSize = const Size(1000, 2000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      final speaker = FakeSpeaker();
      await tester.pumpWidget(const SizedBox());
      await tester.pumpWidget(MaterialApp(
        home: AiChatScreen(
          friendName: '미소',
          speaker: speaker,
          send: send ?? (_) async => const ChatAnswer(reply: '맑아요.', urgent: false),
        ),
      ));
      await tester.pumpAndSettle();
      return speaker;
    }

    testWidgets('AI 말풍선의 왼쪽 아래에 번역 버튼이 맨 왼쪽, 그 오른쪽에 스피커가 있다', (tester) async {
      await open(tester);

      expect(find.byKey(const Key('speak-0')), findsOneWidget);
      final text = find.textContaining('저는 미소예요');
      final translate = find.byKey(const Key('translate-0'));
      final speaker = find.byKey(const Key('speak-0'));
      expect(tester.getTopLeft(translate).dy, greaterThan(tester.getBottomLeft(text).dy - 1)); // 글 아래
      expect(tester.getTopLeft(translate).dx, closeTo(tester.getTopLeft(text).dx, 1)); // 왼쪽 끝
      expect(tester.getTopLeft(speaker).dx, greaterThan(tester.getTopLeft(translate).dx)); // 번역의 오른쪽
      expect(tester.getTopLeft(speaker).dy, closeTo(tester.getTopLeft(translate).dy, 1)); // 같은 줄
    });

    testWidgets('내가 쓴 말과 오류 문구에는 스피커가 없다', (tester) async {
      await open(tester, send: (_) async => throw const ApiException(503, '지금은 대답하기 어려워요'));

      await tester.enterText(find.byKey(const Key('chat-input')), '안녕');
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pumpAndSettle();

      // 실패하면 쓴 글이 입력창에도 돌아오므로, 말풍선 안에서만 찾는다.
      expect(find.descendant(of: find.byType(ChatBubble), matching: find.text('안녕')), findsOneWidget);
      expect(find.textContaining('대답하기 어려워요'), findsOneWidget);
      expect(find.byIcon(Icons.volume_up_rounded), findsOneWidget); // 인사말 하나뿐
      expect(find.byIcon(Icons.translate_rounded), findsOneWidget);
    });

    testWidgets('스피커를 누르면 그 말풍선을 읽고 멈춤 모양으로 바뀌며, 다시 누르면 멈춘다', (tester) async {
      final fake = await open(tester);

      await tester.tap(find.byKey(const Key('speak-0')));
      await tester.pump();

      expect(fake.spoken.single, contains('저는 미소예요'));
      expect(find.byIcon(Icons.stop_circle_rounded), findsOneWidget);

      await tester.tap(find.byKey(const Key('speak-0')));
      await tester.pump();

      expect(find.byIcon(Icons.stop_circle_rounded), findsNothing);
      expect(find.byIcon(Icons.volume_up_rounded), findsOneWidget);
      expect(fake.spoken.length, 1);
    });

    testWidgets('다 읽으면 스피커 모양으로 돌아온다', (tester) async {
      final fake = await open(tester);
      await tester.tap(find.byKey(const Key('speak-0')));
      await tester.pump();

      fake.finish();
      await tester.pump();

      expect(find.byIcon(Icons.stop_circle_rounded), findsNothing);
    });

    testWidgets('새 말을 보내면 읽던 소리가 멈춘다', (tester) async {
      final fake = await open(tester);
      await tester.tap(find.byKey(const Key('speak-0')));
      await tester.pump();
      final stopsBefore = fake.stops;

      await tester.enterText(find.byKey(const Key('chat-input')), '안녕');
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pumpAndSettle();

      expect(fake.stops, greaterThan(stopsBefore));
      expect(find.byIcon(Icons.stop_circle_rounded), findsNothing);
    });

    testWidgets('한국어 음성이 없으면 안내 문장이 뜬다', (tester) async {
      final fake = await open(tester);
      fake.unavailable = true;

      await tester.tap(find.byKey(const Key('speak-0')));
      await tester.pumpAndSettle();

      expect(find.text(kNoKoreanVoice), findsOneWidget);
    });

    testWidgets('화면을 나가면 읽던 소리가 멈춘다', (tester) async {
      final fake = await open(tester);
      await tester.tap(find.byKey(const Key('speak-0')));
      await tester.pump();
      final stopsBefore = fake.stops;

      await tester.pumpWidget(const SizedBox());

      expect(fake.stops, greaterThan(stopsBefore));
    });

    testWidgets('위급 안내 말풍선에도 스피커가 있어 안내를 소리로 들을 수 있다', (tester) async {
      final fake = await open(tester,
          send: (_) async => const ChatAnswer(reply: '참지 마시고 119에 전화하세요.', urgent: true));

      await tester.enterText(find.byKey(const Key('chat-input')), '가슴이 아파요');
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('speak-2'))); // 인사말, 내 말, 위급 안내 순
      await tester.pump();

      expect(fake.spoken.single, '참지 마시고 119에 전화하세요.');
    });
  });

  group('지난 대화 화면의 스피커', () {
    testWidgets('AI의 말에만 스피커가 있고 누르면 읽는다', (tester) async {
      tester.view.physicalSize = const Size(1000, 2000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      final fake = FakeSpeaker();
      await tester.pumpWidget(MaterialApp(
        home: ChatHistoryScreen(
          session: MyChatSession(sessionId: 7, startedAt: DateTime(2026, 11, 17, 14, 30), preview: '날씨'),
          friendName: '미소',
          speaker: fake,
          load: (_) async => [
            const MyChatMessage(fromElder: true, text: '날씨 어때요?'),
            const MyChatMessage(fromElder: false, text: '맑아요, 산책하기 좋아요.'),
          ],
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.byIcon(Icons.volume_up_rounded), findsOneWidget);
      await tester.tap(find.byKey(const Key('speak-1')));
      await tester.pump();

      expect(fake.spoken.single, '맑아요, 산책하기 좋아요.');
    });
  });

  group('번역', () {
    final translateCalls = <String>[];

    Future<FakeSpeaker> openT(
      WidgetTester tester, {
      Future<String> Function(String text, String language)? translate,
      Map<String, Object> prefs = const {},
    }) async {
      SharedPreferences.setMockInitialValues(prefs);
      translateCalls.clear();
      tester.view.physicalSize = const Size(1000, 2000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      final speaker = FakeSpeaker();
      await tester.pumpWidget(const SizedBox());
      await tester.pumpWidget(MaterialApp(
        home: AiChatScreen(
          friendName: '미소',
          speaker: speaker,
          send: (_) async => const ChatAnswer(reply: '맑아요.', urgent: false),
          translate: translate ??
              (text, language) async {
                translateCalls.add('$language|$text');
                return 'Hello ($language)';
              },
        ),
      ));
      await tester.pumpAndSettle();
      return speaker;
    }

    testWidgets('번역 버튼을 누르면 설정한 언어(기본 영어)로 번역해 말풍선에 보여 주고 그 언어로 읽는다', (tester) async {
      final fake = await openT(tester);

      await tester.tap(find.byKey(const Key('translate-0')));
      await tester.pump();
      await tester.pump();

      expect(translateCalls.single, startsWith('en|안녕하세요, 저는 미소예요.'));
      expect(find.byKey(const Key('chat-translation')), findsOneWidget);
      expect(find.text('영어 번역'), findsOneWidget);
      expect(find.text('Hello (en)'), findsOneWidget);
      expect(fake.spoken.single, 'Hello (en)'); // 한국어 원문이 아니라 번역문을 읽는다
      expect(fake.languages.single, 'en-US');
      expect(find.byIcon(Icons.stop_circle_rounded), findsOneWidget); // 읽는 동안 번역 버튼이 멈춤 모양
    });

    testWidgets('읽는 중 다시 누르면 멈추고, 다 읽은 뒤 누르면 서버를 다시 부르지 않고 다시 읽는다', (tester) async {
      final fake = await openT(tester);
      await tester.tap(find.byKey(const Key('translate-0')));
      await tester.pump();
      await tester.pump();

      await tester.tap(find.byKey(const Key('translate-0'))); // 읽는 중 → 멈춤
      await tester.pump();
      expect(find.byIcon(Icons.stop_circle_rounded), findsNothing);
      expect(fake.spoken.length, 1);

      await tester.tap(find.byKey(const Key('translate-0'))); // 다시 읽기
      await tester.pump();
      await tester.pump();
      expect(fake.spoken.length, 2);
      expect(translateCalls.length, 1); // 번역은 한 번만 했다
    });

    testWidgets('번역을 기다리는 동안 번역 버튼 자리에 빙글빙글이 돈다', (tester) async {
      final answer = Completer<String>();
      await openT(tester, translate: (_, __) => answer.future);

      await tester.tap(find.byKey(const Key('translate-0')));
      await tester.pump();
      expect(find.byKey(const Key('chat-translating')), findsOneWidget);

      answer.complete('Hello');
      await tester.pump();
      await tester.pump();
      expect(find.byKey(const Key('chat-translating')), findsNothing);
      expect(find.text('Hello'), findsOneWidget);
    });

    testWidgets('번역에 실패하면 서버가 준 문장을 알리고 번역문은 보이지 않는다', (tester) async {
      await openT(tester, translate: (_, __) async => throw const ApiException(429, '오늘은 번역을 많이 했어요. 내일 또 해 보세요'));

      await tester.tap(find.byKey(const Key('translate-0')));
      await tester.pumpAndSettle();

      expect(find.text('오늘은 번역을 많이 했어요. 내일 또 해 보세요'), findsOneWidget);
      expect(find.byKey(const Key('chat-translation')), findsNothing);

      await openT(tester, translate: (_, __) async => throw Exception('끊김'));
      await tester.tap(find.byKey(const Key('translate-0')));
      await tester.pumpAndSettle();
      expect(find.textContaining('번역하기 어려워요'), findsOneWidget);
      expect(find.textContaining('끊김'), findsNothing);
    });

    testWidgets('그 언어의 음성이 없어도 번역문은 화면에 남고 안내만 뜬다', (tester) async {
      final fake = await openT(tester);
      fake.unavailable = true;

      await tester.tap(find.byKey(const Key('translate-0')));
      await tester.pumpAndSettle();

      expect(find.text('Hello (en)'), findsOneWidget);
      expect(find.text(noVoiceMessage('영어')), findsOneWidget);
    });

    testWidgets('설정에서 번역 언어를 고르면 저장되고, 그 언어로 번역한다', (tester) async {
      await openT(tester);

      await tester.tap(find.byKey(const Key('chat-font'))); // 설정
      await tester.pumpAndSettle();
      expect(find.text('번역 언어'), findsOneWidget);
      expect(find.descendant(of: find.byKey(const Key('chat-lang-en')), matching: find.byIcon(Icons.check_circle_rounded)),
          findsOneWidget); // 기본은 영어
      await tester.tap(find.byKey(const Key('chat-lang-ja')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('chat-settings-done')));
      await tester.pumpAndSettle();

      expect((await SharedPreferences.getInstance()).getString('chat_translate_language'), 'ja');
      await tester.tap(find.byKey(const Key('translate-0')));
      await tester.pump();
      await tester.pump();
      expect(translateCalls.single, startsWith('ja|'));
      expect(find.text('일본어 번역'), findsOneWidget);
    });

    testWidgets('저장된 번역 언어로 화면이 열린다', (tester) async {
      final fake = await openT(tester, prefs: {'chat_translate_language': 'vi'});

      await tester.tap(find.byKey(const Key('translate-0')));
      await tester.pump();
      await tester.pump();

      expect(translateCalls.single, startsWith('vi|'));
      expect(fake.languages.single, 'vi-VN');
    });

    testWidgets('언어를 바꾸면 앞서 번역해 둔 다른 언어의 번역문은 가려지고, 새 언어로 다시 번역한다', (tester) async {
      await openT(tester);
      await tester.tap(find.byKey(const Key('translate-0')));
      await tester.pump();
      await tester.pump();
      expect(find.text('Hello (en)'), findsOneWidget);

      await tester.tap(find.byKey(const Key('chat-font')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('chat-lang-zh')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('chat-settings-done')));
      await tester.pumpAndSettle();

      expect(find.text('Hello (en)'), findsNothing);
      await tester.tap(find.byKey(const Key('translate-0')));
      await tester.pump();
      await tester.pump();
      expect(translateCalls.last, startsWith('zh|'));
      expect(find.text('Hello (zh)'), findsOneWidget);
    });

    testWidgets('원문을 읽는 중에는 번역 버튼이 멈춤으로 바뀌지 않는다(서로 다른 번호)', (tester) async {
      await openT(tester);
      await tester.tap(find.byKey(const Key('speak-0')));
      await tester.pump();

      expect(find.byIcon(Icons.stop_circle_rounded), findsOneWidget); // 스피커 쪽만
      expect(find.byIcon(Icons.translate_rounded), findsOneWidget);
    });

    testWidgets('지난 대화 화면에서도 번역한다', (tester) async {
      tester.view.physicalSize = const Size(1000, 2000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      final fake = FakeSpeaker();
      await tester.pumpWidget(MaterialApp(
        home: ChatHistoryScreen(
          session: MyChatSession(sessionId: 7, startedAt: DateTime(2026, 11, 17, 14, 30), preview: '날씨'),
          friendName: '미소',
          speaker: fake,
          translate: (text, language) async => 'It is sunny.',
          load: (_) async => [
            const MyChatMessage(fromElder: true, text: '날씨 어때요?'),
            const MyChatMessage(fromElder: false, text: '맑아요, 산책하기 좋아요.'),
          ],
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.byIcon(Icons.translate_rounded), findsOneWidget); // AI의 말에만
      await tester.tap(find.byKey(const Key('translate-1')));
      await tester.pump();
      await tester.pump();

      expect(find.text('It is sunny.'), findsOneWidget);
      expect(fake.spoken.single, 'It is sunny.');
    });
  });

  group('ChatTranslator', () {
    test('같은 말풍선을 같은 언어로 다시 부르면 서버를 다시 부르지 않는다', () async {
      var calls = 0;
      final translator = ChatTranslator(translate: (text, language) async {
        calls++;
        return '$language:$text';
      });

      expect(await translator.obtain(1, '안녕', 'en'), 'en:안녕');
      expect(await translator.obtain(1, '안녕', 'en'), 'en:안녕');
      expect(await translator.obtain(1, '안녕', 'ja'), 'ja:안녕'); // 다른 언어는 새로 번역
      expect(await translator.obtain(2, '안녕', 'en'), 'en:안녕'); // 다른 말풍선도 새로
      expect(calls, 3);
      expect(translator.resultFor(1, 'en'), 'en:안녕');
      expect(translator.resultFor(1, 'vi'), isNull);
      translator.dispose();
    });

    test('실패하면 예외를 그대로 던지고 기다림 표시를 지운다', () async {
      final translator = ChatTranslator(translate: (_, __) async => throw const ApiException(503, '잠시 뒤에'));

      await expectLater(translator.obtain(1, '안녕', 'en'), throwsA(isA<ApiException>()));

      expect(translator.isPending(1, 'en'), isFalse);
      expect(translator.resultFor(1, 'en'), isNull);
      translator.dispose();
    });
  });
}
