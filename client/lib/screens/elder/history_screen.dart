import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:google_fonts/google_fonts.dart';
import '../../theme/app_theme.dart';


class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key});

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  /// 오늘 자정. 표본 통화 시각을 여기서부터 정각으로 잡는다.
  /// `DateTime.now()`에서 빼면 화면을 연 시각의 분/초가 그대로 묻어나
  /// 09:00 정기 통화가 03:38처럼 찍힌다.
  static final DateTime _midnight = DateUtils.dateOnly(DateTime.now());

  static DateTime _at({int daysAgo = 0, required int hour}) =>
      _midnight.subtract(Duration(days: daysAgo)).add(Duration(hours: hour));

  final List<Map<String, dynamic>> _callHistory = [
    {
      'name': '아들',
      'time': _at(hour: 9),
      'duration': '00:15:32',
      'type': 'incoming',
    },
    {
      'name': '딸',
      'time': _at(hour: 8),
      'duration': '00:08:45',
      'type': 'incoming',
    },
    {
      'name': '며느리',
      'time': _at(daysAgo: 1, hour: 15),
      'duration': '00:22:10',
      'type': 'outgoing',
    },
    {
      'name': '가족의사',
      'time': _at(daysAgo: 1, hour: 9),
      'duration': '00:05:30',
      'type': 'incoming',
    },
    {
      'name': '복지관',
      'time': _at(daysAgo: 2, hour: 14),
      'duration': '00:10:15',
      'type': 'incoming',
    },
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
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
              onPressed: () {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('새로고침 중...')),
                );
              },
            ),
          ),
        ],
      ),
      body: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: _callHistory.length,
        itemBuilder: (context, index) {
          final call = _callHistory[index];
          final isIncoming = call['type'] == 'incoming';

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
                  color: isIncoming ? const Color(0xFFE5F3EA) : eAccentSoft,
                ),
                child: Icon(
                  isIncoming ? Icons.call_received : Icons.call_made,
                  color: isIncoming
                      ? const Color(0xFF2E8F5E)
                      : eAccent,
                  size: 28,
                ),
              ),
              title: Text(
                call['name'],
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
                    DateFormat('M월 d일 H:mm').format(call['time']),
                    style: TextStyle(
                      fontSize: 16,
                      color: eInkSoft,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 3,
                    ),
                    decoration: BoxDecoration(
                      color: eAccentSoft,
                      borderRadius: BorderRadius.circular(100),
                    ),
                    child: Text(
                      '통화 시간: ${call['duration']}',
                      style: TextStyle(
                        fontSize: 13.5,
                        color: eAccent,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
              trailing: IconButton(
                icon: const Icon(Icons.call, size: 28, color: eAccent),
                onPressed: () {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text('${call['name']}에게 전화 중...'),
                    ),
                  );
                },
              ),
            ),
          );
        },
      ),
    );
  }
}
