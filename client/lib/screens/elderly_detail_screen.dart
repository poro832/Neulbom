import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'conversation_detail_page.dart';

const Color eBg = Color(0xFFFBF6ED);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);

class ElderlyDetailScreen extends StatefulWidget {
  final int elderlyId;
  final String elderlyName;

  const ElderlyDetailScreen({
    super.key,
    required this.elderlyId,
    required this.elderlyName,
  });

  @override
  State<ElderlyDetailScreen> createState() => _ElderlyDetailScreenState();
}

class _ElderlyDetailScreenState extends State<ElderlyDetailScreen> {
  String _selectedDate = _todayKey();
  String _reportPeriod = 'daily';
  DateTime _periodDate = DateTime.now();

  static String _todayKey() => _dateKey(DateTime.now());

  static String _dateKey(DateTime date) {
    final month = date.month.toString().padLeft(2, '0');
    final day = date.day.toString().padLeft(2, '0');
    return '${date.year}-$month-$day';
  }

  String _formatKoreanDate(DateTime date) {
    return '${date.year}년 ${date.month}월 ${date.day}일';
  }

  DateTime _weekStart(DateTime date) {
    final day = DateTime(date.year, date.month, date.day);
    return day.subtract(Duration(days: day.weekday % 7));
  }

  String _weeklyRangeLabel() {
    final sunday = _weekStart(_periodDate);
    final saturday = sunday.add(const Duration(days: 6));
    return '${_formatKoreanDate(sunday)} ~ ${_formatKoreanDate(saturday)}';
  }

  String _monthlyLabel() {
    return '${_periodDate.year}년 ${_periodDate.month}월';
  }

  Future<DateTime?> _showReportDatePicker(DateTime initialDate) {
    final now = DateTime.now();
    final lastDate = DateTime(now.year, now.month, now.day);
    final firstDate = DateTime(2024, 1, 1);
    var safeInitial = initialDate;
    if (safeInitial.isAfter(lastDate)) {
      safeInitial = lastDate;
    } else if (safeInitial.isBefore(firstDate)) {
      safeInitial = firstDate;
    }

    return showDatePicker(
      context: context,
      initialDate: safeInitial,
      firstDate: firstDate,
      lastDate: lastDate,
      locale: const Locale('ko', 'KR'),
      builder: (context, child) {
        return Theme(
          data: Theme.of(context).copyWith(
            colorScheme: const ColorScheme.light(
              primary: eAccent,
              onPrimary: Colors.white,
              onSurface: eInk,
            ),
            textTheme: Theme.of(
              context,
            ).textTheme.apply(fontFamily: 'NotoSansKR'),
          ),
          child: Localizations.override(
            context: context,
            locale: const Locale('ko', 'KR'),
            child: child!,
          ),
        );
      },
    );
  }

