import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../main.dart' show eAccent, eBg, eCard, eInk, eInkSoft, eLine;
import '../services/text_size.dart';

/// 글자 크기 고르기 창 — 어르신 메뉴, 보호자 계정 화면, 채팅 설정에서 같이 쓴다.
/// 고르는 즉시 앱 전체 글자가 바뀌고 이 기기에 저장된다. 창은 열어 둔다(뒤 화면이 바뀌는 것을 보면서 고른다).
/// 다 골랐으면 "완료"나 바깥을 누른다.
Future<void> showTextSizeSheet(BuildContext context) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: eCard,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
    builder: (context) => SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.of(context).size.height * 0.85),
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 20, 20, 12),
          child: Column(
            key: const Key('text-size-sheet'),
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('글자 크기',
                  style: GoogleFonts.notoSansKr(fontSize: 22, fontWeight: FontWeight.w800, color: eInk)),
              const SizedBox(height: 4),
              Text('앱의 글자가 이 크기로 바뀌어요.',
                  style: GoogleFonts.notoSansKr(fontSize: 15, height: 1.4, color: eInkSoft)),
              const SizedBox(height: 8),
              const TextSizeChoices(),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                height: 52,
                child: FilledButton(
                  key: const Key('text-size-done'),
                  style: FilledButton.styleFrom(backgroundColor: eAccent),
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
}

/// 4단계 목록. 예시 글은 그 단계의 실제 크기로 보여 준다(지금 고른 배율의 영향을 받지 않게 한다).
class TextSizeChoices extends StatelessWidget {
  const TextSizeChoices({super.key});

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<int>(
      valueListenable: textSizeIndex,
      builder: (context, selected, _) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < textSizeOptions.length; i++)
            InkWell(
              key: Key('text-size-$i'),
              borderRadius: BorderRadius.circular(14),
              onTap: () => setTextSize(i),
              child: Container(
                margin: const EdgeInsets.symmetric(vertical: 4),
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                decoration: BoxDecoration(
                  color: i == selected ? const Color(0xFFE3EEFF) : eBg,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: i == selected ? eAccent : eLine, width: i == selected ? 2 : 1),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: MediaQuery(
                        data: MediaQuery.of(context).copyWith(textScaler: TextScaler.noScaling),
                        child: Text('${textSizeOptions[i].label} — 안녕하세요',
                            style: GoogleFonts.notoSansKr(
                                fontSize: 19 * textSizeOptions[i].scale, color: eInk, fontWeight: FontWeight.w500)),
                      ),
                    ),
                    if (i == selected) const Icon(Icons.check_circle_rounded, color: eAccent),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}
