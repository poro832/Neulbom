import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../services/nulbom_api.dart';
import '../models/nulbom_models.dart' show DayStat, ElderCalls;
import '../utils/kst.dart';
import 'elder_call_time_card.dart';
import 'elder_calls_screen.dart';
import 'elder_mentions_section.dart';

const Color eBg = Color(0xFFEFF6FF);
const Color eCard = Color(0xFFFFFFFF);
const Color eInk = Color(0xFF0E2548);
const Color eInkSoft = Color(0xFF3C5C8C);
const Color eLine = Color(0xFFD6E4FF);
const Color eAccent = Color(0xFF1A6BFF);

/// 서버의 평소 기준(app/analysis/baseline.py)과 같은 수: 최근 14통을 보고, 3통이 안 되면 기준이 없다.
/// 서버 쪽 tests/test_reports_contract.py가 두 값이 어긋나지 않는지 본다.
const int baselineMinCalls = 3;
const int baselineWindow = 14;

class ElderlyDetailScreen extends StatefulWidget {
  final int elderlyId;
  final String elderlyName;

  /// 테스트에서 바꾼다. 기본은 [kstNow] — 필드(년·월·일)를 한국 날짜로 읽는 값이다.
  final DateTime Function()? now;

  const ElderlyDetailScreen({
    super.key,
    required this.elderlyId,
    required this.elderlyName,
    this.now,
  });

  @override
  State<ElderlyDetailScreen> createState() => _ElderlyDetailScreenState();
}

class _ElderlyDetailScreenState extends State<ElderlyDetailScreen> {
  // "오늘"은 한국 날짜다(서버의 하루·주 경계와 같게). initState에서 정한다.
  late String _selectedDate;
  String _reportPeriod = 'daily';
  late DateTime _periodDate;

  // 지금 보는 기간(일·주·월)의 실제 통계. 서버의 주간 통계에서 만든다.
  int _statCalls = 0;
  double? _statScore;
  Map<String, double> _dayScores = const {}; // 날짜 키 -> 그날 평균 점수 (점수가 있는 날만)
  List<DateTime> _periodDays = const []; // 그 기간의 모든 날(주간 7일, 월간 1일~말일, 일간 그날)
  int? _baselineCalls; // 평소 기준에 쓸 수 있는 최근 통화 수. 서버가 주지 않으면 null(안내를 숨긴다)
  bool _statsLoading = true;
  String? _statsError;
  int _statsRequest = 0; // 늦게 온 응답이 최근 요청을 덮어쓰지 않게 한다

  // 최근 통화 요약 (어르신이 공유에 동의한 경우만 채워진다)
  ElderCalls? _recentCalls;
  String? _recentCallsError;

