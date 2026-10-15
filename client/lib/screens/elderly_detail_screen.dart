import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../services/nulbom_api.dart';
import '../models/nulbom_models.dart' show ElderCalls;
import 'elder_calls_screen.dart';
import 'elder_mentions_section.dart';

const Color eBg = Color(0xFFEFF6FF);
const Color eCard = Color(0xFFFFFFFF);
const Color eInk = Color(0xFF0E2548);
const Color eInkSoft = Color(0xFF3C5C8C);
const Color eLine = Color(0xFFD6E4FF);
const Color eAccent = Color(0xFF1A6BFF);

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

  // 지금 보는 기간(일·주·월)의 실제 통계. 서버의 주간 통계에서 만든다.
  int _statCalls = 0;
  double? _statScore;
  bool _statsLoading = true;
  String? _statsError;
  int _statsRequest = 0; // 늦게 온 응답이 최근 요청을 덮어쓰지 않게 한다

  // 최근 통화 요약 (어르신이 공유에 동의한 경우만 채워진다)
  ElderCalls? _recentCalls;
  String? _recentCallsError;

  @override
  void initState() {
    super.initState();
    _loadStats();
    _loadRecentCalls();
  }

  Future<void> _loadRecentCalls() async {
    try {
      final calls = await NulbomApi.elderCalls(widget.elderlyId, limit: 3);
      if (!mounted) return;
      setState(() => _recentCalls = calls);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _recentCallsError = error is ApiException
            ? error.message
            : '통화 요약을 불러오지 못했어요. 잠시 뒤에 다시 해 주세요.';
      });
    }
  }

  Widget _buildRecentCallsSection() {
    final calls = _recentCalls;
    final Widget body;
    if (_recentCallsError != null) {
      body = Text(_recentCallsError!, style: const TextStyle(fontSize: 14, color: eInkSoft));
    } else if (calls == null) {
      body = const LinearProgressIndicator();
    } else if (!calls.shareAgreed) {
      body = const Text('어르신이 동의한 뒤에 볼 수 있어요.',
          style: TextStyle(fontSize: 14, color: eInkSoft));
    } else if (calls.calls.isEmpty) {
      body = const Text('아직 통화가 없어요.', style: TextStyle(fontSize: 14, color: eInkSoft));
    } else {
      body = Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final call in calls.calls)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Text(
                call.summary ?? '요약이 없어요.',
                style: const TextStyle(fontSize: 14, color: eInk, height: 1.6),
              ),
            ),
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              '최근 통화 요약',
              style: GoogleFonts.notoSansKr(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: eInk,
              ),
            ),
            TextButton(
              onPressed: () => Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => ElderCallsScreen(
                    elderId: widget.elderlyId,
                    elderName: widget.elderlyName,
                  ),
                ),
              ),
              child: const Text('전체 통화 보기', style: TextStyle(color: eAccent)),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Container(
          width: double.infinity,
          decoration: BoxDecoration(
            color: eAccent.withOpacity(0.08),
            border: Border.all(color: eAccent.withOpacity(0.2)),
            borderRadius: BorderRadius.circular(12),
          ),
          padding: const EdgeInsets.all(16),
          child: body,
        ),
      ],
    );
  }

  Future<void> _loadStats() async {
    final request = ++_statsRequest;
    setState(() {
      _statsLoading = true;
      _statsError = null;
    });
    try {
      final scored = <String, double>{}; // 날짜 -> 평균 점수 (점수가 있는 날만)
      var calls = 0;
      void add(Iterable<dynamic> weekDays, bool Function(String date) keep) {
        for (final d in weekDays) {
          final date = d.date as String;
          if (!keep(date)) continue;
          calls += d.calls as int;
          final score = d.avgScore as double?;
          if (score != null) scored[date] = score;
        }
      }

      if (_reportPeriod == 'daily') {
        final week = await NulbomApi.weekly(widget.elderlyId, weekStart: _selectedDate);
        add(week.days, (date) => date == _selectedDate);
      } else if (_reportPeriod == 'weekly') {
        final week = await NulbomApi.weekly(widget.elderlyId, weekStart: _dateKey(_periodDate));
        add(week.days, (_) => true);
      } else {
        // 서버에는 주간 통계만 있다. 그 달에 걸친 주들을 이어 읽고 그 달의 날만 합친다.
        final first = DateTime(_periodDate.year, _periodDate.month, 1);
        final last = DateTime(_periodDate.year, _periodDate.month + 1, 0);
        final prefix = '${first.year}-${first.month.toString().padLeft(2, '0')}-';
        var cursor = _weekStart(first);
        while (!cursor.isAfter(last)) {
          final week = await NulbomApi.weekly(widget.elderlyId, weekStart: _dateKey(cursor));
          add(week.days, (date) => date.startsWith(prefix));
          cursor = cursor.add(const Duration(days: 7));
        }
      }
      if (!mounted || request != _statsRequest) return;
      final values = scored.values.toList();
      setState(() {
        _statCalls = calls;
        _statScore = values.isEmpty ? null : values.reduce((a, b) => a + b) / values.length;
        _statsLoading = false;
      });
    } catch (error) {
      if (!mounted || request != _statsRequest) return;
      setState(() {
        _statsLoading = false;
        _statsError = error is ApiException
            ? error.message
            : '통계를 불러오지 못했어요. 잠시 뒤에 다시 해 주세요.';
      });
    }
  }

  /// 낮을수록 평소와 같다: 30점부터 주의, 60점부터 경보.
  String get _statusLabel {
    final score = _statScore;
    if (score == null) return '기록 없음';
    if (score >= 60) return '경보';
    if (score >= 30) return '주의';
    return '정상';
  }

  Color get _statusColor {
    switch (_statusLabel) {
      case '경보':
        return const Color(0xFFE56F67);
      case '주의':
        return const Color(0xFFFFA726);
      case '정상':
        return const Color(0xFF4CAF50);
      default:
        return eInkSoft;
    }
  }

  Widget _buildRealStatRow(String callsSubtitle) {
    final loading = _statsLoading;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (loading) const LinearProgressIndicator(),
        if (_statsError != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(
              _statsError!,
              style: const TextStyle(fontSize: 13, color: Color(0xFFD92D20)),
            ),
          ),
        Row(
          children: [
            Expanded(
              child: _buildStatCard(
                title: '평소와 다른 정도',
                value: loading || _statScore == null ? '-' : '${_statScore!.round()}점',
                subtitle: '낮을수록 평소와 같아요',
                color: _statusColor,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _buildStatCard(
                title: '통화 횟수',
                value: loading ? '-' : '$_statCalls회',
                subtitle: callsSubtitle,
                color: eAccent,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _buildStatCard(
                title: '상태',
                value: loading ? '-' : _statusLabel,
                subtitle: '30점부터 주의, 60점부터 경보',
                color: _statusColor,
              ),
            ),
          ],
        ),
      ],
    );
  }

  String _periodSummaryText(String periodLabel) {
    if (_statsLoading) return '통계를 불러오는 중이에요.';
    if (_statCalls == 0) return '$periodLabel에는 ${widget.elderlyName}님과 나눈 통화 기록이 없어요.';
    final score = _statScore;
    final scoreText = score == null
        ? '점수를 낼 수 있는 통화가 없었어요'
        : '평소와 다른 정도는 평균 ${score.round()}점($_statusLabel)이에요';
    return '$periodLabel에는 ${widget.elderlyName}님과 $_statCalls번 통화했고, $scoreText.';
  }

  Widget _buildStatusAnalysis() {
    final label = _statusLabel;
    final color = _statusColor;
    final String lines;
    switch (label) {
      case '정상':
        lines = '• 평소와 비슷한 말수와 대답 속도예요\n• 특별히 달라진 점이 없어요';
      case '주의':
        lines = '• 평소보다 말수가 줄었거나 대답이 느려졌어요\n• 안부를 한 번 확인해 보세요';
      case '경보':
        lines = '• 평소와 많이 달랐어요\n• 가능하면 직접 연락해 보세요';
      default:
        lines = '• 이날은 점수를 낸 통화가 없어요';
    }
    return Container(
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        border: Border.all(color: color.withOpacity(0.3)),
        borderRadius: BorderRadius.circular(12),
      ),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                label == '정상' ? Icons.check_circle_outline_rounded : Icons.info_outline_rounded,
                color: color,
                size: 24,
              ),
              const SizedBox(width: 12),
              Text(
                label,
                style: GoogleFonts.notoSansKr(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: color,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(lines, style: const TextStyle(fontSize: 14, color: eInkSoft, height: 1.6)),
        ],
      ),
    );
  }

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

  Future<DateTime?> _showDayPicker(DateTime initialDate) {
    return _showCalendarPicker(initialDate, selectByWeek: false);
  }

  Future<DateTime?> _showWeekPicker(DateTime initialDate) {
    return _showCalendarPicker(initialDate, selectByWeek: true);
  }

  Future<DateTime?> _showCalendarPicker(
    DateTime initialDate, {
    required bool selectByWeek,
  }) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final firstDate = DateTime(2024, 1, 1);
    var safeInitial = DateTime(initialDate.year, initialDate.month, initialDate.day);
    if (safeInitial.isAfter(today)) {
      safeInitial = today;
    } else if (safeInitial.isBefore(firstDate)) {
      safeInitial = firstDate;
    }

    var visibleMonth = DateTime(safeInitial.year, safeInitial.month);
    final selectedWeekStart = _weekStart(safeInitial);
    final selectedDay = safeInitial;
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

                          if (selectByWeek) {
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
                                                              visibleMonth
                                                                  .month
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
                          }

                          return Padding(
                            padding: const EdgeInsets.only(bottom: 4),
                            child: Container(
                              decoration: BoxDecoration(
                                color: eBg,
                                borderRadius: BorderRadius.circular(10),
                              ),
                              padding: const EdgeInsets.symmetric(vertical: 4),
                              child: Row(
                                children: [
                                  for (final day in weekDays)
                                    Expanded(
                                      child: Builder(
                                        builder: (context) {
                                          final isOutsideMonth =
                                              day.month != visibleMonth.month;
                                          final isFuture = day.isAfter(today);
                                          final isTooOld = day.isBefore(
                                            firstDate,
                                          );
                                          final enabled =
                                              !isOutsideMonth &&
                                              !isFuture &&
                                              !isTooOld;
                                          final isSelected =
                                              day.year == selectedDay.year &&
                                              day.month == selectedDay.month &&
                                              day.day == selectedDay.day;

                                          return Padding(
                                            padding: const EdgeInsets.symmetric(
                                              horizontal: 2,
                                            ),
                                            child: Material(
                                              color: isSelected
                                                  ? eAccent
                                                  : Colors.transparent,
                                              borderRadius:
                                                  BorderRadius.circular(10),
                                              child: InkWell(
                                                borderRadius:
                                                    BorderRadius.circular(10),
                                                onTap: enabled
                                                    ? () => Navigator.pop(
                                                        context,
                                                        day,
                                                      )
                                                    : null,
                                                child: SizedBox(
                                                  height: 36,
                                                  child: Center(
                                                    child: Text(
                                                      '${day.day}',
                                                      textAlign:
                                                          TextAlign.center,
                                                      style:
                                                          GoogleFonts.notoSansKr(
                                                        fontSize: 14,
                                                        fontWeight:
                                                            FontWeight.w600,
                                                        color: isSelected
                                                            ? Colors.white
                                                            : enabled
                                                            ? eInk
                                                            : eInkSoft,
                                                      ),
                                                    ),
                                                  ),
                                                ),
                                              ),
                                            ),
                                          );
                                        },
                                      ),
                                    ),
                                ],
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
        onTap: () {
          setState(() => _reportPeriod = period);
          _loadStats();
        },
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
          style: GoogleFonts.notoSansKr(
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
                  _loadStats();
                }
              },
            ),
            const SizedBox(height: 16),
            _buildRealStatRow(isWeekly ? '주간 합계' : '월간 합계'),
            const SizedBox(height: 24),
            Text(
              isWeekly ? '주간 분석 요약' : '월간 분석 요약',
              style: GoogleFonts.notoSansKr(
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
                _periodSummaryText(isWeekly ? rangeLabel : monthLabel),
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

    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        title: Text(
          '${widget.elderlyName} 건강 리포트',
          style: GoogleFonts.notoSansKr(
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
                  final picked = await _showDayPicker(
                    DateTime.parse(_selectedDate),
                  );
                  if (picked != null) {
                    setState(() => _selectedDate = _dateKey(picked));
                    _loadStats();
                  }
                },
              ),
              const SizedBox(height: 24),

              // 통계 제목
              Text(
                '이날의 통계',
                style: GoogleFonts.notoSansKr(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),

              // 통계 그리드
              _buildRealStatRow('그날 합계'),
              const SizedBox(height: 24),

              _buildRecentCallsSection(),
              const SizedBox(height: 24),

              // 어르신이 통화에서 직접 하신 건강·기분 이야기(주간)
              ElderMentionsSection(elderId: widget.elderlyId),
              const SizedBox(height: 24),

              // 상태 분석
              Text(
                '상태 분석',
                style: GoogleFonts.notoSansKr(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),
              _buildStatusAnalysis(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildStatsGrid({
    required String depressionIndex,
    required String depressionStatus,
    required String healthStatus,
    required String healthDetail,
    required String callCount,
    required String callStatus,
    required String chatCount,
    required String chatStatus,
  }) {
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: _buildStatCard(
                title: '우울 수치',
                value: depressionIndex,
                subtitle: depressionStatus,
                color: const Color(0xFF4CAF50),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _buildStatCard(
                title: '건강상태',
                value: healthStatus,
                subtitle: healthDetail,
                color: const Color(0xFF4CAF50),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: _buildStatCard(
                title: '전화 횟수',
                value: callCount,
                subtitle: callStatus,
                color: eAccent,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _buildStatCard(
                title: '채팅 횟수',
                value: chatCount,
                subtitle: chatStatus,
                color: const Color(0xFF2196F3),
              ),
            ),
          ],
        ),
      ],
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
      padding: const EdgeInsets.all(14),
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
}
