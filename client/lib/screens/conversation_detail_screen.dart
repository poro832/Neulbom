import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

const Color eBg = Color(0xFFFBF6ED);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);

class ConversationDetailScreen extends StatelessWidget {
  final String date;
  final String time;
  final String elder;
  final String topic;
  final String sentiment;
  final String duration;
  final String type;
  final bool isUrgent;

  const ConversationDetailScreen({
    super.key,
    required this.date,
    required this.time,
    required this.elder,
    required this.topic,
    required this.sentiment,
    required this.duration,
    required this.type,
    required this.isUrgent,
  });

  @override
  Widget build(BuildContext context) {
    // 감정에 따른 색상
    Color sentimentColor = sentiment == '긍정적'
        ? const Color(0xFF4CAF50)
        : sentiment == '부정적'
            ? const Color(0xFFF44336)
            : const Color(0xFFFFA726);

    String typeLabel = type == 'call' ? '통화' : '채팅';
    Color typeColor = type == 'call' ? const Color(0xFF2196F3) : eAccent;

    // 샘플 대화 내용
    final conversationMessages = [
      {
        'type': 'user',
        'time': '14:30:15',
        'content': '안녕하세요, 오늘 기분 어떠신가요?',
      },
      {
        'type': 'elder',
        'time': '14:30:45',
        'content': '네, 오늘은 날씨도 좋고 기분이 정말 좋아요.',
      },
      {
        'type': 'user',
        'time': '14:31:20',
        'content': '그렇군요! 좋은 소식이에요. 요즘 건강은 어떠신가요?',
      },
      {
        'type': 'elder',
        'time': '14:32:00',
        'content': '네, 특별한 불편함은 없어요. 다만 요즘 밤에 자주 깨긴 해요.',
      },
      {
        'type': 'user',
        'time': '14:32:45',
        'content': '수면에 문제가 있으신 것 같네요. 전문의와 상담해보시는 것도 좋을 것 같습니다.',
      },
      {
        'type': 'elder',
        'time': '14:33:30',
        'content': '좋은 조언 감사합니다. 곧 병원에 가볼게요.',
      },
    ];

    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        title: Text(
          '대화 상세보기',
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
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 기본 정보
              Container(
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
                    if (isUrgent)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 8,
                          ),
                          decoration: BoxDecoration(
                            color: const Color(0xFFF44336).withOpacity(0.1),
                            border: Border.all(color: const Color(0xFFF44336)),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Row(
                            children: [
                              const Icon(
                                Icons.warning_rounded,
                                color: Color(0xFFF44336),
                                size: 20,
                              ),
                              const SizedBox(width: 8),
                              const Expanded(
                                child: Text(
                                  '긴급 상황 - 즉시 확인 필요합니다.',
                                  style: TextStyle(
                                    fontSize: 13,
                                    fontWeight: FontWeight.w700,
                                    color: Color(0xFFF44336),
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              elder,
                              style: GoogleFonts.notoSansKr(
                                fontSize: 18,
                                fontWeight: FontWeight.w700,
                                color: eInk,
                              ),
                            ),
                            const SizedBox(height: 8),
                            Text(
                              '$date $time',
                              style: const TextStyle(
                                fontSize: 13,
                                color: eInkSoft,
                              ),
                            ),
                          ],
                        ),
                        Column(
                          children: [
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 12,
                                vertical: 6,
                              ),
                              decoration: BoxDecoration(
                                color: typeColor.withOpacity(0.15),
                                borderRadius: BorderRadius.circular(6),
                              ),
                              child: Text(
                                typeLabel,
                                style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                  color: typeColor,
                                ),
                              ),
                            ),
                            const SizedBox(height: 8),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 12,
                                vertical: 6,
                              ),
                              decoration: BoxDecoration(
                                color: sentimentColor.withOpacity(0.15),
                                borderRadius: BorderRadius.circular(6),
                              ),
                              child: Text(
                                sentiment,
                                style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                  color: sentimentColor,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '주제',
                                style: TextStyle(
                                  fontSize: 12,
                                  color: eInkSoft,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                topic,
                                style: GoogleFonts.notoSansKr(
                                  fontSize: 14,
                                  fontWeight: FontWeight.w600,
                                  color: eInk,
                                ),
                              ),
                            ],
                          ),
                        ),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '소요시간',
                                style: TextStyle(
                                  fontSize: 12,
                                  color: eInkSoft,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                duration,
                                style: GoogleFonts.notoSansKr(
                                  fontSize: 14,
                                  fontWeight: FontWeight.w600,
                                  color: eInk,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),

              // 대화 내용
              Text(
                '대화 내용',
                style: GoogleFonts.notoSerifKr(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 16),
              Container(
                decoration: BoxDecoration(
                  color: eCard,
                  border: Border.all(color: eLine),
                  borderRadius: BorderRadius.circular(12),
                ),
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: conversationMessages.map((msg) {
                    bool isUser = msg['type'] == 'user';
                    return Column(
                      children: [
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Container(
                              width: 36,
                              height: 36,
                              decoration: BoxDecoration(
                                shape: BoxShape.circle,
                                color: isUser ? eAccent : eLine,
                              ),
                              child: Center(
                                child: Text(
                                  isUser ? '지원' : '어르신',
                                  textAlign: TextAlign.center,
                                  style: TextStyle(
                                    fontSize: 10,
                                    fontWeight: FontWeight.w600,
                                    color: isUser ? Colors.white : eInkSoft,
                                  ),
                                ),
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    '${isUser ? 'AI 지원' : elder} • ${msg['time']}',
                                    style: TextStyle(
                                      fontSize: 11,
                                      color: eInkSoft,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                  const SizedBox(height: 6),
                                  Container(
                                    decoration: BoxDecoration(
                                      color: isUser
                                          ? eAccent.withOpacity(0.1)
                                          : eLine.withOpacity(0.5),
                                      borderRadius: BorderRadius.circular(10),
                                    ),
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 12,
                                      vertical: 10,
                                    ),
                                    child: Text(
                                      msg['content'] as String,
                                      style: const TextStyle(
                                        fontSize: 13,
                                        color: eInk,
                                        height: 1.5,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                        if (conversationMessages.indexOf(msg) <
                            conversationMessages.length - 1)
                          const SizedBox(height: 16),
                      ],
                    );
                  }).toList(),
                ),
              ),
              const SizedBox(height: 24),

              // 분석 결과
              Text(
                '대화 분석',
                style: GoogleFonts.notoSerifKr(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),
              Container(
                decoration: BoxDecoration(
                  color: sentimentColor.withOpacity(0.08),
                  border: Border.all(
                    color: sentimentColor.withOpacity(0.2),
                  ),
                  borderRadius: BorderRadius.circular(12),
                ),
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(
                          Icons.mood_rounded,
                          color: sentimentColor,
                          size: 24,
                        ),
                        const SizedBox(width: 12),
                        Text(
                          '감정 상태',
                          style: GoogleFonts.notoSansKr(
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                            color: eInk,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Text(
                      '어르신이 긍정적인 감정으로 대화를 진행했으며, 건강에 대한 관심을 보였습니다. 수면 문제를 언급했지만 전문의 상담에 대해 긍정적인 반응을 보였습니다.',
                      style: TextStyle(
                        fontSize: 13,
                        color: eInkSoft,
                        height: 1.6,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
