import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../models/nulbom_models.dart';
import '../services/nulbom_api.dart';
import '../services/speaker.dart';
import '../utils/korean.dart';
import 'chat_history.dart';
import 'chat_widgets.dart';

/// 어르신의 글 말동무 — 심심할 때 이야기하고 궁금한 것을 물어본다.
///
/// 앱은 말을 서버에 보내고 AI의 답을 받아 보여 줄 뿐이다. AI는 서버가 부르는 LLM 게이트웨이에 있다.
/// 위급한 말(예: "가슴이 아파요")은 서버가 규칙으로 찾아 보호자께 알리고, 안내 문장을 답에 붙여 보낸다.
///
/// - 제목과 인사말, AI가 말하는 이름은 어르신이 지은 AI 친구 이름([friendName])이다(메인 화면 "○○와 통화하기"와 같다).
/// - 왼쪽 위 햄버거 버튼은 지난 대화 목록을 연다(서버가 30일 보관).
/// - 오른쪽 위 "글자 크기"는 4단계로 고르고 이 기기에 저장한다.
/// - AI 말풍선 왼쪽 아래 스피커를 누르면 그 말을 소리로 읽어 준다(한 번에 하나, 다시 누르면 멈춘다).
/// - 화면을 나가면 이 화면의 말풍선은 사라진다(서버는 30분 안에 다시 오면 같은 대화로 이어 준다).
class AiChatScreen extends StatefulWidget {
  /// AI 친구 이름. 메인 화면이 넘긴다.
  final String friendName;

  /// 테스트에서 바꾼다. 기본은 [NulbomApi.sendChat]에 [friendName]을 실어 보낸다.
  final Future<ChatAnswer> Function(String message)? send;

  /// 테스트에서 바꾼다. 기본은 [NulbomApi.myChats].
  final Future<List<MyChatSession>> Function()? loadSessions;

  /// 테스트에서 바꾼다. 기본은 [NulbomApi.myChat].
  final Future<List<MyChatMessage>> Function(int sessionId)? loadSession;

  /// 지난 대화에 이어 말할 때 부른다. 테스트에서 바꾼다. 기본은 [NulbomApi.sendChat]에 대화 번호를 실어 보낸다.
  final Future<ChatAnswer> Function(String message, int sessionId)? sendInSession;

  /// 소리로 듣기에 쓰는 음성 엔진. 테스트에서 바꾼다. 기본은 기기 안의 음성 합성이다.
  final Speaker? speaker;

  const AiChatScreen({
    super.key,
    this.friendName = 'AI 친구',
    this.send,
    this.loadSessions,
    this.loadSession,
    this.sendInSession,
    this.speaker,
  });

  @override
  State<AiChatScreen> createState() => _AiChatScreenState();
}

class _Bubble {
  final String text;
  final bool fromElder;
  final bool isError;
  final bool isUrgent;

  const _Bubble(this.text, {this.fromElder = false, this.isError = false, this.isUrgent = false});
}

class _AiChatScreenState extends State<AiChatScreen> {
  final TextEditingController _input = TextEditingController();
  final ScrollController _scroll = ScrollController();
  late final List<_Bubble> _bubbles;
  bool _sending = false;
  int _fontIndex = chatFontDefaultIndex;
  late final ReadAloud _readAloud = ReadAloud(speaker: widget.speaker);

  @override
  void initState() {
    super.initState();
    _bubbles = [
      _Bubble('안녕하세요, 저는 ${withIEyo(widget.friendName)}. 궁금한 것이나 하고 싶은 이야기를 편하게 적어 주세요.'),
    ];
    _loadFont();
  }

  Future<void> _loadFont() async {
    final index = await loadChatFontIndex();
    if (mounted) setState(() => _fontIndex = index);
  }

