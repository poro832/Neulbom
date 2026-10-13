import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../main.dart' show eAccent, eBg, eCard, eInk, eInkSoft, eLine;
import '../models/nulbom_models.dart';
import '../services/nulbom_api.dart';
import 'call_turns_screen.dart';

/// 한 어르신의 통화 목록과 요약. 원문이 있는 통화는 눌러서 대화를 읽는다.
/// 어르신이 통화 내용 공유에 동의하기 전에는 아무것도 보이지 않는다.
class ElderCallsScreen extends StatefulWidget {
  const ElderCallsScreen({super.key, required this.elderId, required this.elderName});

  final int elderId;
  final String elderName;

  @override
  State<ElderCallsScreen> createState() => _ElderCallsScreenState();
}

class _ElderCallsScreenState extends State<ElderCallsScreen> {
  late Future<ElderCalls> _calls;

  @override
  void initState() {
    super.initState();
    _calls = NulbomApi.elderCalls(widget.elderId);
  }

  static String _errorText(Object error) =>
      error is ApiException ? error.message : '통화를 불러오지 못했어요. 잠시 뒤에 다시 해 주세요.';

  static String _dateText(DateTime time) {
    final t = time.toLocal();
    final hm = '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
    return '${t.month}월 ${t.day}일 $hm';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        iconTheme: const IconThemeData(color: eInk),
        title: Text(
          '${widget.elderName}님 통화',
          style: GoogleFonts.notoSansKr(fontSize: 20, fontWeight: FontWeight.w700, color: eInk),
        ),
      ),
      body: FutureBuilder<ElderCalls>(
        future: _calls,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return _message(_errorText(snapshot.error!));
          }
          final result = snapshot.data!;
          if (!result.shareAgreed) return _message('어르신이 동의한 뒤에 볼 수 있어요.');
          if (result.calls.isEmpty) return _message('아직 통화가 없어요.');
          return ListView(
            padding: const EdgeInsets.all(20),
            children: [for (final call in result.calls) _card(context, call)],
          );
        },
      ),
    );
  }

  Widget _message(String text) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            text,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 14, color: eInkSoft),
          ),
        ),
      );

  Widget _card(BuildContext context, CallSummary call) {
    final title = _dateText(call.startedAt);
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Material(
        color: eCard,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: call.hasTurns
              ? () => Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => CallTurnsScreen(callId: call.callId, title: '$title 통화'),
                    ),
                  )
              : null,
          child: Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              border: Border.all(color: eLine),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        title,
                        style: GoogleFonts.notoSansKr(
                          fontSize: 14,
                          fontWeight: FontWeight.w700,
                          color: eInk,
                        ),
                      ),
                    ),
                    if (call.hasTurns)
                      const Icon(Icons.chevron_right_rounded, color: eAccent, size: 20),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  call.summary ?? '요약이 없어요.',
                  style: const TextStyle(fontSize: 14, color: eInk, height: 1.6),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
