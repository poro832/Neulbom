import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../models/nulbom_models.dart';
import '../services/nulbom_api.dart';
import 'chat_widgets.dart';

/// 햄버거 버튼으로 여는 지난 대화 목록 — 어르신 본인의 대화만 보인다(서버가 30일 지나면 지운다).
class ChatHistoryDrawer extends StatefulWidget {
  final String friendName;
  final int fontIndex;

  /// 테스트에서 바꾼다. 기본은 [NulbomApi.myChats].
  final Future<List<MyChatSession>> Function()? loadSessions;

  /// 테스트에서 바꾼다. 기본은 [NulbomApi.myChat].
  final Future<List<MyChatMessage>> Function(int sessionId)? loadSession;

  const ChatHistoryDrawer({
    super.key,
    required this.friendName,
    required this.fontIndex,
    this.loadSessions,
    this.loadSession,
  });

  @override
  State<ChatHistoryDrawer> createState() => _ChatHistoryDrawerState();
}

class _ChatHistoryDrawerState extends State<ChatHistoryDrawer> {
  late Future<List<MyChatSession>> _sessions;

  @override
  void initState() {
    super.initState();
    _sessions = (widget.loadSessions ?? NulbomApi.myChats)();
  }

  void _retry() {
    // 화살표로 쓰면 setState가 Future를 돌려받아 오류가 난다 — 블록으로 쓴다.
    setState(() {
      _sessions = (widget.loadSessions ?? NulbomApi.myChats)();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Drawer(
      key: const Key('chat-history-drawer'),
      backgroundColor: chatBg,
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 20, 20, 4),
              child: Text('지난 대화',
                  style: GoogleFonts.notoSansKr(fontSize: 24, fontWeight: FontWeight.w800, color: chatInk)),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
              child: Text('30일이 지난 대화는 지워져요.', style: GoogleFonts.notoSansKr(fontSize: 14, color: chatInkSoft)),
            ),
            Expanded(
              child: FutureBuilder<List<MyChatSession>>(
                future: _sessions,
                builder: (context, snapshot) {
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snapshot.hasError) return _problem(snapshot.error);
                  final sessions = snapshot.data ?? const <MyChatSession>[];
                  if (sessions.isEmpty) {
                    return Padding(
                      key: const Key('chat-history-empty'),
                      padding: const EdgeInsets.all(20),
                      child: Text('아직 나눈 대화가 없어요.',
                          style: GoogleFonts.notoSansKr(fontSize: 18, color: chatInkSoft)),
                    );
                  }
                  return ListView.separated(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
                    itemCount: sessions.length,
                    separatorBuilder: (context, index) => const SizedBox(height: 8),
                    itemBuilder: (context, i) => _tile(context, sessions[i]),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _tile(BuildContext context, MyChatSession s) {
    return Material(
      color: chatCard,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        key: Key('chat-history-${s.sessionId}'),
        borderRadius: BorderRadius.circular(14),
        onTap: () {
          final navigator = Navigator.of(context);
          navigator.pop(); // 서랍을 닫고
          navigator.push(MaterialPageRoute(
            builder: (_) => ChatHistoryScreen(
              session: s,
              friendName: widget.friendName,
              fontIndex: widget.fontIndex,
              load: widget.loadSession,
            ),
          ));
        },
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(border: Border.all(color: chatLine), borderRadius: BorderRadius.circular(14)),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(chatTimeLabel(s.startedAt), style: GoogleFonts.notoSansKr(fontSize: 14, color: chatInkSoft)),
              const SizedBox(height: 4),
              Text(s.preview,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: GoogleFonts.notoSansKr(fontSize: 18, height: 1.4, color: chatInk, fontWeight: FontWeight.w500)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _problem(Object? error) {
    final message = error is ApiException ? error.message : '지난 대화를 불러오지 못했어요.';
    return Padding(
      key: const Key('chat-history-error'),
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(message, style: GoogleFonts.notoSansKr(fontSize: 18, color: chatDanger)),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: _retry, child: const Text('다시 불러오기')),
        ],
      ),
    );
  }
}

/// 지난 대화 한 덩이를 읽는 화면(읽기 전용).
class ChatHistoryScreen extends StatefulWidget {
  final MyChatSession session;
  final String friendName;
  final int fontIndex;
  final Future<List<MyChatMessage>> Function(int sessionId)? load;

  const ChatHistoryScreen({
    super.key,
    required this.session,
    required this.friendName,
    required this.fontIndex,
    this.load,
  });

  @override
  State<ChatHistoryScreen> createState() => _ChatHistoryScreenState();
}

class _ChatHistoryScreenState extends State<ChatHistoryScreen> {
  late Future<List<MyChatMessage>> _messages;
  late int _fontIndex;

  @override
  void initState() {
    super.initState();
    _fontIndex = widget.fontIndex;
    _messages = (widget.load ?? NulbomApi.myChat)(widget.session.sessionId);
  }

  Future<void> _pickFont() async {
    final picked = await showChatFontSheet(context, _fontIndex);
    if (picked == null || !mounted) return;
    setState(() => _fontIndex = picked);
    await saveChatFontIndex(picked);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: chatBg,
      appBar: AppBar(
        backgroundColor: chatBg,
        elevation: 0,
        iconTheme: const IconThemeData(color: chatInk),
        title: Text(chatTimeLabel(widget.session.startedAt),
            style: GoogleFonts.notoSansKr(fontSize: 20, fontWeight: FontWeight.w800, color: chatInk)),
        actions: [
          IconButton(
            key: const Key('chat-history-font'),
            tooltip: '글자 크기',
            icon: const Icon(Icons.text_fields_rounded),
            onPressed: _pickFont,
          ),
        ],
      ),
      body: SafeArea(
        child: FutureBuilder<List<MyChatMessage>>(
          future: _messages,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              final e = snapshot.error;
              return Padding(
                key: const Key('chat-history-screen-error'),
                padding: const EdgeInsets.all(20),
                child: Text(e is ApiException ? e.message : '대화를 불러오지 못했어요.',
                    style: GoogleFonts.notoSansKr(fontSize: 18, color: chatDanger)),
              );
            }
            final messages = snapshot.data ?? const <MyChatMessage>[];
            return ListView.builder(
              key: const Key('chat-history-list'),
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
              itemCount: messages.length,
              itemBuilder: (context, i) => ChatBubble(
                text: messages[i].text,
                fromElder: messages[i].fromElder,
                fontSize: chatFontOptions[_fontIndex].size,
              ),
            );
          },
        ),
      ),
    );
  }
}