  @override
  void initState() {
    super.initState();
    _selectedDate = _todayKey();
    _periodDate = _today();
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
      void add(Iterable<DayStat> weekDays, bool Function(String date) keep) {
        for (final d in weekDays) {
          if (!keep(d.date)) continue;
          calls += d.calls;
          final score = d.avgScore;
          if (score != null) scored[d.date] = score;
        }
      }

      final List<DateTime> days;
      final int? baseline;
      if (_reportPeriod == 'daily') {
        days = [DateTime.parse(_selectedDate)];
        final week = await NulbomApi.weekly(widget.elderlyId, weekStart: _selectedDate);
        add(week.days, (date) => date == _selectedDate);
        baseline = week.baselineCalls;
      } else if (_reportPeriod == 'weekly') {
        final sunday = _weekStart(_periodDate);
        days = [for (var i = 0; i < 7; i++) _addDays(sunday, i)];
        final week = await NulbomApi.weekly(widget.elderlyId, weekStart: _dateKey(_periodDate));
        add(week.days, (_) => true);
        baseline = week.baselineCalls;
      } else {
        // 그 달의 날별 통계를 서버의 월간 주소에서 한 번에 읽는다.
        final first = DateTime(_periodDate.year, _periodDate.month, 1);
        final last = DateTime(_periodDate.year, _periodDate.month + 1, 0);
        days = [for (var d = 1; d <= last.day; d++) DateTime(first.year, first.month, d)];
        final month = '${first.year}-${first.month.toString().padLeft(2, '0')}';
        final stats = await NulbomApi.monthly(widget.elderlyId, month: month);
        add(stats.days, (date) => date.startsWith('$month-'));
        baseline = stats.baselineCalls;
      }
      if (!mounted || request != _statsRequest) return;
      final values = scored.values.toList();
      setState(() {
        _statCalls = calls;
        _statScore = values.isEmpty ? null : values.reduce((a, b) => a + b) / values.length;
        _dayScores = scored;
        _periodDays = days;
        _baselineCalls = baseline;
        _statsLoading = false;
      });
    } catch (error) {
      if (!mounted || request != _statsRequest) return;
      setState(() {
        _baselineCalls = null;
        _statsLoading = false;
        _statsError = error is ApiException
            ? error.message
            : '통계를 불러오지 못했어요. 잠시 뒤에 다시 해 주세요.';
      });
    }
  }

  /// 화면에 보이는 점수(반올림). 상태·색·가장 높았던 날을 정하는 비교는 모두 이 값으로 한다 —
  /// 59.6은 "60점"으로 보이니 경고다(보이는 숫자와 상태가 어긋나지 않게).
  static int _shown(double score) => score.round();

  /// 낮을수록 평소와 같다: 30점부터 주의, 60점부터 경고.
  static String _labelFor(double? score) {
    if (score == null) return '기록 없음';
    final shown = _shown(score);
    if (shown >= 60) return '경고';
    if (shown >= 30) return '주의';
    return '정상';
  }

  /// 평소 기준이 덜 쌓였을 때 카드 아래에 붙이는 한 줄. 기준 수를 모르거나(옛 서버) 다 쌓였으면 null.
  static String? _baselineHint(int? calls) {
    if (calls == null || calls >= baselineWindow) return null;
    if (calls < baselineMinCalls) return '아직 평소 기준을 만드는 중이에요($calls통). 점수는 참고만 해 주세요.';
    return '평소 기준 $calls/$baselineWindow통을 쌓았어요.';
  }

  static Color _colorFor(double? score) {
    switch (_labelFor(score)) {
      case '경고':
        return const Color(0xFFE56F67);
      case '주의':
        return const Color(0xFFFFA726);
      case '정상':
        return const Color(0xFF4CAF50);
      default:
        return eInkSoft;
    }
  }

  bool get _isDaily => _reportPeriod == 'daily';

  /// 그 기간에 점수가 가장 높았던 날과 그 점수. 보이는 점수가 같으면 나중 날. 점수 있는 날이 없으면 null.
  ({DateTime day, double score})? get _highestDay {
    MapEntry<String, double>? best;
    for (final entry in _dayScores.entries) {
      final shown = _shown(entry.value);
      // 날짜 키(yyyy-mm-dd)는 글자 순서가 곧 날짜 순서다.
      if (best == null ||
          shown > _shown(best.value) ||
          (shown == _shown(best.value) && entry.key.compareTo(best.key) > 0)) {
        best = entry;
      }
    }
    if (best == null) return null;
    return (day: DateTime.parse(best.key), score: best.value);
  }

  /// 상태(정상·주의·경고)를 정하는 점수. 일간은 그날 점수, 주간·월간은 가장 높았던 날의 점수 —
  /// 평균이 나쁜 하루를 가리지 않게 한다.
  double? get _statusScore => _isDaily ? _statScore : _highestDay?.score;

  String get _statusLabel => _labelFor(_statusScore);

  Color get _statusColor => _colorFor(_statusScore);

  Widget _buildRealStatRow(String callsSubtitle) {
    final loading = _statsLoading;
    final hint = loading || _statsError != null
        ? null
        : _baselineHint(_baselineCalls);
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
        // 부제 길이가 달라도 세 카드의 높이를 맞춘다.
        LayoutBuilder(
          builder: (context, constraints) {
            // 제목이 줄바꿈돼도 모든 카드의 수치가 같은 높이에서 시작한다.
            final titleWidth = ((constraints.maxWidth - 16) / 3 - 30).clamp(
              1.0,
              double.infinity,
            );
            final titleStyle = DefaultTextStyle.of(context).style.merge(
              const TextStyle(
                fontSize: 12,
                color: eInkSoft,
                fontWeight: FontWeight.w600,
              ),
            );
            var titleHeight = 0.0;
            for (final title in ['평소와 다른 정도', '통화 횟수', '상태']) {
              final painter = TextPainter(
                text: TextSpan(text: title, style: titleStyle),
                textDirection: Directionality.of(context),
                textScaler: MediaQuery.textScalerOf(context),
              )..layout(maxWidth: titleWidth);
              if (painter.height > titleHeight) titleHeight = painter.height;
              painter.dispose();
            }
            return IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(
                    child: _buildStatCard(
                      title: '평소와 다른 정도',
                      titleHeight: titleHeight,
                      value: loading || _statScore == null
                          ? '-'
                          : '${_shown(_statScore!)}점',
                      subtitle: _isDaily ? '낮을수록 평소와 같아요' : '평균 · 낮을수록 평소와 같아요',
                      // 평균 숫자는 평균 자신의 구간 색으로 칠한다(차트 범례와 같게). 상태 카드가 가장 높았던 날을 맡는다.
                      color: _colorFor(_statScore),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: _buildStatCard(
                      title: '통화 횟수',
                      titleHeight: titleHeight,
                      value: loading ? '-' : '$_statCalls회',
                      subtitle: callsSubtitle,
                      color: eAccent,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: _buildStatCard(
                      title: '상태',
                      titleHeight: titleHeight,
                      value: loading ? '-' : _statusLabel,
                      subtitle: _isDaily
                          ? '30점부터 주의, 60점부터 경고'
                          : '가장 높았던 날 기준 · 30점부터 주의, 60점부터 경고',
                      color: _statusColor,
                    ),
                  ),
                ],
              ),
            );
          },
        ),
        if (hint != null) ...[
          const SizedBox(height: 8),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.info_outline_rounded, size: 16, color: eInkSoft),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  hint,
                  style: const TextStyle(
                    fontSize: 12,
                    color: eInkSoft,
                    height: 1.5,
                  ),
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }

  /// 주간·월간: 카드 아래 "가장 높았던 날" 한 줄. 점수 있는 날이 없으면 그리지 않는다.
  Widget _buildHighestDayLine() {
    final highest = _highestDay;
    if (highest == null) return const SizedBox.shrink();
    final day = highest.day;
    return Row(
      children: [
        Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(color: _colorFor(highest.score), shape: BoxShape.circle),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            '가장 높았던 날: ${day.month}월 ${day.day}일 · ${_shown(highest.score)}점',
            style: GoogleFonts.notoSansKr(fontSize: 14, fontWeight: FontWeight.w600, color: eInk),
          ),
        ),
      ],
    );
  }

  /// 주간·월간: 날짜별 평균 점수 막대(세로축 0~100 고정). 점수 없는 날은 막대를 그리지 않는다.
  Widget _buildScoreChart() {
    final days = _periodDays;
    final monthly = _reportPeriod == 'monthly';
    double? scoreAt(int index) => _dayScores[_dateKey(days[index])];
    const weekdays = ['일', '월', '화', '수', '목', '금', '토'];
    const axisMarks = {0, 30, 60, 100};
    bool isMark(double value) =>
        (value - value.round()).abs() < 0.001 && axisMarks.contains(value.round());

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          decoration: BoxDecoration(
            color: eCard,
            border: Border.all(color: eLine),
            borderRadius: BorderRadius.circular(12),
          ),
          padding: const EdgeInsets.all(16),
          height: 200,
          child: BarChart(
            BarChartData(
              alignment: BarChartAlignment.spaceAround,
              minY: 0,
              maxY: 100,
              barTouchData: BarTouchData(
                enabled: true,
                touchTooltipData: BarTouchTooltipData(
                  getTooltipItem: (group, groupIndex, rod, rodIndex) {
                    final score = scoreAt(group.x);
                    if (score == null) return null;
                    final day = days[group.x];
                    return BarTooltipItem(
                      '${day.month}/${day.day} · ${_shown(score)}점',
                      const TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
                    );
                  },
                ),
              ),
              titlesData: FlTitlesData(
                show: true,
                topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                leftTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 28,
                    interval: 10,
                    getTitlesWidget: (value, meta) {
                      if (!isMark(value)) return const SizedBox.shrink();
                      return SideTitleWidget(
                        axisSide: meta.axisSide,
                        child: Text(
                          '${value.round()}',
                          style: const TextStyle(
                            color: eInkSoft,
                            fontWeight: FontWeight.w500,
                            fontSize: 11,
                          ),
                        ),
                      );
                    },
                  ),
                ),
                bottomTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    getTitlesWidget: (value, meta) {
                      final index = value.toInt();
                      if (index < 0 || index >= days.length) return const SizedBox.shrink();
                      final day = days[index];
                      // 주간은 요일, 월간은 1일부터 5일 간격의 날짜 숫자
                      if (monthly && (day.day - 1) % 5 != 0) return const SizedBox.shrink();
                      return Text(
                        monthly ? '${day.day}' : weekdays[day.weekday % 7],
                        style: TextStyle(
                          color: eInkSoft,
                          fontWeight: FontWeight.w500,
                          fontSize: monthly ? 11 : 14,
                        ),
                      );
                    },
                  ),
                ),
              ),
              gridData: FlGridData(
                show: true,
                drawVerticalLine: false,
                horizontalInterval: 10,
                checkToShowHorizontalLine: isMark,
              ),
              borderData: FlBorderData(show: false),
              barGroups: [
                for (var i = 0; i < days.length; i++)
                  BarChartGroupData(
                    x: i,
                    barRods: [
                      // 점수 없는 날도 자리는 남긴다(막대 간격이 날짜대로 고르게). 높이 0, 투명.
                      BarChartRodData(
                        toY: (scoreAt(i) ?? 0).clamp(0.0, 100.0),
                        color: scoreAt(i) == null ? Colors.transparent : _colorFor(scoreAt(i)),
                        width: monthly ? 5 : 14,
                        borderRadius: BorderRadius.only(
                          topLeft: Radius.circular(monthly ? 2 : 4),
                          topRight: Radius.circular(monthly ? 2 : 4),
                        ),
                      ),
                    ],
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 8),
        Text.rich(
          TextSpan(
            style: const TextStyle(fontSize: 12, color: eInkSoft),
            children: [
              TextSpan(
                text: '정상',
                style: TextStyle(color: _colorFor(0), fontWeight: FontWeight.w700),
              ),
              const TextSpan(text: ' 30점 미만 · '),
              TextSpan(
                text: '주의',
                style: TextStyle(color: _colorFor(30), fontWeight: FontWeight.w700),
              ),
              const TextSpan(text: ' 30~59점 · '),
              TextSpan(
                text: '경고',
                style: TextStyle(color: _colorFor(60), fontWeight: FontWeight.w700),
              ),
              const TextSpan(text: ' 60점 이상'),
            ],
          ),
        ),
      ],
    );
  }

  String _periodSummaryText(String periodLabel) {
    if (_statsLoading) return '통계를 불러오는 중이에요.';
    if (_statCalls == 0) return '$periodLabel에는 ${widget.elderlyName}님과 나눈 통화 기록이 없어요.';
    final score = _statScore;
    final highest = _highestDay;
    final scoreText = score == null || highest == null
        ? '점수를 낼 수 있는 통화가 없었어요'
        : '평소와 다른 정도는 평균 ${_shown(score)}점, 가장 높았던 날은 '
            '${highest.day.month}월 ${highest.day.day}일(${_shown(highest.score)}점, $_statusLabel)이에요';
    return '$periodLabel에는 ${widget.elderlyName}님과 $_statCalls번 통화했고, $scoreText.';
  }

  /// 상태 분석. 점수가 왜 그렇게 나왔는지(원인)는 말하지 않는다 — 이 서비스는 진단·원인 추정을 하지 않는다.
  Widget _buildStatusAnalysis() {
    final label = _statusLabel;
    final color = _statusColor;
    final String lines;
    switch (label) {
      case '정상':
        lines = '• 평소와 비슷했어요\n• 특별히 달라진 점이 없어요';
      case '주의':
        lines = '• 평소와 다른 신호가 있었어요\n• 안부를 한 번 확인해 보세요';
      case '경고':
        lines = '• 평소와 많이 달랐어요\n• 가능하면 직접 연락해 보세요';
      default:
        lines = '• 이 기간에는 점수를 낸 통화가 없어요';
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
          const SizedBox(height: 12),
          Divider(height: 1, color: color.withValues(alpha: 0.3)),
          const SizedBox(height: 10),
          const Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.info_outline_rounded, size: 16, color: eInkSoft),
              SizedBox(width: 6),
              Expanded(
                child: Text(
                  '통화에서 나온 신호를 점수로 요약한 것이에요. 진단이 아니에요.',
                  style: TextStyle(fontSize: 12, color: eInkSoft, height: 1.5),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  /// 한국 날짜의 오늘(자정). 폰의 시간대와 상관없이 서버의 하루·주 경계와 같다.
  DateTime _today() {
    final now = (widget.now ?? kstNow)();
    return DateTime(now.year, now.month, now.day);
  }

  String _todayKey() => _dateKey(_today());

  /// 날짜 생성자로 더해 서머타임이 있는 시간대에서도 자정이 밀리지 않게 한다.
  static DateTime _addDays(DateTime date, int days) =>
      DateTime(date.year, date.month, date.day + days);

  static String _dateKey(DateTime date) {
    final month = date.month.toString().padLeft(2, '0');
    final day = date.day.toString().padLeft(2, '0');
    return '${date.year}-$month-$day';
  }

  String _formatKoreanDate(DateTime date) {
    return '${date.year}년 ${date.month}월 ${date.day}일';
  }

  /// 그 날이 속한 주(일~토)의 일요일.
  DateTime _weekStart(DateTime date) =>
      DateTime(date.year, date.month, date.day - date.weekday % 7);

  String _weeklyRangeLabel() {
    final sunday = _weekStart(_periodDate);
    final saturday = _addDays(sunday, 6);
    return '${_formatKoreanDate(sunday)} ~ ${_formatKoreanDate(saturday)}';
  }

  String _monthlyLabel() {
    return '${_periodDate.year}년 ${_periodDate.month}월';
  }

  Future<DateTime?> _showMonthPicker(DateTime initialDate) {
    var selectedYear = initialDate.year;
    final now = _today();
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
    final today = _today();
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
            // 점수를 낸 날이 하나라도 있을 때만: 가장 높았던 날 한 줄과 날짜별 막대
            if (!_statsLoading && _statsError == null && _highestDay != null) ...[
              const SizedBox(height: 12),
              _buildHighestDayLine(),
              const SizedBox(height: 12),
              _buildScoreChart(),
            ],
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
              ElderMentionsSection(elderId: widget.elderlyId, now: widget.now),
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
              const SizedBox(height: 24),

              // 하루 한 번 AI가 전화하는 시간(07:00~21:00, 30분 단위). 스케줄러가 매분 새로 읽는다.
              ElderCallTimeCard(elderId: widget.elderlyId),
              const SizedBox(height: 24),

              // 어르신 폰을 바꿨거나 미리 등록된 어르신이 처음 앱에 들어올 때 쓰는 6자리 코드
              _ElderPhonePairingCard(elderId: widget.elderlyId),
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
    double? titleHeight,
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
        mainAxisAlignment: MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            height: titleHeight,
            child: Text(
              title,
              style: const TextStyle(
                fontSize: 12,
                color: eInkSoft,
                fontWeight: FontWeight.w600,
              ),
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

/// 보호자: 어르신 폰을 이 앱에 연결하는 6자리 코드(24시간, 한 번만 쓸 수 있음)를 만든다.
///
/// 어르신은 폰의 로그인 화면에 번호와 이 코드를 넣어 이 폰 전용 열쇠를 받는다. 새로 만들면 서버가 이전 코드를
/// 바로 못 쓰게 하므로, 만드는 동안에는 다시 누를 수 없다. 코드는 대화상자에만 보이고 저장하거나 기록하지 않는다.
class _ElderPhonePairingCard extends StatefulWidget {
  final int elderId;

  const _ElderPhonePairingCard({required this.elderId});

  @override
  State<_ElderPhonePairingCard> createState() => _ElderPhonePairingCardState();
}

class _ElderPhonePairingCardState extends State<_ElderPhonePairingCard> {
  static const String _offline = '서버에 연결하지 못했어요. 잠시 뒤에 다시 해 주세요.';

  bool _issuing = false;

  Future<void> _issue() async {
    if (_issuing) return;
    setState(() => _issuing = true);
    String? code;
    String? error;
    try {
      code = (await NulbomApi.issuePairingCode(widget.elderId)).code;
    } on ApiException catch (e) {
      error = e.message;
    } catch (_) {
      error = _offline;
    }
    if (!mounted) return;
    setState(() => _issuing = false);
    await showDialog<void>(
      context: context,
      builder: (context) => _PairingCodeDialog(code: code, error: error),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '어르신 폰 연결',
          style: GoogleFonts.notoSansKr(
            fontSize: 18,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        const SizedBox(height: 8),
        Container(
          width: double.infinity,
          decoration: BoxDecoration(
            color: eCard,
            border: Border.all(color: eLine),
            borderRadius: BorderRadius.circular(12),
          ),
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '어르신 폰을 바꿨거나 처음 연결할 때 쓰는 코드예요.',
                style: TextStyle(fontSize: 14, color: eInkSoft, height: 1.5),
              ),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                height: 48,
                child: OutlinedButton(
                  onPressed: _issuing ? null : _issue,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: eAccent,
                    side: const BorderSide(color: eAccent, width: 1.5),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                  child: Text(
                    '연결 코드 만들기',
                    style: GoogleFonts.notoSansKr(fontSize: 15, fontWeight: FontWeight.w700),
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

/// 만든 연결 코드(앞자리 0 그대로) 또는 서버가 거절한 이유를 보여 준다. 닫으면 코드는 어디에도 남지 않는다.
class _PairingCodeDialog extends StatelessWidget {
  final String? code;
  final String? error;

  const _PairingCodeDialog({this.code, this.error});

  @override
  Widget build(BuildContext context) {
    final code = this.code;
    return AlertDialog(
      backgroundColor: eCard,
      title: Text(
        '어르신 폰 연결 코드',
        style: GoogleFonts.notoSansKr(fontSize: 18, fontWeight: FontWeight.w700, color: eInk),
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (code != null) ...[
            Center(
              child: SelectableText(
                code,
                textAlign: TextAlign.center,
                style: GoogleFonts.notoSansKr(
                  fontSize: 36,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 6,
                  color: eAccent,
                ),
              ),
            ),
            const SizedBox(height: 12),
            Text(
              '24시간 안에 어르신 폰의 로그인 화면에 번호와 함께 입력해 주세요. 새로 만들면 이전 코드는 쓸 수 없어요.',
              style: GoogleFonts.notoSansKr(fontSize: 14, height: 1.5, color: eInkSoft),
            ),
          ] else
            Text(
              error ?? '연결 코드를 만들지 못했어요.',
              style: const TextStyle(fontSize: 14, color: Color(0xFFD92D20)),
            ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(
            '닫기',
            style: GoogleFonts.notoSansKr(fontWeight: FontWeight.w600, color: eAccent),
          ),
        ),
      ],
    );
  }
}
