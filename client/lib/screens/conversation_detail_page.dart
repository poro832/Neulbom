import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

const Color eBg = Color(0xFFFBF6ED);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);
const Color eAccentSoft = Color(0xFFFBE4D3);

class ConversationDetailPage extends StatefulWidget {
  final int elderlyId;
  final String elderlyName;

  const ConversationDetailPage({
    super.key,
    required this.elderlyId,
    required this.elderlyName,
  });

  @override
  State<ConversationDetailPage> createState() => _ConversationDetailPageState();
}

class _ConversationDetailPageState extends State<ConversationDetailPage> {
  late String _selectedDate;

  // Mock 날짜별 대화 데이터
  final Map<String, List<Map<String, dynamic>>> _conversationsByDate = {
    '2024-12-15': [
      {
        'time': '09:30',
        'elderly': '오늘 날씨가 정말 좋네요',
        'ai': '정말 그렇네요! 이렇게 좋은 날씨에는 밖에서 활동하는 것이 건강에 정말 좋습니다.',
        'hasAudio': true,
        'duration': '2분 15초',
      },
      {
        'time': '14:15',
        'elderly': '손주가 만났다고 얘기해주면 좋겠어요',
        'ai': '가족과의 시간은 정말 소중하지요. 즐거운 대화가 되시기를 바랍니다.',
        'hasAudio': true,
        'duration': '3분 42초',
      },
      {
        'time': '18:45',
        'elderly': 'AI 친구와 통화했습니다',
        'ai': '오늘 하루 정말 활동적이셨네요. 건강한 생활을 축하드립니다!',
        'hasAudio': true,
        'duration': '1분 58초',
      },
    ],
    '2024-12-14': [
      {
        'time': '10:15',
        'elderly': '좀 피곤해요',
        'ai': '충분한 휴식이 필요할 것 같네요. 천천히 쉬시고 가벼운 활동부터 시작해보세요.',
        'hasAudio': true,
        'duration': '2분 30초',
      },
      {
        'time': '16:30',
        'elderly': '산책하고 기분이 좋아졌어요',
        'ai': '산책은 정말 마음을 편하게 해주는 좋은 활동이네요. 계속 이렇게 활동해주세요!',
        'hasAudio': true,
        'duration': '2분 05초',
      },
    ],
    '2024-12-13': [
      {
        'time': '09:00',
        'elderly': '손자가 방문했어요',
        'ai': '가족과 함께하는 시간이 최고의 보약이네요! 소중한 순간들 많이 만드세요.',
        'hasAudio': true,
        'duration': '4분 12초',
      },
      {
        'time': '14:30',
        'elderly': '오늘 정말 행복해요',
        'ai': '그런 모습을 들으니 저도 기쁘네요. 계속 행복한 나날이 되기를 바랍니다.',
        'hasAudio': true,
        'duration': '2분 48초',
      },
    ],
  };

  @override
  void initState() {
    super.initState();
    _selectedDate = _conversationsByDate.keys.first;
  }

