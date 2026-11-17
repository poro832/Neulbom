import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:shared_preferences/shared_preferences.dart';

const Color chatBg = Color(0xFFEFF6FF);
const Color chatCard = Color(0xFFFFFFFF);
const Color chatInk = Color(0xFF0E2548);
const Color chatInkSoft = Color(0xFF3C5C8C);
const Color chatLine = Color(0xFFD6E4FF);
const Color chatAccent = Color(0xFF1A6BFF);
const Color chatDanger = Color(0xFFD92D20);

/// 말풍선 하나. 어르신 말은 오른쪽 파랑, AI 말은 왼쪽 흰색, 위급 안내는 붉은 테두리, 오류는 붉은 글씨.
class ChatBubble extends StatelessWidget {
  final String text;
  final bool fromElder;
  final bool isError;
  final bool isUrgent;
  final double fontSize;

  /// 있으면 말풍선 왼쪽 아래에 "소리로 듣기" 스피커 버튼이 생긴다(AI의 말에만 붙인다).
  final VoidCallback? onSpeak;

  /// 지금 이 말풍선을 읽는 중인가. 읽는 중이면 버튼이 "멈추기"로 바뀐다.
  final bool speaking;
  final Key? speakButtonKey;

  /// 있으면 소리로 듣기 스피커 왼쪽에 "번역" 버튼이 생긴다. 누르면 설정한 언어로 번역해 보여 주고 읽어 준다.
  final VoidCallback? onTranslate;

  /// 번역을 기다리는 중이면 번역 버튼 자리에 빙글빙글이 돈다.
  final bool translating;

  /// 이 말풍선의 번역문(설정한 언어). 있으면 글 아래에 보인다.
  final String? translation;

  /// 번역문 머리에 쓰는 이름. 예: "영어 번역".
  final String? translationLabel;

  /// 번역문을 읽는 중인가. 읽는 중이면 번역 버튼이 "멈추기"로 바뀐다.
  final bool translationSpeaking;
  final Key? translateButtonKey;

  const ChatBubble({
    super.key,
    required this.text,
    this.fromElder = false,
    this.isError = false,
    this.isUrgent = false,
    this.fontSize = 19,
    this.onSpeak,
    this.speaking = false,
    this.speakButtonKey,
    this.onTranslate,
    this.translating = false,
    this.translation,
    this.translationLabel,
    this.translationSpeaking = false,
    this.translateButtonKey,
  });

  @override
  Widget build(BuildContext context) {
    final Color fill = fromElder ? chatAccent : (isError ? const Color(0xFFFDECEA) : chatCard);
    final Color textColor = fromElder ? Colors.white : (isError ? chatDanger : chatInk);
    return Align(
      alignment: fromElder ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 5),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.82),
        decoration: BoxDecoration(
          color: fill,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: isUrgent ? chatDanger : (fromElder ? chatAccent : chatLine), width: isUrgent ? 2 : 1),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(text,
                style: GoogleFonts.notoSansKr(
                    fontSize: fontSize, height: 1.55, color: textColor, fontWeight: FontWeight.w500)),
            if (translation != null) ...[
              const SizedBox(height: 8),
              Container(
                key: const Key('chat-translation'),
                width: double.infinity,
                padding: const EdgeInsets.only(top: 8),
                decoration: const BoxDecoration(border: Border(top: BorderSide(color: chatLine))),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (translationLabel != null)
                      Text(translationLabel!,
                          style: GoogleFonts.notoSansKr(fontSize: 14, color: chatInkSoft, fontWeight: FontWeight.w700)),
                    Text(translation!,
                        style: GoogleFonts.notoSansKr(
                            fontSize: fontSize, height: 1.55, color: textColor, fontWeight: FontWeight.w500)),
                  ],
                ),
              ),
            ],
            if (onSpeak != null || onTranslate != null)
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  // 왼쪽부터 번역, 소리로 듣기. 번역 버튼은 눌러 둔 언어로 번역해 읽어 준다.
                  if (onTranslate != null)
                    translating
                        ? const SizedBox(
                            key: Key('chat-translating'),
                            width: 44,
                            height: 44,
                            child: Padding(
                              padding: EdgeInsets.all(10),
                              child: CircularProgressIndicator(strokeWidth: 2.5),
                            ),
                          )
                        : IconButton(
                            key: translateButtonKey,
                            tooltip: translationSpeaking ? '읽기 멈추기' : '번역해서 듣기',
                            onPressed: onTranslate,
                            padding: EdgeInsets.zero,
                            alignment: Alignment.centerLeft,
                            constraints: const BoxConstraints(minWidth: 44, minHeight: 44),
                            icon: Icon(translationSpeaking ? Icons.stop_circle_rounded : Icons.translate_rounded,
                                size: 30, color: isUrgent ? chatDanger : chatAccent),
                          ),
                  if (onSpeak != null)
                    IconButton(
                      key: speakButtonKey,
                      tooltip: speaking ? '읽기 멈추기' : '소리로 듣기',
                      onPressed: onSpeak,
                      padding: EdgeInsets.zero,
                      alignment: Alignment.centerLeft,
                      constraints: const BoxConstraints(minWidth: 44, minHeight: 44),
                      icon: Icon(speaking ? Icons.stop_circle_rounded : Icons.volume_up_rounded,
                          size: 30, color: isUrgent ? chatDanger : chatAccent),
                    ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

/// 채팅 글자 크기 고르기. 어르신이 읽기 편한 크기를 직접 고른다 — 이 기기에만 저장한다.
class ChatFontOption {
  final String label;
  final double size;
  const ChatFontOption(this.label, this.size);
}

const List<ChatFontOption> chatFontOptions = [
  ChatFontOption('작게', 16),
  ChatFontOption('보통', 19),
  ChatFontOption('크게', 23),
  ChatFontOption('아주 크게', 28),
];
const int chatFontDefaultIndex = 1;
const String _fontPrefKey = 'chat_font_size_index';

Future<int> loadChatFontIndex() async {
  try {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getInt(_fontPrefKey);
    if (saved != null && saved >= 0 && saved < chatFontOptions.length) return saved;
  } catch (_) {
    // 저장소를 못 읽어도 화면은 기본 크기로 뜬다.
  }
  return chatFontDefaultIndex;
}

Future<void> saveChatFontIndex(int index) async {
  try {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_fontPrefKey, index);
  } catch (_) {
    // 저장이 안 되어도 이번 화면에서는 바뀐 크기로 보인다.
  }
}

