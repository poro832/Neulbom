import 'dart:async';
import 'dart:convert';

import 'package:eldercare/models/nulbom_models.dart';
import 'package:eldercare/screens/ai_chat_screen.dart';
import 'package:eldercare/screens/chat_widgets.dart';
import 'package:eldercare/utils/korean.dart';
import 'package:eldercare/screens/elder_chats_section.dart';
import 'package:eldercare/screens/health_alerts_screen.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:eldercare/services/text_size.dart';
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

    test('sendChat은 AI 친구 이름이 있으면 함께 보내고, 빈 이름은 보내지 않는다', () async {
      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return _json({'reply': '네', 'urgent': false});
      });

      await NulbomApi.sendChat('안녕', persona: ' 미소 ', key: 'nle_test');
      expect(jsonDecode(seen.body), {'message': '안녕', 'persona': '미소'});

      await NulbomApi.sendChat('안녕', persona: '  ', key: 'nle_test');
      expect(jsonDecode(seen.body), {'message': '안녕'});
    });

    test('translate는 어르신 열쇠로 글과 언어를 보내고 번역문을 읽는다', () async {
      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return _json({'text': 'It is sunny.', 'language': 'en'});
      });

      final text = await NulbomApi.translate('맑아요.', language: 'en', key: 'nle_test');

      expect(seen.method, 'POST');
      expect(seen.url.path, '/v1/me/translate');
      expect(seen.headers['Authorization'], 'Bearer nle_test');
      expect(jsonDecode(seen.body), {'text': '맑아요.', 'language': 'en'});
      expect(text, 'It is sunny.');
    });

    test('translate는 서버가 거절하면 그 문장을 오류 메시지로 던진다', () async {
      NulbomApi.client = MockClient((request) async => _json({'detail': '오늘은 번역을 많이 했어요. 내일 또 해 보세요'}, 429));

      await expectLater(
        NulbomApi.translate('맑아요.', language: 'en', key: 'nle_test'),
        throwsA(isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 429)
            .having((e) => e.message, 'message', contains('내일 또'))),
      );
    });

    test('sendChat은 지난 대화에 이어 말할 때만 대화 번호를 보낸다', () async {
      late http.Request seen;
      NulbomApi.client = MockClient((request) async {
        seen = request;
        return _json({'reply': '네', 'urgent': false});
      });

      await NulbomApi.sendChat('이어서', sessionId: 7, key: 'nle_test');
      expect(jsonDecode(seen.body), {'message': '이어서', 'session_id': 7});

      await NulbomApi.sendChat('새로', key: 'nle_test');
      expect(jsonDecode(seen.body), {'message': '새로'});
    });

    test('myChats와 myChat은 어르신 열쇠로 내 지난 대화를 읽는다', () async {
      final seen = <http.Request>[];
      NulbomApi.client = MockClient((request) async {
        seen.add(request);
        if (request.url.path == '/v1/me/chats') {
          return _json({
            'sessions': [
              {'session_id': 7, 'started_at': '2026-11-17T14:30:00+09:00', 'preview': '날씨 어때요?'}
            ]
          });
        }
        return _json({
          'session_id': 7,
          'messages': [
            {'role': 'elder', 'text': '날씨 어때요?', 'created_at': '2026-11-17T14:30:00+09:00'},
            {'role': 'ai', 'text': '맑아요.', 'created_at': '2026-11-17T14:30:05+09:00'},
          ]
        });
      });

      final sessions = await NulbomApi.myChats(key: 'nle_test');
      final messages = await NulbomApi.myChat(7, key: 'nle_test');

      expect(seen.map((r) => r.url.path), ['/v1/me/chats', '/v1/me/chats/7']);
      expect(seen.every((r) => r.headers['Authorization'] == 'Bearer nle_test'), isTrue);
      expect(sessions.single.preview, '날씨 어때요?');
      expect([for (final m in messages) m.fromElder], [true, false]);
      expect(messages.last.text, '맑아요.');
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
    Future<void> open(
      WidgetTester tester,
      Future<ChatAnswer> Function(String) send, {
      String friendName = '늘봄이',
      Future<List<MyChatSession>> Function()? loadSessions,
      Future<List<MyChatMessage>> Function(int)? loadSession,
    }) async {
      tester.view.physicalSize = const Size(1000, 2000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      await tester.pumpWidget(const SizedBox()); // 같은 테스트에서 다시 열 때 State를 새로 만든다
      await tester.pumpWidget(MaterialApp(
        home: AiChatScreen(
            friendName: friendName, send: send, loadSessions: loadSessions, loadSession: loadSession),
      ));
      await tester.pump();
    }

    testWidgets('인사말과, 위급한 말이 가족에게 알려질 수 있다는 안내를 먼저 보여 준다', (tester) async {
      await open(tester, (_) async => const ChatAnswer(reply: '', urgent: false));

      expect(find.textContaining('저는 늘봄이예요'), findsOneWidget);
      expect(find.byKey(const Key('chat-notice')), findsOneWidget);
      expect(find.textContaining('가족분께 알려질 수 있어요'), findsOneWidget);
    });

    testWidgets('제목과 인사말은 어르신이 지은 AI 친구 이름이다(받침에 따라 이에요/예요)', (tester) async {
      await open(tester, (_) async => const ChatAnswer(reply: '', urgent: false), friendName: '미소');

      expect(find.byKey(const Key('chat-title')), findsOneWidget);
      expect(tester.widget<Text>(find.byKey(const Key('chat-title'))).data, '미소');
      expect(find.textContaining('저는 미소예요'), findsOneWidget);
      expect(find.textContaining('늘봄'), findsNothing);
      expect(find.text('AI 채팅'), findsNothing);

      await open(tester, (_) async => const ChatAnswer(reply: '', urgent: false), friendName: '영철');
      expect(find.textContaining('저는 영철이에요'), findsOneWidget);
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

    testWidgets('보내기가 실패하면 쓴 글이 입력창에 돌아온다', (tester) async {
      await open(tester, (_) async => throw const ApiException(503, '지금은 대답하기 어려워요'));

      await tester.enterText(find.byKey(const Key('chat-input')), '긴 이야기를 적었어요');
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pumpAndSettle();

      final field = tester.widget<TextField>(find.byKey(const Key('chat-input')));
      expect(field.controller!.text, '긴 이야기를 적었어요');
    });

    testWidgets('답을 기다리는 동안에도 입력창은 포커스를 잃지 않는다(읽기 전용일 뿐)', (tester) async {
      final answer = Completer<ChatAnswer>();
      await open(tester, (_) => answer.future);

      await tester.enterText(find.byKey(const Key('chat-input')), '안녕');
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pump();

      final field = tester.widget<TextField>(find.byKey(const Key('chat-input')));
      expect(field.enabled, isNot(false));
      expect(field.readOnly, isTrue);
      answer.complete(const ChatAnswer(reply: '네.', urgent: false));
      await tester.pumpAndSettle();
      expect(tester.widget<TextField>(find.byKey(const Key('chat-input'))).readOnly, isFalse);
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

  group('지난 대화(햄버거)와 글자 크기', () {
    final sessions = [
      MyChatSession(sessionId: 8, startedAt: DateTime(2026, 11, 17, 14, 30), preview: '점심 뭐 먹을까요'),
      MyChatSession(sessionId: 7, startedAt: DateTime(2026, 11, 16, 9, 5), preview: '날씨 어때요?'),
    ];

    Future<void> open(
      WidgetTester tester, {
      Future<List<MyChatSession>> Function()? loadSessions,
      Future<List<MyChatMessage>> Function(int)? loadSession,
      Future<ChatAnswer> Function(String, int)? sendInSession,
    }) async {
      tester.view.physicalSize = const Size(1000, 2000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      await tester.pumpWidget(const SizedBox()); // 같은 테스트에서 다시 열 때 State를 새로 만든다
      await tester.pumpWidget(MaterialApp(
        home: AiChatScreen(
          friendName: '미소',
          sendInSession: sendInSession,
          send: (_) async => const ChatAnswer(reply: '네', urgent: false),
          loadSessions: loadSessions ?? () async => sessions,
          loadSession: loadSession ??
              (id) async => [
                    const MyChatMessage(fromElder: true, text: '날씨 어때요?'),
                    const MyChatMessage(fromElder: false, text: '맑아요, 산책하기 좋아요.'),
                  ],
        ),
      ));
      await tester.pump();
    }

    testWidgets('햄버거 버튼을 누르면 지난 대화가 최신순으로 미리보기와 함께 보인다', (tester) async {
      await open(tester);

      await tester.tap(find.byKey(const Key('chat-menu')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('chat-history-drawer')), findsOneWidget);
      expect(find.text('지난 대화'), findsOneWidget);
      expect(find.textContaining('30일이 지난 대화는 지워져요'), findsOneWidget);
      expect(find.text('점심 뭐 먹을까요'), findsOneWidget);
      expect(find.text('11월 17일 오후 2:30'), findsOneWidget);
      expect(find.text('11월 16일 오전 9:05'), findsOneWidget);
      expect(tester.getTopLeft(find.byKey(const Key('chat-history-8'))).dy,
          lessThan(tester.getTopLeft(find.byKey(const Key('chat-history-7'))).dy));
    });

    testWidgets('지난 대화를 누르면 그 대화의 말이 열리고 이어서 말할 입력창이 있다', (tester) async {
      int? opened;
      await open(tester, loadSession: (id) async {
        opened = id;
        return [
          const MyChatMessage(fromElder: true, text: '날씨 어때요?'),
          const MyChatMessage(fromElder: false, text: '맑아요, 산책하기 좋아요.'),
        ];
      });

      await tester.tap(find.byKey(const Key('chat-menu')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('chat-history-7')));
      await tester.pumpAndSettle();

      expect(opened, 7);
      expect(find.byKey(const Key('chat-history-list')), findsOneWidget);
      expect(find.text('맑아요, 산책하기 좋아요.'), findsOneWidget);
      expect(find.byKey(const Key('chat-input')), findsOneWidget); // 이어서 말할 수 있다
      expect(find.text('이 대화에 이어서 말해요'), findsOneWidget);
      expect(find.byKey(const Key('chat-history-drawer')), findsNothing); // 서랍은 닫혔다
    });

    testWidgets('지난 대화에 이어 말하면 그 대화 번호로 보내고 답이 아래에 붙는다', (tester) async {
      String? sentText;
      int? sentSession;
      await open(tester, sendInSession: (text, id) async {
        sentText = text;
        sentSession = id;
        return const ChatAnswer(reply: '그럼 산책 가세요.', urgent: false);
      });

      await tester.tap(find.byKey(const Key('chat-menu')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('chat-history-7')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('chat-input')), '그럼 오늘 나갈까요?');
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pumpAndSettle();

      expect(sentText, '그럼 오늘 나갈까요?');
      expect(sentSession, 7);
      expect(find.text('날씨 어때요?'), findsOneWidget); // 앞 대화가 그대로 있다
      expect(find.text('그럼 오늘 나갈까요?'), findsOneWidget);
      expect(find.text('그럼 산책 가세요.'), findsOneWidget);
    });

    testWidgets('이어 말하기가 실패하면 오류 말풍선이 붙고 쓴 글이 입력창에 돌아온다', (tester) async {
      await open(tester, sendInSession: (text, id) async => throw const ApiException(404, '그 대화를 찾을 수 없어요'));

      await tester.tap(find.byKey(const Key('chat-menu')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('chat-history-7')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('chat-input')), '이어서 말해요');
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pumpAndSettle();

      expect(find.text('그 대화를 찾을 수 없어요'), findsOneWidget);
      expect(tester.widget<TextField>(find.byKey(const Key('chat-input'))).controller!.text, '이어서 말해요');
    });

    testWidgets('이어 말한 위급한 답은 붉은 테두리로 보인다', (tester) async {
      await open(tester,
          sendInSession: (text, id) async =>
              const ChatAnswer(reply: '참지 마시고 119에 전화하세요.', urgent: true));

      await tester.tap(find.byKey(const Key('chat-menu')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('chat-history-7')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('chat-input')), '가슴이 아파요');
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pumpAndSettle();

      final bubble = tester.widget<ChatBubble>(find.ancestor(
          of: find.text('참지 마시고 119에 전화하세요.'), matching: find.byType(ChatBubble)));
      expect(bubble.isUrgent, isTrue);
    });

    testWidgets('지난 대화가 없으면 안내를, 불러오지 못하면 오류와 다시 불러오기를 보인다', (tester) async {
      await open(tester, loadSessions: () async => []);
      await tester.tap(find.byKey(const Key('chat-menu')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('chat-history-empty')), findsOneWidget);
      expect(find.text('아직 나눈 대화가 없어요.'), findsOneWidget);

      var calls = 0;
      await open(tester, loadSessions: () async {
        calls++;
        if (calls == 1) throw const ApiException(503, '잠시 뒤에 다시 해 주세요');
        return sessions;
      });
      await tester.tap(find.byKey(const Key('chat-menu')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('chat-history-error')), findsOneWidget);
      expect(find.text('잠시 뒤에 다시 해 주세요'), findsOneWidget);

      await tester.tap(find.text('다시 불러오기'));
      await tester.pumpAndSettle();
      expect(find.text('점심 뭐 먹을까요'), findsOneWidget);
    });

    testWidgets('채팅 설정에서 글자 크기를 고르면 앱 전체 설정이 바뀌고 기기에 저장된다', (tester) async {
      await open(tester);
      double bubbleSize() => tester.widget<Text>(find.textContaining('저는 미소예요')).style!.fontSize!;
      expect(bubbleSize(), 19);

      await tester.tap(find.byKey(const Key('chat-font')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('chat-font-sheet')), findsOneWidget);
      await tester.tap(find.byKey(const Key('text-size-3'))); // 아주 크게
      await tester.pumpAndSettle();

      expect(textSizeIndex.value, 3);
      expect((await SharedPreferences.getInstance()).getInt('app_text_size_index'), 3);
      // 말풍선·입력창의 기본 글자는 그대로이고 앱 맨 위 배율이 곱해진다 — 채팅이 두 번 커지지 않는다.
      expect(bubbleSize(), 19);
      expect(tester.widget<TextField>(find.byKey(const Key('chat-input'))).style!.fontSize, 19);
    });

    test('이름 뒤 이에요/예요는 받침에 맞춰 붙는다', () {
      expect(withIEyo('미소'), '미소예요');
      expect(withIEyo('영철'), '영철이에요');
      expect(withIEyo('AI 친구'), 'AI 친구예요');
      expect(withIEyo(' '), '');
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
