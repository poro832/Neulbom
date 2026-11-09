import 'dart:async';
import 'dart:convert';

import 'package:eldercare/models/nulbom_models.dart';
import 'package:eldercare/screens/ai_chat_screen.dart';
import 'package:eldercare/screens/elder_chats_section.dart';
import 'package:eldercare/screens/health_alerts_screen.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Response _json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json; charset=utf-8'});

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
  });

  group('API', () {
    test('sendChat은 어르신 열쇠로 어르신 주소에 말을 보내고 답을 읽는다', () async {
      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return _json({'reply': '맑아요.', 'urgent': false});
      });

      final answer = await NulbomApi.sendChat('날씨 어때요?', key: 'nle_test');

      expect(seen.method, 'POST');
      expect(seen.url.path, '/v1/me/chat');
      expect(seen.headers['Authorization'], 'Bearer nle_test');
      expect(jsonDecode(seen.body), {'message': '날씨 어때요?'});
      expect(answer.reply, '맑아요.');
      expect(answer.urgent, isFalse);
    });

    test('서버가 거절하면 그 문장이 오류 메시지다', () async {
      NulbomApi.client = MockClient((request) async => _json({'detail': '오늘은 이야기를 많이 나눴어요. 내일 또 이야기해요'}, 429));

      await expectLater(
        NulbomApi.sendChat('안녕', key: 'nle_test'),
        throwsA(isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 429)
            .having((e) => e.message, 'message', contains('내일 또'))),
      );
    });

    test('elderChats는 보호자 열쇠로 요약을 읽는다', () async {
      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return _json({
          'share_agreed': true,
          'chats': [
            {'session_id': 3, 'started_at': '2026-11-09T10:00:00+09:00', 'summary': '날씨를 궁금해하셨어요.'}
          ],
        });
      });

      final chats = await NulbomApi.elderChats(12, key: 'nlb_test');

      expect(seen.url.path, '/v1/elders/12/chats');
      expect(seen.headers['Authorization'], 'Bearer nlb_test');
      expect(chats.shareAgreed, isTrue);
      expect(chats.chats.single.summary, '날씨를 궁금해하셨어요.');
    });
  });

  group('어르신 채팅 화면', () {
    Future<void> open(WidgetTester tester, Future<ChatAnswer> Function(String) send) async {
      tester.view.physicalSize = const Size(1000, 2000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      await tester.pumpWidget(MaterialApp(home: AiChatScreen(send: send)));
      await tester.pump();
    }

    testWidgets('인사말과, 위급한 말이 가족에게 알려질 수 있다는 안내를 먼저 보여 준다', (tester) async {
      await open(tester, (_) async => const ChatAnswer(reply: '', urgent: false));

      expect(find.textContaining('저는 늘봄이에요'), findsOneWidget);
      expect(find.byKey(const Key('chat-notice')), findsOneWidget);
      expect(find.textContaining('가족분께 알려질 수 있어요'), findsOneWidget);
    });

    testWidgets('말을 보내면 내 말풍선과 AI의 답이 차례로 보인다', (tester) async {
      String? sent;
      await open(tester, (m) async {
        sent = m;
        return const ChatAnswer(reply: '산책하기 좋은 날이에요.', urgent: false);
      });

      await tester.enterText(find.byKey(const Key('chat-input')), '오늘 날씨 어때요?');
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pumpAndSettle();

      expect(sent, '오늘 날씨 어때요?');
      expect(find.text('오늘 날씨 어때요?'), findsOneWidget);
      expect(find.text('산책하기 좋은 날이에요.'), findsOneWidget);
      expect(find.byKey(const Key('chat-typing')), findsNothing);
    });

    testWidgets('답을 기다리는 동안 입력과 보내기가 막힌다', (tester) async {
      final answer = Completer<ChatAnswer>();
      await open(tester, (_) => answer.future);

      await tester.enterText(find.byKey(const Key('chat-input')), '안녕');
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pump();

      expect(find.byKey(const Key('chat-typing')), findsOneWidget);
      expect(tester.widget<IconButton>(find.byKey(const Key('chat-send'))).onPressed, isNull);
      answer.complete(const ChatAnswer(reply: '네.', urgent: false));
      await tester.pumpAndSettle();
      expect(find.text('네.'), findsOneWidget);
      expect(find.byKey(const Key('chat-typing')), findsNothing);
    });

    testWidgets('빈 말은 보내지 않는다', (tester) async {
      var calls = 0;
      await open(tester, (_) async {
        calls++;
        return const ChatAnswer(reply: 'x', urgent: false);
      });

      await tester.enterText(find.byKey(const Key('chat-input')), '   ');
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pumpAndSettle();

      expect(calls, 0);
    });

    testWidgets('서버가 거절하면 그 문장을 오류 말풍선으로 보인다', (tester) async {
      await open(tester, (_) async => throw const ApiException(503, '지금은 대답하기 어려워요. 잠시 뒤에 다시 해 주세요'));

      await tester.enterText(find.byKey(const Key('chat-input')), '안녕');
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pumpAndSettle();

      expect(find.textContaining('잠시 뒤에 다시 해 주세요'), findsOneWidget);
    });

    testWidgets('예상 밖 오류도 어르신에게는 쉬운 문장으로 보인다', (tester) async {
      await open(tester, (_) async => throw Exception('끊김'));

      await tester.enterText(find.byKey(const Key('chat-input')), '안녕');
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pumpAndSettle();

      expect(find.textContaining('지금은 대답하기 어려워요'), findsOneWidget);
      expect(find.textContaining('끊김'), findsNothing);
    });

    testWidgets('위급한 말의 답에는 안내 문장이 그대로 보인다', (tester) async {
      await open(
        tester,
        (_) async => const ChatAnswer(reply: '많이 불편하시면 참지 마시고 119에 전화하시거나 가족에게 바로 연락해 주세요.', urgent: true),
      );

      await tester.enterText(find.byKey(const Key('chat-input')), '가슴이 아파요');
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pumpAndSettle();

      expect(find.textContaining('119에 전화하시거나'), findsOneWidget);
    });
  });

  group('보호자 AI 채팅 요약 구역', () {
    Future<void> pump(WidgetTester tester, Future<ElderChats> Function(int) fetch) async {
      tester.view.physicalSize = const Size(1200, 3000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: SingleChildScrollView(child: ElderChatsSection(elderId: 12, fetch: fetch))),
      ));
      await tester.pumpAndSettle();
    }

    testWidgets('요약을 최신 순으로 보여 주고 원문은 보이지 않는다고 알린다', (tester) async {
      await pump(
        tester,
        (_) async => ElderChats.fromJson({
          'share_agreed': true,
          'chats': [
            {'session_id': 2, 'started_at': '2026-11-09T14:30:00+09:00', 'summary': '어르신이 점심 메뉴를 궁금해하셨어요.'},
            {'session_id': 1, 'started_at': '2026-11-08T09:00:00+09:00', 'summary': '어르신이 손주 이야기를 하셨어요.'},
          ],
        }),
      );

      expect(find.text('AI 채팅 요약'), findsOneWidget);
      expect(find.text('어르신이 점심 메뉴를 궁금해하셨어요.'), findsOneWidget);
      expect(find.text('어르신이 손주 이야기를 하셨어요.'), findsOneWidget);
      expect(find.textContaining('대화 원문은 보이지 않고'), findsOneWidget);
    });

    testWidgets('어르신이 공유에 동의하기 전에는 구역이 통째로 사라진다', (tester) async {
      await pump(tester, (_) async => const ElderChats(shareAgreed: false, chats: []));

      expect(find.text('AI 채팅 요약'), findsNothing);
    });

    testWidgets('요약이 없으면 안내 문구를 보인다', (tester) async {
      await pump(tester, (_) async => const ElderChats(shareAgreed: true, chats: []));

      expect(find.byKey(const Key('chats-empty')), findsOneWidget);
    });

    testWidgets('서버가 거절하면 그 문장을 보인다', (tester) async {
      await pump(tester, (_) async => throw const ApiException(401, '열쇠가 필요합니다'));

      expect(find.text('열쇠가 필요합니다'), findsOneWidget);
    });
  });

  group('위급 표현 알림', () {
    testWidgets('건강 경고 탭에 위급 표현으로 따로 묶여 지금 바로 연락하라고 안내한다', (tester) async {
      NulbomApi.guardianKey = 'nlb_test';
      addTearDown(() => NulbomApi.guardianKey = '');
      NulbomApi.client = MockClient((request) async {
        if (request.url.path == '/v1/guardian/elders') return _json({'elders': []});
        return _json({
          'alerts': [
            {
              'alert_id': 1,
              'elder_id': 12,
              'elder_name': '어르신 12',
              'type': 'emergency_keyword',
              'severity': 'critical',
              'message': '채팅에서 위급할 수 있는 표현이 있었어요. 직접 연락해 보세요.',
              'created_at': DateTime.now().toIso8601String(),
            }
          ],
        });
      });
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);

      await tester.pumpWidget(const MaterialApp(home: HealthAlertsScreen(initialTabIndex: 1)));
      await tester.pumpAndSettle();

      expect(find.text('위급 표현'), findsWidgets);
      expect(find.textContaining('위급할 수 있는 표현이 있었어요'), findsOneWidget);
      expect(find.textContaining('지금 바로 연락해 보세요'), findsWidgets);
      expect(find.text('평소와 다름'), findsNothing);
    });
  });
}
