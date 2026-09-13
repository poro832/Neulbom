import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../../services/api_service.dart';
import '../../theme/app_theme.dart';


class AiChatScreen extends StatefulWidget {
  const AiChatScreen({super.key});

  @override
  State<AiChatScreen> createState() => _AiChatScreenState();
}

class _AiChatScreenState extends State<AiChatScreen> {
  final TextEditingController _messageController = TextEditingController();
  final List<ChatMessage> _messages = [
    ChatMessage(
      text: '안녕하세요! 저는 당신의 친한 친구예요. 편하게 이야기해주세요.',
      isUserMessage: false,
    ),
  ];
  bool _isLoading = false;

  @override
  void dispose() {
    _messageController.dispose();
    super.dispose();
  }

  void _sendMessage() async {
    if (_messageController.text.isEmpty) return;

    final userMessage = _messageController.text;
    _messageController.clear();

    setState(() {
      _messages.add(ChatMessage(text: userMessage, isUserMessage: true));
      _isLoading = true;
    });

    try {
      final response = await ApiService.chat(userMessage);
      setState(() {
        _messages.add(ChatMessage(text: response, isUserMessage: false));
      });
    } catch (e) {
      setState(() {
        _messages.add(
          ChatMessage(
            text: '죄송해요. 지금은 답변할 수 없어요. 잠시 후 다시 시도해주세요.',
            isUserMessage: false,
          ),
        );
      });
      print('AI 대화 에러: $e');
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        leading: IconButton(
          icon: Container(
            width: 34,
            height: 34,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: Colors.white,
              border: Border.all(color: eLine, width: 1),
            ),
            child: const Icon(Icons.chevron_left, color: eInk, size: 18),
          ),
          onPressed: () => Navigator.pop(context),
        ),
        title: Text(
          'AI 채팅',
          style: GoogleFonts.notoSerifKr(
            fontSize: 21,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        centerTitle: false,
      ),
      body: Column(
        children: [
          // 메시지 리스트
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 6),
              itemCount: _messages.length,
              reverse: true,
              itemBuilder: (context, index) {
                final message = _messages[_messages.length - 1 - index];
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Align(
                    alignment: message.isUserMessage
                        ? Alignment.centerRight
                        : Alignment.centerLeft,
                    child: Container(
                      constraints: BoxConstraints(
                        maxWidth: MediaQuery.of(context).size.width * 0.78,
                      ),
                      decoration: BoxDecoration(
                        color: message.isUserMessage ? eAccent : eCard,
                        border: message.isUserMessage
                            ? null
                            : Border.all(color: eLine, width: 1),
                        borderRadius: BorderRadius.circular(16),
                      ),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 17,
                        vertical: 14,
                      ),
                      child: Text(
                        message.text,
                        style: TextStyle(
                          fontSize: 16.5,
                          color: message.isUserMessage ? Colors.white : eInk,
                          height: 1.55,
                        ),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),

          // 로딩 표시
          if (_isLoading)
            Padding(
              padding: const EdgeInsets.all(16),
              child: CircularProgressIndicator(
                color: eAccent,
              ),
            ),

          // 입력 필드
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
            color: eBg,
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _messageController,
                    onSubmitted: (_) => _sendMessage(),
                    style: const TextStyle(fontSize: 16),
                    decoration: InputDecoration(
                      hintText: '메시지를 입력하세요',
                      hintStyle: TextStyle(
                        fontSize: 16,
                        color: eInkSoft,
                      ),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(100),
                        borderSide: const BorderSide(color: eLine),
                      ),
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 18,
                        vertical: 14,
                      ),
                      filled: true,
                      fillColor: Colors.white,
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                GestureDetector(
                  onTap: _isLoading ? null : _sendMessage,
                  child: Container(
                    width: 44,
                    height: 44,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: eAccent,
                    ),
                    child: Icon(
                      Icons.send,
                      color: Colors.white,
                      size: 18,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class ChatMessage {
  final String text;
  final bool isUserMessage;

  ChatMessage({
    required this.text,
    required this.isUserMessage,
  });
}