  @override
  Widget build(BuildContext context) {
    final selectedConversations = _conversationsByDate[_selectedDate] ?? [];

    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        leading: IconButton(
          icon: Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: Colors.white,
              border: Border.all(color: eLine, width: 2),
              boxShadow: [
                BoxShadow(
                  color: eInk.withOpacity(0.1),
                  blurRadius: 6,
                  spreadRadius: 1,
                ),
              ],
            ),
            child: const Icon(Icons.chevron_left, color: eInk, size: 24),
          ),
          onPressed: () => Navigator.pop(context),
          padding: EdgeInsets.zero,
          constraints: const BoxConstraints(
            minWidth: 44,
            minHeight: 44,
          ),
        ),
        title: Text(
          '${widget.elderlyName} - 상세 대화기록',
          style: GoogleFonts.notoSerifKr(
            fontSize: 18,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        centerTitle: false,
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 날짜 선택 탭
                Text(
                  '날짜 선택',
                  style: GoogleFonts.notoSerifKr(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                  ),
                ),
                const SizedBox(height: 12),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: _conversationsByDate.keys.map((date) {
                      final isSelected = _selectedDate == date;
                      return Padding(
                        padding: const EdgeInsets.only(right: 10),
                        child: GestureDetector(
                          onTap: () {
                            setState(() {
                              _selectedDate = date;
                            });
                          },
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 16,
                              vertical: 10,
                            ),
                            decoration: BoxDecoration(
                              color: isSelected ? eAccent : eCard,
                              border: Border.all(
                                color: isSelected ? eAccent : eLine,
                                width: 2,
                              ),
                              borderRadius: BorderRadius.circular(20),
                            ),
                            child: Text(
                              date,
                              style: GoogleFonts.notoSansKr(
                                fontSize: 14,
                                fontWeight: FontWeight.w600,
                                color: isSelected ? Colors.white : eInk,
                              ),
                            ),
                          ),
                        ),
                      );
                    }).toList(),
                  ),
                ),
                const SizedBox(height: 28),

                // 선택된 날짜의 대화 기록
                Text(
                  '$_selectedDate 대화기록',
                  style: GoogleFonts.notoSerifKr(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                  ),
                ),
                const SizedBox(height: 14),

                // 대화 목록
                ...selectedConversations
                    .map((conv) => Padding(
                          padding: const EdgeInsets.only(bottom: 16),
                          child: Container(
                            decoration: BoxDecoration(
                              color: eCard,
                              border: Border.all(color: eLine),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            padding: const EdgeInsets.all(14),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                // 시간
                                Text(
                                  conv['time'] as String,
                                  style: TextStyle(
                                    fontSize: 12,
                                    color: eInkSoft,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                const SizedBox(height: 10),

                                // 어르신 발언
                                Container(
                                  padding: const EdgeInsets.all(10),
                                  decoration: BoxDecoration(
                                    color: Colors.white,
                                    border: Border.all(color: eLine),
                                    borderRadius: BorderRadius.circular(8),
                                  ),
                                  child: Text(
                                    '어르신: ${conv['elderly']}',
                                    style: const TextStyle(
                                      fontSize: 13,
                                      color: eInk,
                                      fontWeight: FontWeight.w500,
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 8),

                                // AI 응답
                                Container(
                                  padding: const EdgeInsets.all(10),
                                  decoration: BoxDecoration(
                                    color: eAccentSoft,
                                    border: Border.all(color: eLine),
                                    borderRadius: BorderRadius.circular(8),
                                  ),
                                  child: Text(
                                    'AI 친구: ${conv['ai']}',
                                    style: const TextStyle(
                                      fontSize: 13,
                                      color: Color(0xFF8B4A2A),
                                      fontWeight: FontWeight.w500,
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 12),

                                // 음성 다운로드 버튼
                                if (conv['hasAudio'] as bool)
                                  Row(
                                    children: [
                                      Expanded(
                                        child: Container(
                                          padding: const EdgeInsets.symmetric(
                                            horizontal: 12,
                                            vertical: 10,
                                          ),
                                          decoration: BoxDecoration(
                                            color: eAccent.withOpacity(0.1),
                                            borderRadius:
                                                BorderRadius.circular(8),
                                            border: Border.all(
                                              color: eAccent.withOpacity(0.3),
                                            ),
                                          ),
                                          child: Row(
                                            mainAxisAlignment:
                                                MainAxisAlignment.center,
                                            children: [
                                              Icon(
                                                Icons.download_rounded,
                                                color: eAccent,
                                                size: 18,
                                              ),
                                              const SizedBox(width: 6),
                                              Text(
                                                '음성 다운로드 (${conv['duration']})',
                                                style: GoogleFonts.notoSansKr(
                                                  fontSize: 12,
                                                  fontWeight:
                                                      FontWeight.w600,
                                                  color: eAccent,
                                                ),
                                              ),
                                            ],
                                          ),
                                        ),
                                      ),
                                    ],
                                  ),
                              ],
                            ),
                          ),
                        ))
                    .toList(),

                if (selectedConversations.isEmpty)
                  Center(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 40),
                      child: Text(
                        '선택한 날짜에 대화 기록이 없습니다.',
                        style: TextStyle(
                          fontSize: 14,
                          color: eInkSoft,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