/// 번역 언어. [ttsLocale]은 그 언어로 읽을 때 쓰는 음성 언어 코드다.
class ChatLanguage {
  final String code; // 서버와 주고받는 코드(app/chat/translate.py의 LANGUAGES와 같다)
  final String label; // 어르신께 보이는 한국어 이름
  final String nativeName; // 그 언어로 쓴 이름
  final String ttsLocale;
  const ChatLanguage(this.code, this.label, this.nativeName, this.ttsLocale);
}

const List<ChatLanguage> chatLanguages = [
  ChatLanguage('en', '영어', 'English', 'en-US'),
  ChatLanguage('ja', '일본어', '日本語', 'ja-JP'),
  ChatLanguage('zh', '중국어', '中文', 'zh-CN'),
  ChatLanguage('vi', '베트남어', 'Tiếng Việt', 'vi-VN'),
  ChatLanguage('th', '태국어', 'ไทย', 'th-TH'),
  ChatLanguage('ru', '러시아어', 'Русский', 'ru-RU'),
];
const String chatLanguageDefault = 'en';
const String _languagePrefKey = 'chat_translate_language';

ChatLanguage chatLanguageByCode(String code) =>
    chatLanguages.firstWhere((l) => l.code == code, orElse: () => chatLanguages.first);

Future<String> loadChatLanguage() async {
  try {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(_languagePrefKey);
    if (saved != null && chatLanguages.any((l) => l.code == saved)) return saved;
  } catch (_) {
    // 저장소를 못 읽어도 화면은 기본 언어로 뜬다.
  }
  return chatLanguageDefault;
}

Future<void> saveChatLanguage(String code) async {
  try {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_languagePrefKey, code);
  } catch (_) {
    // 저장이 안 되어도 이번 화면에서는 바뀐 언어로 번역한다.
  }
}

