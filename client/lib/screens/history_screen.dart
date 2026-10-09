import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';

import '../main.dart';
import '../models/nulbom_models.dart';
import '../services/nulbom_api.dart';

/// 어르신의 늘봄 안부 전화 기록. 서버의 `GET /v1/me/calls`를 보여 준다.
class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key});

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  late Future<List<AiCall>> _calls;

  @override
  void initState() {
    super.initState();
    _calls = NulbomApi.myCalls();
  }

  void _reload() {
    setState(() {
      _calls = NulbomApi.myCalls();
    });
  }

  static String _duration(int? seconds) {
    if (seconds == null) return '-';
    final m = (seconds ~/ 60).toString().padLeft(2, '0');
    final s = (seconds % 60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  static String _statusLabel(String status) {
    switch (status) {
      case 'completed':
        return '통화했어요';
      case 'no_answer':
        return '받지 못했어요';
      default:
        return '연결되지 않았어요';
    }
  }

  static String _errorText(Object error) =>
      error is ApiException ? error.message : '기록을 불러오지 못했어요. 잠시 뒤에 다시 해 주세요.';

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        automaticallyImplyLeading: false,
        title: Text(
          '통화 기록',
          style: GoogleFonts.notoSerifKr(
            fontSize: 28,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        centerTitle: true,
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: IconButton(
              icon: const Icon(Icons.refresh, size: 28, color: eInk),
              onPressed: _reload,
            ),
          ),
        ],
      ),
      body: FutureBuilder<List<AiCall>>(
        future: _calls,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return _message(_errorText(snapshot.error!));
          }
          final calls = snapshot.data!;
          if (calls.isEmpty) {
            return _message('아직 통화 기록이 없어요.');
          }
          return ListView.builder(
            padding: const EdgeInsets.all(16),
            itemCount: calls.length,
            itemBuilder: (context, index) => _tile(calls[index]),
          );
        },
      ),
    );
  }

  Widget _message(String text) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Text(
          text,
          textAlign: TextAlign.center,
          style: GoogleFonts.notoSansKr(fontSize: 20, color: eInkSoft),
        ),
      ),
    );
  }

  Widget _tile(AiCall call) {
    final talked = call.status == 'completed';
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: eCard,
        border: Border.all(color: eLine, width: 1),
        borderRadius: BorderRadius.circular(15),
      ),
      child: ListTile(
        contentPadding: const EdgeInsets.all(16),
        leading: Container(
          width: 60,
          height: 60,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: talked ? const Color(0xFFE5F3EA) : eAccentSoft,
          ),
          child: Icon(
            talked ? Icons.phone_in_talk : Icons.phone_missed,
            color: talked ? const Color(0xFF2E8F5E) : eAccent,
            size: 28,
          ),
        ),
        title: Text(
          '늘봄 안부 전화',
          style: GoogleFonts.notoSansKr(
            fontSize: 20,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 8),
            Text(
              DateFormat('M월 d일 H:mm').format(call.startedAt),
              style: const TextStyle(fontSize: 16, color: eInkSoft),
            ),
            const SizedBox(height: 4),
            Text(
              talked
                  ? '${_statusLabel(call.status)} · ${_duration(call.durationS)}'
                  : _statusLabel(call.status),
              style: const TextStyle(fontSize: 16, color: eInkSoft),
            ),
          ],
        ),
      ),
    );
  }
}