  Future<DateTime?> _showMonthPicker(DateTime initialDate) {
    var selectedYear = initialDate.year;
    final now = DateTime.now();
    const firstYear = 2024;

    return showDialog<DateTime>(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return Dialog(
              backgroundColor: eCard,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
              ),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Row(
                      children: [
                        IconButton(
                          onPressed: selectedYear <= firstYear
                              ? null
                              : () => setDialogState(() => selectedYear--),
                          icon: const Icon(Icons.chevron_left_rounded),
                          color: eInk,
                        ),
                        Expanded(
                          child: Text(
                            '$selectedYear년',
                            textAlign: TextAlign.center,
                            style: GoogleFonts.notoSansKr(
                              fontSize: 18,
                              fontWeight: FontWeight.w700,
                              color: eInk,
                            ),
                          ),
                        ),
                        IconButton(
                          onPressed: selectedYear >= now.year
                              ? null
                              : () => setDialogState(() => selectedYear++),
                          icon: const Icon(Icons.chevron_right_rounded),
                          color: eInk,
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    GridView.builder(
                      shrinkWrap: true,
                      itemCount: 12,
                      physics: const NeverScrollableScrollPhysics(),
                      gridDelegate:
                          const SliverGridDelegateWithFixedCrossAxisCount(
                            crossAxisCount: 3,
                            mainAxisSpacing: 8,
                            crossAxisSpacing: 8,
                            childAspectRatio: 1.6,
                          ),
                      itemBuilder: (context, index) {
                        final month = index + 1;
                        final isFutureMonth =
                            selectedYear == now.year && month > now.month;
                        final isSelected =
                            selectedYear == initialDate.year &&
                            month == initialDate.month;
                        return Material(
                          color: isSelected
                              ? eAccent
                              : isFutureMonth
                              ? eLine.withValues(alpha: 0.4)
                              : eBg,
                          borderRadius: BorderRadius.circular(10),
                          child: InkWell(
                            borderRadius: BorderRadius.circular(10),
                            onTap: isFutureMonth
                                ? null
                                : () => Navigator.pop(
                                    context,
                                    DateTime(selectedYear, month),
                                  ),
                            child: Center(
                              child: Text(
                                '$month월',
                                style: GoogleFonts.notoSansKr(
                                  fontSize: 15,
                                  fontWeight: FontWeight.w600,
                                  color: isSelected
                                      ? Colors.white
                                      : isFutureMonth
                                      ? eInkSoft
                                      : eInk,
                                ),
                              ),
                            ),
                          ),
                        );
                      },
                    ),
                    Align(
                      alignment: Alignment.centerRight,
                      child: TextButton(
                        onPressed: () => Navigator.pop(context),
                        child: Text(
                          '취소',
                          style: GoogleFonts.notoSansKr(
                            fontWeight: FontWeight.w600,
                            color: eInkSoft,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  Future<DateTime?> _showWeekPicker(DateTime initialDate) {
    var visibleMonth = DateTime(initialDate.year, initialDate.month);
    final selectedWeekStart = _weekStart(initialDate);
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final firstDate = DateTime(2024, 1, 1);
    const weekdays = ['일', '월', '화', '수', '목', '금', '토'];

    return showDialog<DateTime>(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            final monthStart = DateTime(visibleMonth.year, visibleMonth.month, 1);
            final gridStart = _weekStart(monthStart);
            final canGoPrev =
                visibleMonth.isAfter(DateTime(firstDate.year, firstDate.month));
            final canGoNext =
                visibleMonth.isBefore(DateTime(today.year, today.month));

            return Dialog(
              backgroundColor: eCard,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
              ),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(12, 16, 12, 8),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Row(
                      children: [
                        IconButton(
                          onPressed: canGoPrev
                              ? () => setDialogState(() {
                                  visibleMonth = DateTime(
                                    visibleMonth.year,
                                    visibleMonth.month - 1,
                                  );
                                })
                              : null,
                          icon: const Icon(Icons.chevron_left_rounded),
                          color: eInk,
                        ),
                        Expanded(
                          child: Text(
                            '${visibleMonth.year}년 ${visibleMonth.month}월',
                            textAlign: TextAlign.center,
                            style: GoogleFonts.notoSansKr(
                              fontSize: 18,
                              fontWeight: FontWeight.w700,
                              color: eInk,
                            ),
                          ),
                        ),
                        IconButton(
                          onPressed: canGoNext
                              ? () => setDialogState(() {
                                  visibleMonth = DateTime(
                                    visibleMonth.year,
                                    visibleMonth.month + 1,
                                  );
                                })
                              : null,
                          icon: const Icon(Icons.chevron_right_rounded),
                          color: eInk,
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        for (final weekday in weekdays)
                          Expanded(
                            child: Text(
                              weekday,
                              textAlign: TextAlign.center,
                              style: GoogleFonts.notoSansKr(
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                                color: eInkSoft,
                              ),
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    for (var week = 0; week < 6; week++)
                      Builder(
                        builder: (context) {
                          final weekDays = [
                            for (var day = 0; day < 7; day++)
                              gridStart.add(Duration(days: week * 7 + day)),
                          ];
                          final weekStart = weekDays.first;
                          final weekEnd = weekDays.last;
                          final isSelected = weekStart == selectedWeekStart;
                          final isFutureWeek = weekStart.isAfter(today);
                          final isTooOld = weekEnd.isBefore(firstDate);
                          final enabled = !isFutureWeek && !isTooOld;

                          return Padding(
                            padding: const EdgeInsets.only(bottom: 4),
                            child: Material(
                              color: isSelected
                                  ? eAccent
                                  : enabled
                                  ? eBg
                                  : eLine.withValues(alpha: 0.4),
                              borderRadius: BorderRadius.circular(10),
                              child: InkWell(
                                borderRadius: BorderRadius.circular(10),
                                onTap: enabled
                                    ? () => Navigator.pop(context, weekStart)
                                    : null,
                                child: Padding(
                                  padding: const EdgeInsets.symmetric(
                                    vertical: 8,
                                  ),
                                  child: Row(
                                    children: [
                                      for (final day in weekDays)
                                        Expanded(
                                          child: Text(
                                            '${day.day}',
                                            textAlign: TextAlign.center,
                                            style: GoogleFonts.notoSansKr(
                                              fontSize: 14,
                                              fontWeight: FontWeight.w600,
                                              color: isSelected
                                                  ? Colors.white
                                                  : !enabled ||
                                                        day.month !=
                                                            visibleMonth.month
                                                  ? eInkSoft
                                                  : eInk,
                                            ),
                                          ),
                                        ),
                                    ],
                                  ),
                                ),
                              ),
                            ),
                          );
                        },
                      ),
                    Align(
                      alignment: Alignment.centerRight,
                      child: TextButton(
                        onPressed: () => Navigator.pop(context),
                        child: Text(
                          '취소',
                          style: GoogleFonts.notoSansKr(
                            fontWeight: FontWeight.w600,
                            color: eInkSoft,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  Widget _buildDateSelector({
    required String dateText,
    required VoidCallback onTap,
  }) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        decoration: BoxDecoration(
          color: eCard,
          border: Border.all(color: eAccent, width: 2),
          borderRadius: BorderRadius.circular(12),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            const Icon(Icons.calendar_today_rounded, color: eAccent),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                dateText,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: GoogleFonts.notoSansKr(
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                  color: eInk,
                ),
              ),
            ),
            const Icon(
              Icons.arrow_forward_ios_rounded,
              size: 16,
              color: eAccent,
            ),
          ],
        ),
      ),
    );
  }

  // 날짜별 더미 데이터
  final Map<String, Map<String, dynamic>> _conversationData = {
    '2024-12-15': {
      'summary':
          '오늘 오전 9시 30분부터 저녁 6시 45분까지 약 9시간 동안 총 3회의 대화가 이루어졌습니다. 아침에는 날씨가 좋다며 긍정적인 감정으로 하루를 시작했고, 낮 시간에는 손주를 만나고 싶은 마음을 표현했습니다. 저녁에는 AI 친구와의 통화로 활발한 상호작용을 보였습니다.',
      'depressionIndex': '2.4/10',
      'depressionStatus': '정상',
      'conversationCount': '3회',
      'conversationStatus': '활발함',
      'activityStatus': '정상',
      'activitySteps': '7,245걸음',
      'healthStatus': '정상',
      'healthDetail': '이상 없음',
      'conversations': [
        {
          'time': '09:30',
          'content': '오늘 날씨가 정말 좋네요',
          'sentiment': '긍정적',
          'aiResponse': '정말 그렇네요! 이렇게 좋은 날씨에는 밖에서 활동하는 것이 건강에 정말 좋습니다.',
        },
        {
          'time': '14:15',
          'content': '손주가 만났다고 얘기해주면 좋겠어요',
          'sentiment': '중립적',
          'aiResponse': '가족과의 시간은 정말 소중하지요. 즐거운 대화가 되시기를 바랍니다.',
        },
        {
          'time': '18:45',
          'content': 'AI 친구와 통화했습니다',
          'sentiment': '긍정적',
          'aiResponse': '오늘 하루 정말 활동적이셨네요. 건강한 생활을 축하드립니다!',
        },
      ],
    },
    '2024-12-14': {
      'summary':
          '어제는 오전 10시부터 오후 4시까지 약 6시간 동안 2회의 대화가 있었습니다. 아침에는 다소 조용한 모습을 보였으나, 오후에 활동적인 대화를 나누며 기분이 좋아졌습니다. 수면이 충분했으며 활동량도 적절한 상태입니다.',
      'depressionIndex': '3.1/10',
      'depressionStatus': '정상',
      'conversationCount': '2회',
      'conversationStatus': '정상',
      'activityStatus': '정상',
      'activitySteps': '5,800걸음',
      'healthStatus': '정상',
      'healthDetail': '이상 없음',
      'conversations': [
        {
          'time': '10:15',
          'content': '좀 피곤해요',
          'sentiment': '중립적',
          'aiResponse': '충분한 휴식이 필요할 것 같네요. 천천히 쉬시고 가벼운 활동부터 시작해보세요.',
        },
        {
          'time': '16:30',
          'content': '산책하고 기분이 좋아졌어요',
          'sentiment': '긍정적',
          'aiResponse': '산책은 정말 마음을 편하게 해주는 좋은 활동이네요. 계속 이렇게 활동해주세요!',
        },
      ],
    },
    '2024-12-13': {
      'summary':
          '2일 전에는 오전 9시부터 저녁 8시까지 총 4회의 대화가 이루어졌습니다. 하루 종일 활발한 상호작용을 보였으며, 특히 손자와의 대화 시간이 길었습니다. 전반적으로 긍정적인 감정 상태를 유지했습니다.',
      'depressionIndex': '2.0/10',
      'depressionStatus': '정상',
      'conversationCount': '4회',
      'conversationStatus': '매우 활발함',
      'activityStatus': '활동적',
      'activitySteps': '9,120걸음',
      'healthStatus': '정상',
      'healthDetail': '이상 없음',
      'conversations': [
        {'time': '09:00', 'content': '손자가 방문했어요', 'sentiment': '매우긍정적'},
        {'time': '11:45', 'content': '함께 점심을 먹었습니다', 'sentiment': '긍정적'},
        {'time': '15:20', 'content': '같이 산책했어요', 'sentiment': '긍정적'},
        {'time': '19:30', 'content': '함께 저녁을 먹고 헤어졌어요', 'sentiment': '긍정적'},
      ],
    },
  };

  Widget _buildReportSelector() {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: eCard,
        border: Border.all(color: eLine),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          _buildReportPeriodButton('daily', '일간'),
          _buildReportPeriodButton('weekly', '주간'),
          _buildReportPeriodButton('monthly', '월간'),
        ],
      ),
    );
  }

  Widget _buildReportPeriodButton(String period, String label) {
    final isSelected = _reportPeriod == period;
    return Expanded(
      child: GestureDetector(
        onTap: () => setState(() => _reportPeriod = period),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 4),
          decoration: BoxDecoration(
            color: isSelected ? eAccent : Colors.transparent,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            label,
            textAlign: TextAlign.center,
            style: GoogleFonts.notoSansKr(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: isSelected ? Colors.white : eInkSoft,
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildPeriodReport() {
    final isWeekly = _reportPeriod == 'weekly';
    final rangeLabel = isWeekly ? _weeklyRangeLabel() : _monthlyLabel();
    final monthLabel = _monthlyLabel();

    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        title: Text(
          '${widget.elderlyName} 건강 리포트',
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
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildReportSelector(),
            const SizedBox(height: 16),
            _buildDateSelector(
              dateText: isWeekly ? _weeklyRangeLabel() : _monthlyLabel(),
              onTap: () async {
                final picked = isWeekly
                    ? await _showWeekPicker(_periodDate)
                    : await _showMonthPicker(_periodDate);
                if (picked != null) {
                  setState(() => _periodDate = picked);
                }
              },
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: _buildStatCard(
                    title: '우울 수치',
                    value: isWeekly ? '2.8/10' : '2.6/10',
                    subtitle: '정상',
                    color: const Color(0xFF4CAF50),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _buildStatCard(
                    title: '대화 횟수',
                    value: isWeekly ? '12회' : '48회',
                    subtitle: isWeekly ? '주간 합계' : '월간 합계',
                    color: eAccent,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _buildStatCard(
                    title: '건강상태',
                    value: '정상',
                    subtitle: '이상 없음',
                    color: const Color(0xFF4CAF50),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 24),
            Text(
              isWeekly ? '주간 분석 요약' : '월간 분석 요약',
              style: GoogleFonts.notoSerifKr(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: eInk,
              ),
            ),
            const SizedBox(height: 12),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: eAccent.withOpacity(0.08),
                border: Border.all(color: eAccent.withOpacity(0.2)),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                isWeekly
                    ? '$rangeLabel 기간 동안 ${widget.elderlyName}님은 꾸준히 대화에 참여했고, 활동량과 감정 상태가 안정적으로 유지되었습니다.'
                    : '$monthLabel ${widget.elderlyName}님은 규칙적인 대화와 활동을 이어갔으며 전반적인 건강 상태가 양호합니다.',
                style: const TextStyle(fontSize: 14, color: eInk, height: 1.8),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_reportPeriod != 'daily') {
      return _buildPeriodReport();
    }

    // 선택한 날짜의 데이터 가져오기
    final data =
        _conversationData[_selectedDate] ?? _conversationData['2024-12-15']!;
    final conversations = data['conversations'] as List<Map<String, String>>;
    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        title: Text(
          '${widget.elderlyName} 건강 리포트',
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
              _buildReportSelector(),
              const SizedBox(height: 16),

              // 날짜 선택
              _buildDateSelector(
                dateText: _selectedDate,
                onTap: () async {
                  final picked = await _showReportDatePicker(
                    DateTime.parse(_selectedDate),
                  );
                  if (picked != null) {
                    setState(() => _selectedDate = _dateKey(picked));
                  }
                },
              ),
              const SizedBox(height: 24),

              // 통계 제목
              Text(
                '오늘의 통계',
                style: GoogleFonts.notoSerifKr(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),

              // 통계 그리드
              Row(
                children: [
                  Expanded(
                    child: _buildStatCard(
                      title: '우울 수치',
                      value: data['depressionIndex'],
                      subtitle: data['depressionStatus'],
                      color: const Color(0xFF4CAF50),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: _buildStatCard(
                      title: '대화 횟수',
                      value: data['conversationCount'],
                      subtitle: data['conversationStatus'],
                      color: eAccent,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: _buildStatCard(
                      title: '건강상태',
                      value: data['healthStatus'],
                      subtitle: data['healthDetail'],
                      color: const Color(0xFF4CAF50),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 24),

              // 전체 대화 요약
              Text(
                '오늘의 대화 요약',
                style: GoogleFonts.notoSerifKr(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),
              Container(
                decoration: BoxDecoration(
                  color: eAccent.withOpacity(0.08),
                  border: Border.all(color: eAccent.withOpacity(0.2)),
                  borderRadius: BorderRadius.circular(12),
                ),
                padding: const EdgeInsets.all(16),
                child: Text(
                  data['summary'],
                  style: TextStyle(
                    fontSize: 14,
                    color: eInk,
                    height: 1.8,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ),
              const SizedBox(height: 24),

              // 대화 내용
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    '시간별 대화 기록',
                    style: GoogleFonts.notoSerifKr(
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                      color: eInk,
                    ),
                  ),
                  GestureDetector(
                    onTap: () {
                      Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (context) => ConversationDetailPage(
                            elderlyId: widget.elderlyId,
                            elderlyName: widget.elderlyName,
                          ),
                        ),
                      );
                    },
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 8,
                      ),
                      decoration: BoxDecoration(
                        color: eAccent,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        '상세보기',
                        style: GoogleFonts.notoSansKr(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: Colors.white,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Container(
                decoration: BoxDecoration(
                  color: eCard,
                  border: Border.all(color: eLine),
                  borderRadius: BorderRadius.circular(12),
                ),
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    ...List.generate(
                      conversations.length,
                      (index) => Column(
                        children: [
                          _buildConversationItem(
                            time: conversations[index]['time']!,
                            content: conversations[index]['content']!,
                            sentiment: conversations[index]['sentiment']!,
                            aiResponse:
                                conversations[index]['aiResponse'] as String?,
                          ),
                          if (index < conversations.length - 1)
                            const SizedBox(height: 12),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),

              // 상태 분석
              Text(
                '상태 분석',
                style: GoogleFonts.notoSerifKr(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),
              Container(
                decoration: BoxDecoration(
                  color: data['depressionStatus'] == '정상'
                      ? const Color(0xFF4CAF50).withOpacity(0.1)
                      : const Color(0xFFFFA726).withOpacity(0.1),
                  border: Border.all(
                    color: data['depressionStatus'] == '정상'
                        ? const Color(0xFF4CAF50).withOpacity(0.3)
                        : const Color(0xFFFFA726).withOpacity(0.3),
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
                          data['depressionStatus'] == '정상'
                              ? Icons.check_circle_outline_rounded
                              : Icons.warning_amber_rounded,
                          color: data['depressionStatus'] == '정상'
                              ? const Color(0xFF4CAF50)
                              : const Color(0xFFFFA726),
                          size: 24,
                        ),
                        const SizedBox(width: 12),
                        Text(
                          data['depressionStatus'] == '정상' ? '정상 상태' : '주의 필요',
                          style: GoogleFonts.notoSansKr(
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                            color: data['depressionStatus'] == '정상'
                                ? const Color(0xFF4CAF50)
                                : const Color(0xFFFFA726),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Text(
                      data['depressionStatus'] == '정상'
                          ? '• 대화 활동이 활발함\n• 수면 시간이 충분함\n• 특이사항 없음'
                          : '• 우울 수치 증가\n• 활동량 감소 주의\n• 보호자 연락 권장',
                      style: const TextStyle(
                        fontSize: 14,
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

  Widget _buildStatCard({
    required String title,
    required String value,
    required String subtitle,
    required Color color,
  }) {
    return Container(
      decoration: BoxDecoration(
        color: eCard,
        border: Border.all(color: eLine),
        borderRadius: BorderRadius.circular(12),
      ),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 12,
              color: eInkSoft,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            value,
            style: GoogleFonts.notoSansKr(
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: color,
            ),
          ),
          const SizedBox(height: 4),
          Text(subtitle, style: const TextStyle(fontSize: 12, color: eInkSoft)),
        ],
      ),
    );
  }

  Widget _buildConversationItem({
    required String time,
    required String content,
    required String sentiment,
    String? aiResponse,
  }) {
    Color sentimentColor = sentiment == '긍정적'
        ? const Color(0xFF4CAF50)
        : sentiment == '부정적'
        ? const Color(0xFFF44336)
        : const Color(0xFFFFA726);

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          time,
          style: const TextStyle(
            fontSize: 12,
            color: eInkSoft,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 어르신 발언
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: Colors.white,
                  border: Border.all(color: eLine),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '어르신: $content',
                      style: const TextStyle(
                        fontSize: 13,
                        color: eInk,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 2,
                      ),
                      decoration: BoxDecoration(
                        color: sentimentColor.withOpacity(0.15),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        sentiment,
                        style: TextStyle(
                          fontSize: 11,
                          color: sentimentColor,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
              // AI 응답
              if (aiResponse != null)
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFBE4D3),
                    border: Border.all(color: eLine),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    'AI 친구: $aiResponse',
                    style: const TextStyle(
                      fontSize: 13,
                      color: Color(0xFF8B4A2A),
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }
}
