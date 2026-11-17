import 'dart:async';

import 'package:eldercare/models/nulbom_models.dart';
import 'package:eldercare/screens/ai_chat_screen.dart';
import 'package:eldercare/screens/chat_history.dart';
import 'package:eldercare/screens/chat_widgets.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:eldercare/services/speaker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 실제 음성 엔진 대신 쓰는 가짜. 읽기는 [finish]나 [stop]이 불릴 때까지 끝나지 않는다.
class FakeSpeaker implements Speaker {
  final List<String> spoken = [];
  int stops = 0;
  bool unavailable = false;
  final List<Completer<void>> _open = [];

  @override
  Future<SpeakOutcome> speak(String text) async {
    if (unavailable) return SpeakOutcome.unavailable;
    spoken.add(text);
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

    testWidgets('AI 말풍선의 왼쪽 아래에 스피커가 있다', (tester) async {
      await open(tester);

      expect(find.byKey(const Key('speak-0')), findsOneWidget);
      final text = find.textContaining('저는 미소예요');
      final speaker = find.byKey(const Key('speak-0'));
      expect(tester.getTopLeft(speaker).dy, greaterThan(tester.getBottomLeft(text).dy - 1)); // 글 아래
      expect(tester.getTopLeft(speaker).dx, closeTo(tester.getTopLeft(text).dx, 1)); // 왼쪽 끝
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
          fontIndex: 1,
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
}
