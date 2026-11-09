import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';

import '../main.dart' show eCard, eInk, eInkSoft, eLine;
import '../models/nulbom_models.dart';
import '../services/nulbom_api.dart';

/// 보호자: 어르신이 앱 AI 채팅에서 나눈 이야기의 **요약**. 원문은 보이지 않는다.
///
/// 어르신이 공유에 동의하기 전에는 구역 전체를 그리지 않는다(바로 위 통화 요약 카드가 이미 안내한다).
/// 위급한 말은 이 구역이 아니라 알림으로 따로 온다 — 알림에는 말 내용이 없다.
class ElderChatsSection extends StatefulWidget {
  final int elderId;

  /// 테스트에서 바꾼다. 기본은 [NulbomApi.elderChats].
  final Future<ElderChats> Function(int elderId)? fetch;

  const ElderChatsSection({super.key, required this.elderId, this.fetch});

  @override
  State<ElderChatsSection> createState() => _ElderChatsSectionState();
}

class _ElderChatsSectionState extends State<ElderChatsSection> {
  late Future<ElderChats> _future;

  @override
  void initState() {
    super.initState();
    _future = (widget.fetch ?? NulbomApi.elderChats)(widget.elderId);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<ElderChats>(
      future: _future,
      builder: (context, snapshot) {
        final done = snapshot.connectionState == ConnectionState.done;
        final chats = done ? snapshot.data : null;
        if (chats != null && !chats.shareAgreed) return const SizedBox.shrink();
        final Widget body;
        if (!done) {
          body = const Padding(padding: EdgeInsets.symmetric(vertical: 8), child: LinearProgressIndicator());
        } else if (snapshot.hasError) {
          final error = snapshot.error;
          body = Text(
            error is ApiException ? error.message : 'AI 채팅 요약을 불러오지 못했어요. 잠시 뒤에 다시 해 주세요.',
            style: const TextStyle(fontSize: 14, color: eInkSoft),
          );
        } else if (chats!.chats.isEmpty) {
          body = const Text('아직 요약할 채팅이 없어요.', key: Key('chats-empty'), style: TextStyle(fontSize: 14, color: eInkSoft));
        } else {
          body = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [for (final c in chats.chats) _row(c)],
          );
        }
        return _frame(body);
      },
    );
  }

  Widget _row(ChatSummaryItem c) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(DateFormat('M월 d일 H:mm').format(c.startedAt),
              style: const TextStyle(fontSize: 13, color: eInkSoft, fontWeight: FontWeight.w600)),
          const SizedBox(height: 2),
          Text(c.summary, style: const TextStyle(fontSize: 15, color: eInk, height: 1.5)),
        ],
      ),
    );
  }

  Widget _frame(Widget body) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('AI 채팅 요약',
            style: GoogleFonts.notoSansKr(fontSize: 18, fontWeight: FontWeight.w700, color: eInk)),
        const SizedBox(height: 8),
        Container(
          width: double.infinity,
          decoration: BoxDecoration(color: eCard, border: Border.all(color: eLine), borderRadius: BorderRadius.circular(12)),
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              body,
              const Divider(height: 1, color: eLine),
              const SizedBox(height: 10),
              const Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(Icons.info_outline_rounded, size: 16, color: eInkSoft),
                  SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      '어르신이 앱에서 AI와 나눈 이야기를 짧게 줄인 것이에요. 대화 원문은 보이지 않고 진단이 아니에요.',
                      style: TextStyle(fontSize: 12, color: eInkSoft, height: 1.5),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }
}
