import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../main.dart' show eAccent, eBg, eCard, eInk, eInkSoft, eLine;
import '../models/nulbom_models.dart';
import '../services/nulbom_api.dart';

/// 통화 한 건의 AI/어르신 대화 원문. 열 때마다 서버에 열람 기록이 남는다.
class CallTurnsScreen extends StatefulWidget {
  const CallTurnsScreen({super.key, required this.callId, required this.title});

  final int callId;
  final String title;

  @override
  State<CallTurnsScreen> createState() => _CallTurnsScreenState();
}

class _CallTurnsScreenState extends State<CallTurnsScreen> {
  late Future<List<CallTurn>> _turns;

  @override
  void initState() {
    super.initState();
    _turns = NulbomApi.callTurns(widget.callId);
  }

  static String _errorText(Object error) =>
      error is ApiException ? error.message : '대화를 불러오지 못했어요. 잠시 뒤에 다시 해 주세요.';

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        iconTheme: const IconThemeData(color: eInk),
        title: Text(
          widget.title,
          style: GoogleFonts.notoSerifKr(fontSize: 20, fontWeight: FontWeight.w700, color: eInk),
        ),
      ),
      body: FutureBuilder<List<CallTurn>>(
        future: _turns,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  _errorText(snapshot.error!),
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 14, color: eInkSoft),
                ),
              ),
            );
          }
          final turns = snapshot.data!;
          return ListView(
            padding: const EdgeInsets.all(20),
            children: [
              const Text(
                '자동 인식이라 실제 말과 다를 수 있어요.',
                style: TextStyle(fontSize: 12, color: eInkSoft),
              ),
              const SizedBox(height: 16),
              for (final turn in turns) _bubble(turn),
            ],
          );
        },
      ),
    );
  }

  Widget _bubble(CallTurn turn) {
    final ai = turn.isAi;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: ai ? CrossAxisAlignment.start : CrossAxisAlignment.end,
        children: [
          Text(ai ? 'AI' : '어르신', style: const TextStyle(fontSize: 11, color: eInkSoft)),
          const SizedBox(height: 4),
          Container(
            constraints: const BoxConstraints(maxWidth: 300),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: ai ? eCard : eAccent.withValues(alpha: 0.15),
              border: Border.all(color: ai ? eLine : eAccent.withValues(alpha: 0.3)),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Text(
              turn.text,
              style: const TextStyle(fontSize: 14, color: eInk, height: 1.5),
            ),
          ),
        ],
      ),
    );
  }
}
