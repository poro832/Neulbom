import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../models/nulbom_models.dart';
import '../services/nulbom_api.dart';

const Color _bg = Color(0xFFEFF6FF);
const Color _card = Color(0xFFFFFFFF);
const Color _ink = Color(0xFF0E2548);
const Color _inkSoft = Color(0xFF3C5C8C);
const Color _line = Color(0xFFD6E4FF);
const Color _accent = Color(0xFF1A6BFF);
const Color _danger = Color(0xFFD92D20);

/// 어르신의 글 말동무 — 심심할 때 이야기하고 궁금한 것을 물어본다.
///
/// 앱은 말을 서버에 보내고 AI의 답을 받아 보여 줄 뿐이다. AI는 서버가 부르는 LLM 게이트웨이에 있다.
/// 위급한 말(예: "가슴이 아파요")은 서버가 규칙으로 찾아 보호자께 알리고, 안내 문장을 답에 붙여 보낸다.
/// 화면을 나가면 이 화면의 말풍선은 사라진다(서버는 30분 안에 다시 오면 같은 대화로 이어 준다).
class AiChatScreen extends StatefulWidget {
  /// 테스트에서 바꾼다. 기본은 [NulbomApi.sendChat].
  final Future<ChatAnswer> Function(String message)? send;

  const AiChatScreen({super.key, this.send});

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
  static const String _greeting = '안녕하세요, 저는 늘봄이에요. 궁금한 것이나 하고 싶은 이야기를 편하게 적어 주세요.';

  final TextEditingController _input = TextEditingController();
  final ScrollController _scroll = ScrollController();
  final List<_Bubble> _bubbles = [const _Bubble(_greeting)];
  bool _sending = false;

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final text = _input.text.trim();
    if (text.isEmpty || _sending) return;
    setState(() {
      _bubbles.add(_Bubble(text, fromElder: true));
      _sending = true;
      _input.clear();
    });
    _scrollDown();
    try {
      final answer = await (widget.send ?? NulbomApi.sendChat)(text);
      if (!mounted) return;
      setState(() => _bubbles.add(_Bubble(answer.reply, isUrgent: answer.urgent)));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _bubbles.add(_Bubble(e.message, isError: true)));
    } catch (_) {
      if (!mounted) return;
      setState(() => _bubbles.add(const _Bubble('지금은 대답하기 어려워요. 잠시 뒤에 다시 해 주세요.', isError: true)));
    } finally {
      if (mounted) setState(() => _sending = false);
    }
    _scrollDown();
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
      backgroundColor: _bg,
      appBar: AppBar(
        backgroundColor: _bg,
        elevation: 0,
        iconTheme: const IconThemeData(color: _ink),
        title: Text('AI 채팅',
            style: GoogleFonts.notoSansKr(fontSize: 22, fontWeight: FontWeight.w800, color: _ink)),
      ),
      body: SafeArea(
        child: Column(
          children: [
            _notice(),
            Expanded(
              child: ListView.builder(
                key: const Key('chat-list'),
                controller: _scroll,
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                itemCount: _bubbles.length + (_sending ? 1 : 0),
                itemBuilder: (context, i) => i == _bubbles.length ? _typing() : _bubble(_bubbles[i]),
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
        color: _card,
        border: Border.all(color: _line),
        borderRadius: BorderRadius.circular(12),
      ),
      child: const Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.info_outline_rounded, size: 18, color: _inkSoft),
          SizedBox(width: 8),
          Expanded(
            child: Text(
              '위급한 말씀을 하시면 가족분께 알려질 수 있어요. 약이나 병은 정확히 알려 드리기 어려우니 병원에 꼭 여쭤 보세요.',
              style: TextStyle(fontSize: 14, color: _inkSoft, height: 1.5),
            ),
          ),
        ],
      ),
    );
  }

  Widget _bubble(_Bubble b) {
    final Color fill = b.fromElder ? _accent : (b.isError ? const Color(0xFFFDECEA) : _card);
    final Color textColor = b.fromElder ? Colors.white : (b.isError ? _danger : _ink);
    return Align(
      alignment: b.fromElder ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 5),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.82),
        decoration: BoxDecoration(
          color: fill,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: b.isUrgent ? _danger : (b.fromElder ? _accent : _line), width: b.isUrgent ? 2 : 1),
        ),
        child: Text(b.text,
            style: GoogleFonts.notoSansKr(fontSize: 19, height: 1.55, color: textColor, fontWeight: FontWeight.w500)),
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
            color: _card, borderRadius: BorderRadius.circular(18), border: Border.all(color: _line)),
        child: const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5)),
      ),
    );
  }

  Widget _inputBar() {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      color: _bg,
      child: Row(
        children: [
          Expanded(
            child: TextField(
              key: const Key('chat-input'),
              controller: _input,
              enabled: !_sending,
              minLines: 1,
              maxLines: 3,
              maxLength: 300,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _submit(),
              style: const TextStyle(fontSize: 19),
              decoration: InputDecoration(
                hintText: '여기에 적어 주세요',
                counterText: '',
                filled: true,
                fillColor: _card,
                contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(28), borderSide: const BorderSide(color: _line)),
                enabledBorder:
                    OutlineInputBorder(borderRadius: BorderRadius.circular(28), borderSide: const BorderSide(color: _line)),
              ),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            width: 56,
            height: 56,
            child: IconButton.filled(
              key: const Key('chat-send'),
              onPressed: _sending ? null : _submit,
              style: IconButton.styleFrom(backgroundColor: _accent, foregroundColor: Colors.white),
              icon: const Icon(Icons.send_rounded, size: 26),
              tooltip: '보내기',
            ),
          ),
        ],
      ),
    );
  }
}
