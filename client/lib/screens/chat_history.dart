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

  /// 지난 대화에 이어 말할 때 부른다. 테스트에서 바꾼다. 기본은 [NulbomApi.sendChat]에 대화 번호를 실어 보낸다.
  final Future<ChatAnswer> Function(String message, int sessionId)? send;

  const ChatHistoryDrawer({
    super.key,
    required this.friendName,
    required this.fontIndex,
    this.loadSessions,
    this.loadSession,
    this.send,
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
              send: widget.send,
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

class _LogBubble {
  final String text;
  final bool fromElder;
  final bool isError;
  final bool isUrgent;

  const _LogBubble(this.text, {this.fromElder = false, this.isError = false, this.isUrgent = false});
}

/// 지난 대화 한 덩이. 앞의 말을 읽을 수 있고, 아래 입력창으로 그 대화에 이어서 말할 수 있다.
/// 이어 말하면 서버가 같은 대화에 말을 붙이고 AI는 앞 이야기를 기억하고 답한다(30일 안쪽 대화만).
class ChatHistoryScreen extends StatefulWidget {
  final MyChatSession session;
  final String friendName;
  final int fontIndex;
  final Future<List<MyChatMessage>> Function(int sessionId)? load;
  final Future<ChatAnswer> Function(String message, int sessionId)? send;

  const ChatHistoryScreen({
    super.key,
    required this.session,
    required this.friendName,
    required this.fontIndex,
    this.load,
    this.send,
  });

  @override
  State<ChatHistoryScreen> createState() => _ChatHistoryScreenState();
}

class _ChatHistoryScreenState extends State<ChatHistoryScreen> {
  final TextEditingController _input = TextEditingController();
  final ScrollController _scroll = ScrollController();
  List<_LogBubble>? _bubbles; // null이면 아직 불러오는 중
  Object? _loadError;
  bool _sending = false;
  late int _fontIndex;

  @override
  void initState() {
    super.initState();
    _fontIndex = widget.fontIndex;
    _load();
  }

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  double get _fontSize => chatFontOptions[_fontIndex].size;

  Future<void> _load() async {
    try {
      final messages = await (widget.load ?? NulbomApi.myChat)(widget.session.sessionId);
      if (!mounted) return;
      setState(() => _bubbles = [for (final m in messages) _LogBubble(m.text, fromElder: m.fromElder)]);
      _scrollDown(jump: true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _loadError = e);
    }
  }

  Future<void> _pickFont() async {
    final picked = await showChatFontSheet(context, _fontIndex);
    if (picked == null || !mounted) return;
    setState(() => _fontIndex = picked);
    await saveChatFontIndex(picked);
  }

  Future<void> _submit() async {
    final text = _input.text.trim();
    final bubbles = _bubbles;
    if (text.isEmpty || _sending || bubbles == null) return;
    setState(() {
      bubbles.add(_LogBubble(text, fromElder: true));
      _sending = true;
      _input.clear();
    });
    _scrollDown();
    try {
      final Future<ChatAnswer> Function(String, int) send = widget.send ??
          (String m, int id) => NulbomApi.sendChat(m, persona: widget.friendName, sessionId: id);
      final answer = await send(text, widget.session.sessionId);
      if (!mounted) return;
      setState(() => bubbles.add(_LogBubble(answer.reply, isUrgent: answer.urgent)));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => bubbles.add(_LogBubble(e.message, isError: true)));
      _restoreDraft(text);
    } catch (_) {
      if (!mounted) return;
      setState(() => bubbles.add(const _LogBubble('지금은 대답하기 어려워요. 잠시 뒤에 다시 해 주세요.', isError: true)));
      _restoreDraft(text);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
    _scrollDown();
  }

  /// 보내기가 실패하면 쓴 글을 입력창에 돌려 놓는다. 기다리는 사이 새로 쓴 글이 있으면 덮어쓰지 않는다.
  void _restoreDraft(String text) {
    if (_input.text.isEmpty) {
      _input.value = TextEditingValue(text: text, selection: TextSelection.collapsed(offset: text.length));
    }
  }

  void _scrollDown({bool jump = false}) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      if (jump) {
        _scroll.jumpTo(_scroll.position.maxScrollExtent);
      } else {
        _scroll.animateTo(_scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final bubbles = _bubbles;
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
        child: _loadError != null
            ? Padding(
                key: const Key('chat-history-screen-error'),
                padding: const EdgeInsets.all(20),
                child: Text(
                  _loadError is ApiException ? (_loadError as ApiException).message : '대화를 불러오지 못했어요.',
                  style: GoogleFonts.notoSansKr(fontSize: 18, color: chatDanger),
                ),
              )
            : bubbles == null
                ? const Center(child: CircularProgressIndicator())
                : Column(
                    children: [
                      Expanded(
                        child: ListView.builder(
                          key: const Key('chat-history-list'),
                          controller: _scroll,
                          padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                          itemCount: bubbles.length + (_sending ? 1 : 0),
                          itemBuilder: (context, i) => i == bubbles.length
                              ? _typing()
                              : ChatBubble(
                                  text: bubbles[i].text,
                                  fromElder: bubbles[i].fromElder,
                                  isError: bubbles[i].isError,
                                  isUrgent: bubbles[i].isUrgent,
                                  fontSize: _fontSize,
                                ),
                        ),
                      ),
                      ChatInputBar(
                        controller: _input,
                        sending: _sending,
                        onSubmit: _submit,
                        fontSize: _fontSize,
                        hint: '이 대화에 이어서 말해요',
                      ),
                    ],
                  ),
      ),
    );
  }

  Widget _typing() {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        key: const Key('chat-typing'),
        margin: const EdgeInsets.symmetric(vertical: 5),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        decoration: BoxDecoration(
            color: chatCard, borderRadius: BorderRadius.circular(18), border: Border.all(color: chatLine)),
        child: const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5)),
      ),
    );
  }
}