/// 채팅 설정 아래 창 — 글자 크기와 번역 언어. 고르는 즉시 [onFont]·[onLanguage]로 알리고 창은 열어 둔다
/// (글자 크기는 뒤의 화면이 바로 바뀌는 것을 보면서 고를 수 있다). 다 골랐으면 "완료"나 바깥을 누른다.
Future<void> showChatSettingsSheet(
  BuildContext context, {
  required int fontIndex,
  required String language,
  required ValueChanged<int> onFont,
  required ValueChanged<String> onLanguage,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: chatCard,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
    builder: (context) {
      var font = fontIndex;
      var lang = language;
      return StatefulBuilder(
        builder: (context, setSheet) => SafeArea(
          child: ConstrainedBox(
            constraints: BoxConstraints(maxHeight: MediaQuery.of(context).size.height * 0.85),
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(20, 20, 20, 12),
              child: Column(
                key: const Key('chat-font-sheet'),
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('글자 크기',
                      style: GoogleFonts.notoSansKr(fontSize: 22, fontWeight: FontWeight.w800, color: chatInk)),
                  const SizedBox(height: 12),
                  for (var i = 0; i < chatFontOptions.length; i++)
                    _SettingTile(
                      tileKey: Key('chat-font-$i'),
                      selected: i == font,
                      onTap: () {
                        setSheet(() => font = i);
                        onFont(i);
                      },
                      child: Text('${chatFontOptions[i].label} — 안녕하세요',
                          style: GoogleFonts.notoSansKr(
                              fontSize: chatFontOptions[i].size, color: chatInk, fontWeight: FontWeight.w500)),
                    ),
                  const SizedBox(height: 20),
                  Text('번역 언어',
                      style: GoogleFonts.notoSansKr(fontSize: 22, fontWeight: FontWeight.w800, color: chatInk)),
                  const SizedBox(height: 4),
                  Text('말풍선의 번역 버튼을 누르면 이 언어로 번역해서 읽어 줘요.',
                      style: GoogleFonts.notoSansKr(fontSize: 15, height: 1.4, color: chatInkSoft)),
                  const SizedBox(height: 8),
                  for (final l in chatLanguages)
                    _SettingTile(
                      tileKey: Key('chat-lang-${l.code}'),
                      selected: l.code == lang,
                      onTap: () {
                        setSheet(() => lang = l.code);
                        onLanguage(l.code);
                      },
                      child: Text('${l.label} · ${l.nativeName}',
                          style: GoogleFonts.notoSansKr(fontSize: 19, color: chatInk, fontWeight: FontWeight.w500)),
                    ),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    height: 52,
                    child: FilledButton(
                      key: const Key('chat-settings-done'),
                      style: FilledButton.styleFrom(backgroundColor: chatAccent),
                      onPressed: () => Navigator.pop(context),
                      child: Text('완료', style: GoogleFonts.notoSansKr(fontSize: 19, fontWeight: FontWeight.w700)),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    },
  );
}

class _SettingTile extends StatelessWidget {
  final Key tileKey;
  final bool selected;
  final VoidCallback onTap;
  final Widget child;

  const _SettingTile({required this.tileKey, required this.selected, required this.onTap, required this.child});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      key: tileKey,
      borderRadius: BorderRadius.circular(14),
      onTap: onTap,
      child: Container(
        width: double.infinity,
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          color: selected ? const Color(0xFFE3EEFF) : chatBg,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: selected ? chatAccent : chatLine, width: selected ? 2 : 1),
        ),
        child: Row(
          children: [
            Expanded(child: child),
            if (selected) const Icon(Icons.check_circle_rounded, color: chatAccent),
          ],
        ),
      ),
    );
  }
}

/// "11월 17일 오후 2:30"
String chatTimeLabel(DateTime t) {
  final local = t.toLocal();
  final period = local.hour < 12 ? '오전' : '오후';
  final hour12 = local.hour % 12 == 0 ? 12 : local.hour % 12;
  final minute = local.minute.toString().padLeft(2, '0');
  return '${local.month}월 ${local.day}일 $period $hour12:$minute';
}

/// 채팅 입력줄(입력창 + 보내기 버튼). 답을 기다리는 동안([sending])에는 읽기 전용이라 키보드와 포커스가 유지된다.
class ChatInputBar extends StatelessWidget {
  final TextEditingController controller;
  final bool sending;
  final VoidCallback onSubmit;
  final double fontSize;
  final String hint;

  const ChatInputBar({
    super.key,
    required this.controller,
    required this.sending,
    required this.onSubmit,
    required this.fontSize,
    this.hint = '여기에 적어 주세요',
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      color: chatBg,
      child: Row(
        children: [
          Expanded(
            child: TextField(
              key: const Key('chat-input'),
              controller: controller,
              // enabled: false로 막으면 키보드가 내려가고 포커스를 잃는다. 읽기 전용으로 두어 이어서 쓰게 한다.
              readOnly: sending,
              minLines: 1,
              maxLines: 3,
              maxLength: 300,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => onSubmit(),
              style: TextStyle(fontSize: fontSize),
              decoration: InputDecoration(
                hintText: hint,
                counterText: '',
                filled: true,
                fillColor: chatCard,
                contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
                border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(28), borderSide: const BorderSide(color: chatLine)),
                enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(28), borderSide: const BorderSide(color: chatLine)),
              ),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            width: 56,
            height: 56,
            child: IconButton.filled(
              key: const Key('chat-send'),
              onPressed: sending ? null : onSubmit,
              style: IconButton.styleFrom(backgroundColor: chatAccent, foregroundColor: Colors.white),
              icon: const Icon(Icons.send_rounded, size: 26),
              tooltip: '보내기',
            ),
          ),
        ],
      ),
    );
  }
}
