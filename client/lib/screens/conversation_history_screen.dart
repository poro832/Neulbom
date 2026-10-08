import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'conversation_detail_screen.dart';

const Color eBg = Color(0xFFFBF6ED);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);
const Color eBrass = Color(0xFFB78A4A);

class ConversationHistoryScreen extends StatefulWidget {
  const ConversationHistoryScreen({super.key});

  @override
  State<ConversationHistoryScreen> createState() =>
      _ConversationHistoryScreenState();
}

class _ConversationHistoryScreenState extends State<ConversationHistoryScreen> {
  Map<String, bool> _summaryExpanded = {};

  final List<Map<String, dynamic>> conversations = [
    {
      'id': '1',
      'date': '2024-12-15',
      'time': '14:30',
      'elder': '김할머니',
      'topic': '일상 대화',
      'sentiment': '긍정적',
      'duration': '15분',
      'type': 'call',
      'isUrgent': false,
      'summary': '김할머니와의 오늘 오후 통화에서 최근 일상에 대해 나누었습니다. 할머니께서는 건강하신 상태이며 기분이 좋으신 모습이었습니다. 손자/손녀 이야기와 집안일에 대해 주로 대화했습니다.',
    },
    {
      'id': '2',
      'date': '2024-12-15',
      'time': '09:45',
      'elder': '이할아버지',
      'topic': '건강 비정상 감지',
      'sentiment': '중립적',
      'duration': '10분',
      'type': 'chat',
      'isUrgent': true,
      'summary': '이할아버지의 혈압이 평소보다 높게 측정되었습니다. AI 분석 결과 약간의 스트레스 상태로 보입니다. 충분한 휴식과 수분 섭취를 권장했으며, 증상이 계속되면 병원 방문을 권했습니다.',
    },
    {
      'id': '3',
      'date': '2024-12-14',
      'time': '18:20',
      'elder': '김할머니',
      'topic': '추억 나누기',
      'sentiment': '긍정적',
      'duration': '25분',
      'type': 'call',
      'isUrgent': false,
      'summary': '김할머니와 좋은 추억들을 나누는 시간을 가졌습니다. 과거 가족 여행 경험과 어린 시절 이야기들을 함께 회상했습니다. 대화 중 할머니께서 매우 행복해하셨으며 감정 상태가 좋았습니다.',
    },
    {
      'id': '4',
      'date': '2024-12-14',
      'time': '11:15',
      'elder': '이할아버지',
      'topic': '약물 복용 알림',
      'sentiment': '중립적',
      'duration': '5분',
      'type': 'chat',
      'isUrgent': false,
      'summary': '이할아버지의 정기 약물 복용 알림 메시지입니다. 오전 11시 약물을 정상적으로 복용하셨음을 확인했습니다. 약물 부작용은 없으며 건강 상태는 안정적입니다.',
    },
  ];