  @override
  void dispose() {
    _readAloud.dispose();
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  double get _fontSize => chatFontOptions[_fontIndex].size;

  Future<void> _pickFont() async {
    final picked = await showChatFontSheet(context, _fontIndex);
    if (picked == null || !mounted) return;
    setState(() => _fontIndex = picked);
    await saveChatFontIndex(picked);
  }

  Future<void> _submit() async {
    final text = _input.text.trim();
    if (text.isEmpty || _sending) return;
    _readAloud.stop(); // 새 말을 보내면 읽던 소리는 멈춘다
    setState(() {
      _bubbles.add(_Bubble(text, fromElder: true));
      _sending = true;
      _input.clear();
    });
    _scrollDown();
    try {
      final Future<ChatAnswer> Function(String) send =
          widget.send ?? (String m) => NulbomApi.sendChat(m, persona: widget.friendName);
      final answer = await send(text);
      if (!mounted) return;
      setState(() => _bubbles.add(_Bubble(answer.reply, isUrgent: answer.urgent)));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _bubbles.add(_Bubble(e.message, isError: true)));
      _restoreDraft(text);
    } catch (_) {
      if (!mounted) return;
      setState(() => _bubbles.add(const _Bubble('지금은 대답하기 어려워요. 잠시 뒤에 다시 해 주세요.', isError: true)));
      _restoreDraft(text);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
    _scrollDown();
  }

  /// 보내기가 실패하면 쓴 글을 입력창에 돌려 놓는다 — 긴 글을 다시 쓰게 하지 않는다.
  /// 기다리는 사이 새로 쓴 글이 있으면 덮어쓰지 않는다.
  void _restoreDraft(String text) {
    if (_input.text.isEmpty) {
      _input.value = TextEditingValue(text: text, selection: TextSelection.collapsed(offset: text.length));
    }
  }

  void _scrollDown() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: chatBg,
      drawer: ChatHistoryDrawer(
        friendName: widget.friendName,
        fontIndex: _fontIndex,
        loadSessions: widget.loadSessions,
        loadSession: widget.loadSession,
        send: widget.sendInSession,
        speaker: widget.speaker,
      ),
      appBar: AppBar(
        backgroundColor: chatBg,
        elevation: 0,
        iconTheme: const IconThemeData(color: chatInk),
        leading: Builder(
          builder: (context) => IconButton(
            key: const Key('chat-menu'),
            tooltip: '지난 대화',
            icon: const Icon(Icons.menu_rounded),
            onPressed: () => Scaffold.of(context).openDrawer(),
          ),
        ),
        title: Text(widget.friendName,
            key: const Key('chat-title'),
            overflow: TextOverflow.ellipsis,
            style: GoogleFonts.notoSansKr(fontSize: 22, fontWeight: FontWeight.w800, color: chatInk)),
        actions: [
          IconButton(
            key: const Key('chat-font'),
            tooltip: '글자 크기',
            icon: const Icon(Icons.text_fields_rounded),
            onPressed: _pickFont,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            _notice(),
            Expanded(
              child: ValueListenableBuilder<int?>(
                valueListenable: _readAloud.speaking,
                builder: (context, speaking, _) => ListView.builder(
                  key: const Key('chat-list'),
                  controller: _scroll,
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                  itemCount: _bubbles.length + (_sending ? 1 : 0),
                  itemBuilder: (context, i) =>
                      i == _bubbles.length ? _typing() : _bubble(_bubbles[i], i, speaking == i),
                ),
              ),
            ),
            _inputBar(),
          ],
        ),
      ),
    );
  }

  Widget _notice() {
    return Container(
      key: const Key('chat-notice'),
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 4),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: chatCard,
        border: Border.all(color: chatLine),
        borderRadius: BorderRadius.circular(12),
      ),
      child: const Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.info_outline_rounded, size: 18, color: chatInkSoft),
          SizedBox(width: 8),
          Expanded(
            child: Text(
              '위급한 말씀을 하시면 가족분께 알려질 수 있어요. 약이나 병은 정확히 알려 드리기 어려우니 병원에 꼭 여쭤 보세요.',
              style: TextStyle(fontSize: 14, color: chatInkSoft, height: 1.5),
            ),
          ),
        ],
      ),
    );
  }

  Widget _bubble(_Bubble b, int index, bool speaking) => ChatBubble(
        text: b.text,
        fromElder: b.fromElder,
        isError: b.isError,
        isUrgent: b.isUrgent,
        fontSize: _fontSize,
        // 내가 쓴 말과 오류 문구는 읽어 주지 않는다 — AI의 말에만 스피커가 붙는다.
        onSpeak: b.fromElder || b.isError ? null : () => _speak(index, b.text),
        speaking: speaking,
        speakButtonKey: Key('speak-$index'),
      );

  Future<void> _speak(int index, String text) async {
    final message = await _readAloud.toggle(index, text);
    if (message != null && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
    }
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

  Widget _inputBar() =>
      ChatInputBar(controller: _input, sending: _sending, onSubmit: _submit, fontSize: _fontSize);
}