  void _toggleSummary(String id) {
    setState(() {
      if (_summaryExpanded.containsKey(id)) {
        _summaryExpanded[id] = !_summaryExpanded[id]!;
      } else {
        _summaryExpanded[id] = true;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        title: Text(
          '대화 기록',
          style: GoogleFonts.notoSerifKr(
            fontSize: 24,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded, color: eInk),
          onPressed: () => Navigator.pop(context),
        ),
      ),
      body: SingleChildScrollView(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            children: conversations.map((conv) {
              Color sentimentColor = conv['sentiment'] == '긍정적'
                  ? const Color(0xFF4CAF50)
                  : conv['sentiment'] == '부정적'
                      ? const Color(0xFFF44336)
                      : const Color(0xFFFFA726);

              bool isUrgent = conv['isUrgent'] as bool? ?? false;
              String typeLabel = conv['type'] == 'call' ? '통화' : '채팅';
              Color typeColor =
                  conv['type'] == 'call' ? const Color(0xFF2196F3) : eAccent;
              String convId = conv['id'] as String;
              bool isSummaryExpanded = _summaryExpanded[convId] ?? false;

              return Container(
                margin: const EdgeInsets.only(bottom: 12),
                decoration: BoxDecoration(
                  color: eCard,
                  border: Border.all(
                    color: isUrgent ? const Color(0xFFF44336) : eLine,
                    width: isUrgent ? 2 : 1,
                  ),
                  borderRadius: BorderRadius.circular(12),
                  boxShadow: isUrgent
                      ? [
                          BoxShadow(
                            color: const Color(0xFFF44336).withOpacity(0.2),
                            blurRadius: 8,
                            spreadRadius: 1,
                          )
                        ]
                      : [],
                ),
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // 헤더
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Text(
                                  conv['elder'],
                                  style: GoogleFonts.notoSansKr(
                                    fontSize: 16,
                                    fontWeight: FontWeight.w700,
                                    color: eInk,
                                  ),
                                ),
                                if (isUrgent)
                                  Padding(
                                    padding: const EdgeInsets.only(left: 8),
                                    child: Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 6,
                                        vertical: 2,
                                      ),
                                      decoration: BoxDecoration(
                                        color: const Color(0xFFF44336),
                                        borderRadius: BorderRadius.circular(4),
                                      ),
                                      child: const Text(
                                        '긴급',
                                        style: TextStyle(
                                          fontSize: 10,
                                          fontWeight: FontWeight.w700,
                                          color: Colors.white,
                                        ),
                                      ),
                                    ),
                                  ),
                              ],
                            ),
                            const SizedBox(height: 4),
                            Text(
                              '${conv['date']} at ${conv['time']}',
                              style: const TextStyle(
                                fontSize: 12,
                                color: eInkSoft,
                              ),
                            ),
                          ],
                        ),
                        Row(
                          children: [
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 10,
                                vertical: 6,
                              ),
                              decoration: BoxDecoration(
                                color: typeColor.withOpacity(0.15),
                                borderRadius: BorderRadius.circular(6),
                              ),
                              child: Text(
                                typeLabel,
                                style: TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.w600,
                                  color: typeColor,
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 10,
                                vertical: 6,
                              ),
                              decoration: BoxDecoration(
                                color: sentimentColor.withOpacity(0.15),
                                borderRadius: BorderRadius.circular(6),
                              ),
                              child: Text(
                                conv['sentiment'],
                                style: TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.w600,
                                  color: sentimentColor,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),

                    // 기본 정보
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: eBg,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '주제: ${conv['topic']}',
                            style: GoogleFonts.notoSansKr(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                              color: eInk,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            '소요시간: ${conv['duration']}',
                            style: const TextStyle(
                              fontSize: 12,
                              color: eInkSoft,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 12),

                    // AI 요약 섹션
                    GestureDetector(
                      onTap: () => _toggleSummary(convId),
                      child: Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: eBrass.withOpacity(0.08),
                          border: Border.all(
                            color: eBrass.withOpacity(0.3),
                          ),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Row(
                                  children: [
                                    Icon(
                                      Icons.auto_awesome_rounded,
                                      color: eBrass,
                                      size: 18,
                                    ),
                                    const SizedBox(width: 8),
                                    Text(
                                      'AI 요약',
                                      style: GoogleFonts.notoSansKr(
                                        fontSize: 13,
                                        fontWeight: FontWeight.w700,
                                        color: eBrass,
                                      ),
                                    ),
                                  ],
                                ),
                                Icon(
                                  isSummaryExpanded
                                      ? Icons.expand_less_rounded
                                      : Icons.expand_more_rounded,
                                  color: eBrass,
                                  size: 20,
                                ),
                              ],
                            ),
                            if (isSummaryExpanded) ...[
                              const SizedBox(height: 8),
                              Text(
                                conv['summary'] as String,
                                style: GoogleFonts.notoSansKr(
                                  fontSize: 13,
                                  color: eInk,
                                  height: 1.5,
                                ),
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),

                    // 하단 버튼
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: () {
                              if (isUrgent) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  SnackBar(
                                    content: const Row(
                                      children: [
                                        Icon(Icons.warning_rounded,
                                            color: Colors.white),
                                        SizedBox(width: 12),
                                        Expanded(
                                          child:
                                              Text('긴급: 즉시 확인 필요합니다.'),
                                        ),
                                      ],
                                    ),
                                    backgroundColor:
                                        const Color(0xFFF44336),
                                    duration: const Duration(seconds: 3),
                                  ),
                                );
                              }
                              Navigator.push(
                                context,
                                MaterialPageRoute(
                                  builder: (context) =>
                                      ConversationDetailScreen(
                                    date: conv['date'] as String,
                                    time: conv['time'] as String,
                                    elder: conv['elder'] as String,
                                    topic: conv['topic'] as String,
                                    sentiment: conv['sentiment'] as String,
                                    duration: conv['duration'] as String,
                                    type: conv['type'] as String,
                                    isUrgent: isUrgent,
                                  ),
                                ),
                              );
                            },
                            icon:
                                const Icon(Icons.visibility_outlined, size: 18),
                            label: const Text('상세보기'),
                            style: OutlinedButton.styleFrom(
                              foregroundColor: eAccent,
                              side: const BorderSide(color: eAccent),
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: () {
                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(
                                  content: Text(
                                    '${conv['date']} ${conv['elder']}님과의 대화가 저장되었습니다.',
                                  ),
                                  backgroundColor: const Color(0xFF4CAF50),
                                  duration: const Duration(seconds: 2),
                                ),
                              );
                            },
                            icon:
                                const Icon(Icons.download_outlined, size: 18),
                            label: const Text('내보내기'),
                            style: OutlinedButton.styleFrom(
                              foregroundColor: eAccent,
                              side: const BorderSide(color: eAccent),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              );
            }).toList(),
          ),
        ),
      ),
    );
  }
}
