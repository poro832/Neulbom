import 'dart:async';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:fl_chart/fl_chart.dart';
import 'elderly_list_screen.dart';
import '../models/nulbom_models.dart';
import '../services/nulbom_api.dart';
import 'health_alerts_screen.dart';
import 'conversation_history_screen.dart';
import 'elderly_detail_screen.dart';
import 'guardian_account_screen.dart';

// 색상
const Color eBg = Color(0xFFFBF6ED);
const Color eBg2 = Color(0xFFF3E7D3);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);
const Color eAccentSoft = Color(0xFFFBE4D3);
const Color eBrass = Color(0xFFB78A4A);

class GuardianScreen extends StatefulWidget {
  const GuardianScreen({super.key});

  @override
  State<GuardianScreen> createState() => _GuardianScreenState();
}

class _GuardianScreenState extends State<GuardianScreen> {
  // 서버에서 읽어 기존 화면이 쓰던 맵 모양으로 바꿔 둔다.
  List<Map<String, dynamic>> _elders = [];
  Map<String, dynamic> _selectedElder = {};
  List<Map<String, dynamic>> _alerts = [];
  Timer? _dateRefreshTimer;
  bool _loading = true;
  String? _loadError;

  @override
  void initState() {
    super.initState();
    _load();
    _dateRefreshTimer = Timer.periodic(const Duration(minutes: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  static const _weekdayShort = ['월', '화', '수', '목', '금', '토', '일'];

  static String _status(double? score) {
    if (score == null) return '기록 없음';
    if (score >= 60) return '경보';
    if (score >= 30) return '주의';
    return '정상';
  }

  static String _when(DateTime? time) {
    if (time == null) return '-';
    final now = DateTime.now();
    final hm = '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';
    final today = DateTime(now.year, now.month, now.day);
    final day = DateTime(time.year, time.month, time.day);
    final diff = today.difference(day).inDays;
    if (diff == 0) return '오늘 $hm';
    if (diff == 1) return '어제 $hm';
    return '${time.month}월 ${time.day}일 $hm';
  }

  Map<String, dynamic> _elderToMap(ElderSummary e) {
    final last = e.lastCallAt;
    final now = DateTime.now();
    final talkedToday = last != null &&
        e.lastStatus == 'completed' &&
        last.year == now.year &&
        last.month == now.month &&
        last.day == now.day;
    return {
      'id': e.elderId,
      'name': e.name,
      'hasTalked': talkedToday,
      'status': _status(e.weekAvgScore),
      'lastTalk': _when(last),
      'weekCalls': e.weekCalls,
      'weekScore': e.weekAvgScore,
      'alertCount': e.weekAlerts,
      // 일별 점수는 어르신을 고를 때 서버에서 읽는다. 통화 없는 날은 0으로 그린다.
      'dayScores': List<double>.filled(7, 0.0),
    };
  }

  Map<String, dynamic> _alertToMap(AlertItem a) {
    return {
      'type': a.type == 'no_answer' ? '미응답' : '평소와 다름',
      'elder': a.elderName,
      'time': _when(a.createdAt),
      'severity': a.severity == 'critical'
          ? 'high'
          : a.severity == 'warning'
              ? 'medium'
              : 'low',
      'message': a.message,
    };
  }

  Future<void> _load() async {
    try {
      final elders = (await NulbomApi.guardianElders()).map(_elderToMap).toList();
      final alerts = (await NulbomApi.guardianAlerts()).map(_alertToMap).toList();
      if (!mounted) return;
      setState(() {
        _elders = elders;
        _alerts = alerts;
        _selectedElder = elders.isEmpty ? {} : elders.first;
        _loading = false;
        _loadError = null;
      });
      if (elders.isNotEmpty) await _loadWeekly(elders.first);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _loadError = error is ApiException
            ? error.message
            : '데이터를 불러오지 못했어요. 잠시 뒤에 다시 해 주세요.';
      });
    }
  }

  Future<void> _loadWeekly(Map<String, dynamic> elder) async {
    try {
      final w = await NulbomApi.weekly(elder['id'] as int);
      if (!mounted) return;
      setState(() {
        elder['dayScores'] = [for (final d in w.days) d.avgScore ?? 0.0];
        elder['weekScore'] = w.avgScore;
        elder['weekCalls'] = w.totalCalls;
      });
    } catch (_) {
      // 주간 그래프만 못 읽은 것이다. 목록과 알림은 그대로 보여 준다.
    }
  }

  void _select(Map<String, dynamic> elder) {
    setState(() => _selectedElder = elder);
    _loadWeekly(elder);
  }

  static String _scoreText(Object? score) =>
      score == null ? '-' : '${(score as double).round()}점';

  @override
  void dispose() {
    _dateRefreshTimer?.cancel();
    super.dispose();
  }

  String _formatDate(DateTime date) =>
      '${date.year}년 ${date.month}월 ${date.day}일';

  String _currentWeekRange() {
    final today = DateTime.now();
    final sunday = today.subtract(Duration(days: today.weekday % 7));
    final saturday = sunday.add(const Duration(days: 6));
    return '${_formatDate(sunday)} ~ ${_formatDate(saturday)}';
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(
        backgroundColor: eBg,
        body: Center(child: CircularProgressIndicator()),
      );
    }
    if (_loadError != null || _elders.isEmpty) {
      return Scaffold(
        backgroundColor: eBg,
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  _loadError ?? '관리 중인 어르신이 아직 없어요.',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.notoSansKr(fontSize: 18, color: eInkSoft),
                ),
                const SizedBox(height: 16),
                OutlinedButton(
                  onPressed: () {
                    setState(() {
                      _loading = true;
                      _loadError = null;
                    });
                    _load();
                  },
                  child: const Text('다시 불러오기'),
                ),
              ],
            ),
          ),
        ),
      );
    }
    return Scaffold(
      backgroundColor: eBg,
      body: SafeArea(
        child: SingleChildScrollView(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 헤더 (인사말 + 설정 버튼)
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      '보호자님\n안녕하세요',
                      style: GoogleFonts.notoSerifKr(
                        fontSize: 36,
                        fontWeight: FontWeight.w700,
                        color: eInk,
                        height: 1.3,
                      ),
                    ),
                    GestureDetector(
                      onTap: () {
                        Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (context) => const GuardianAccountScreen(),
                          ),
                        );
                      },
                      child: Container(
                        width: 48,
                        height: 48,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: eCard,
                          border: Border.all(color: eLine),
                        ),
                        child: const Icon(
                          Icons.settings_rounded,
                          color: eAccent,
                          size: 24,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 28),

                // 어르신 상태 카드들
                Text(
                  '관리 중인 어르신',
                  style: GoogleFonts.notoSerifKr(
                    fontSize: 22,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                  ),
                ),
                const SizedBox(height: 12),
                ..._elders.map((elder) => _buildElderCard(context, elder)),
                const SizedBox(height: 32),

                _buildElderSelector(),
                const SizedBox(height: 20),

                // 요약 통계
                Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      '이번 주 통계',
                      style: GoogleFonts.notoSerifKr(
                        fontSize: 22,
                        fontWeight: FontWeight.w700,
                        color: eInk,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Padding(
                      padding: const EdgeInsets.only(bottom: 2),
                      child: Text(
                        _currentWeekRange(),
                        style: GoogleFonts.notoSansKr(
                          fontSize: 11,
                          fontWeight: FontWeight.w500,
                          color: eInkSoft,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: _buildStatCard(
                        title: '통화 횟수',
                        value: '${_selectedElder['weekCalls']}회',
                        subtitle: '',
                        color: const Color(0xFF2196F3),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: _buildStatCard(
                        title: '평소와 다른 정도',
                        value: _scoreText(_selectedElder['weekScore']),
                        subtitle: '',
                        color: const Color(0xFF4CAF50),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 32),

                // 감정 추이 그래프
                Text(
                  '이번 주 평소와 다른 정도',
                  style: GoogleFonts.notoSerifKr(
                    fontSize: 22,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                  ),
                ),
                const SizedBox(height: 12),
                _buildEmotionChart(
                  _selectedElder['dayScores'] as List<double>,
                ),
                const SizedBox(height: 6),
                Text(
                  '낮을수록 평소와 같아요. 30점부터 주의, 60점부터 경보로 알려 드려요.',
                  style: GoogleFonts.notoSansKr(fontSize: 12, color: eInkSoft),
                ),
                const SizedBox(height: 32),

                // 최근 알림 미리보기
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Row(
                      children: [
                        Text(
                          '최근 알림',
                          style: GoogleFonts.notoSerifKr(
                            fontSize: 22,
                            fontWeight: FontWeight.w700,
                            color: eInk,
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          '건강 정보',
                          style: GoogleFonts.notoSansKr(
                            fontSize: 12,
                            fontWeight: FontWeight.w500,
                            color: eInkSoft,
                          ),
                        ),
                      ],
                    ),
                    GestureDetector(
                      onTap: () {
                        Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (context) => HealthAlertsScreen(
                              elderName: _selectedElder['name'] as String,
                            ),
                          ),
                        );
                      },
                      child: Text(
                        '전체보기',
                        style: GoogleFonts.notoSansKr(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                          color: eAccent,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                ..._alerts
                    .where((alert) => alert['elder'] == _selectedElder['name'])
                    .take(2)
                    .map((alert) => _buildAlertItem(alert)),
                const SizedBox(height: 20),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildElderSelector() {
    return LayoutBuilder(
      builder: (context, constraints) {
        final menuWidth = constraints.maxWidth;
        final maxMenuHeight = MediaQuery.sizeOf(context).height * 0.5;
        return _buildElderMenuAnchor(menuWidth, maxMenuHeight);
      },
    );
  }

  Widget _buildElderMenuAnchor(double menuWidth, double maxMenuHeight) {
    const menuPadding = 6.0;
    const itemPadding = 4.0;
    final tileWidth = menuWidth - (menuPadding + itemPadding) * 2 - 2;

    return MenuAnchor(
      crossAxisUnconstrained: false,
      alignmentOffset: const Offset(0, 8),
      style: MenuStyle(
        backgroundColor: const WidgetStatePropertyAll(eCard),
        surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
        elevation: const WidgetStatePropertyAll(3),
        shadowColor: WidgetStatePropertyAll(eInk.withValues(alpha: 0.12)),
        padding: const WidgetStatePropertyAll(EdgeInsets.all(menuPadding)),
        minimumSize: WidgetStatePropertyAll(Size(menuWidth, 0)),
        maximumSize: WidgetStatePropertyAll(Size(menuWidth, maxMenuHeight)),
        shape: WidgetStatePropertyAll(
          RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
            side: const BorderSide(color: eLine),
          ),
        ),
      ),
      menuChildren: [
        for (final elder in _elders)
          MenuItemButton(
            style: ButtonStyle(
              overlayColor: WidgetStatePropertyAll(eAccent.withValues(alpha: 0.08)),
              padding: const WidgetStatePropertyAll(
                EdgeInsets.all(itemPadding),
              ),
              minimumSize: WidgetStatePropertyAll(Size(tileWidth, 0)),
            ),
            onPressed: () => _select(elder),
            child: _buildElderMenuTile(elder, tileWidth),
          ),
      ],
      builder: (context, controller, child) {
        final selectedName = (_selectedElder['name'] as String?) ?? '선택';
        return Material(
          color: Colors.transparent,
          child: InkWell(
            borderRadius: BorderRadius.circular(16),
            onTap: () {
              if (controller.isOpen) {
                controller.close();
              } else {
                controller.open();
              }
            },
            child: Ink(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              decoration: BoxDecoration(
                color: eCard,
                border: Border.all(
                  color: controller.isOpen ? eAccent : eLine,
                  width: controller.isOpen ? 1.4 : 1,
                ),
                borderRadius: BorderRadius.circular(16),
              ),
              child: Row(
                children: [
                  Container(
                    width: 40,
                    height: 40,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: eAccentSoft,
                    ),
                    child: const Icon(
                      Icons.person_rounded,
                      color: eAccent,
                      size: 22,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '어르신 선택',
                          style: GoogleFonts.notoSansKr(
                            fontSize: 12,
                            fontWeight: FontWeight.w500,
                            color: eInkSoft,
                          ),
                        ),
                        Text(
                          selectedName,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: GoogleFonts.notoSansKr(
                            fontSize: 17,
                            fontWeight: FontWeight.w700,
                            color: eInk,
                          ),
                        ),
                      ],
                    ),
                  ),
                  Icon(
                    controller.isOpen
                        ? Icons.keyboard_arrow_up_rounded
                        : Icons.keyboard_arrow_down_rounded,
                    color: eAccent,
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildElderMenuTile(Map<String, dynamic> elder, double width) {
    final selected = elder['id'] == _selectedElder['id'];
    return Container(
      width: width,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
      decoration: BoxDecoration(
        color: selected ? eAccentSoft : Colors.transparent,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: selected ? eCard : eAccentSoft,
            ),
            child: Icon(
              Icons.person_rounded,
              color: selected ? eAccent : eInkSoft,
              size: 20,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  elder['name'] as String,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: GoogleFonts.notoSansKr(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                  ),
                ),
                Text(
                  '이번 주 ${elder['weekCalls']}회 통화',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: GoogleFonts.notoSansKr(
                    fontSize: 13,
                    fontWeight: FontWeight.w500,
                    color: eInkSoft,
                  ),
                ),
              ],
            ),
          ),
          if (selected)
            const Icon(Icons.check_rounded, color: eAccent, size: 20),
        ],
      ),
    );
  }

  Widget _buildElderCard(BuildContext context, Map<String, dynamic> elder) {
    return GestureDetector(
      onTap: () {
        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (context) => ElderlyDetailScreen(
              elderlyId: elder['id'],
              elderlyName: elder['name'],
            ),
          ),
        );
      },
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        decoration: BoxDecoration(
          color: eCard,
          border: Border.all(color: eLine),
          borderRadius: BorderRadius.circular(12),
        ),
        padding: const EdgeInsets.all(14),
        child: Row(
          children: [
            Container(
              width: 52,
              height: 52,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: elder['hasTalked']
                    ? const Color(0xFF4CAF50).withOpacity(0.1)
                    : const Color(0xFFFFA726).withOpacity(0.1),
              ),
              child: Icon(
                Icons.person_rounded,
                color: elder['hasTalked']
                    ? const Color(0xFF4CAF50)
                    : const Color(0xFFFFA726),
                size: 24,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        elder['name'],
                        style: GoogleFonts.notoSansKr(
                          fontSize: 20,
                          fontWeight: FontWeight.w700,
                          color: eInk,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: elder['hasTalked']
                              ? const Color(0xFF4CAF50)
                              : const Color(0xFFFFA726),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          elder['hasTalked'] ? '완료' : '미완료',
                          style: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '마지막 통화: ${elder['lastTalk']}',
                    style: const TextStyle(fontSize: 16, color: eInkSoft),
                  ),
                ],
              ),
            ),
            Icon(Icons.chevron_right_rounded, color: eInkSoft),
          ],
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
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 15,
              color: eInkSoft,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            value,
            style: GoogleFonts.notoSansKr(
              fontSize: 24,
              fontWeight: FontWeight.w700,
              color: color,
            ),
          ),
          if (subtitle.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              subtitle,
              style: const TextStyle(fontSize: 15, color: eInkSoft),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildEmotionChart(List<double> dayScores) {
    // 낮을수록 평소와 같다: 30 미만 초록, 30~60 노랑, 60 이상 빨강.
    Color colorFor(double score) {
      if (score >= 60) return const Color(0xFFE56F67);
      if (score >= 30) return const Color(0xFFE6B84B);
      return const Color(0xFF68B98A);
    }

    return Container(
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
          maxY: 100,
          barTouchData: BarTouchData(
            enabled: true,
            touchTooltipData: BarTouchTooltipData(
              getTooltipItem: (group, groupIndex, rod, rodIndex) {
                return BarTooltipItem(
                  '${rod.toY.round()}점',
                  const TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
                );
              },
            ),
          ),
          titlesData: FlTitlesData(
            show: true,
            topTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
            rightTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 28,
                getTitlesWidget: (value, meta) {
                  if (value != 0 && value != 30 && value != 60 && value != 100) {
                    return const SizedBox.shrink();
                  }
                  return SideTitleWidget(
                    axisSide: meta.axisSide,
                    child: Text(
                      '${value.toInt()}',
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
                  const days = ['일', '월', '화', '수', '목', '금', '토'];
                  return Text(
                    days[value.toInt()],
                    style: const TextStyle(
                      color: eInkSoft,
                      fontWeight: FontWeight.w500,
                      fontSize: 14,
                    ),
                  );
                },
              ),
            ),
          ),
          gridData: FlGridData(show: true, drawVerticalLine: false),
          borderData: FlBorderData(show: false),
          barGroups: List.generate(dayScores.length, (index) {
            final score = dayScores[index].clamp(0.0, 100.0);
            return BarChartGroupData(
              x: index,
              barRods: [
                BarChartRodData(
                  toY: score,
                  color: colorFor(score),
                  borderRadius: const BorderRadius.only(
                    topLeft: Radius.circular(4),
                    topRight: Radius.circular(4),
                  ),
                ),
              ],
            );
          }),
        ),
      ),
    );
  }

  Widget _buildAlertItem(Map<String, dynamic> alert) {
    Color typeColor = alert['severity'] == 'high'
        ? const Color(0xFFF44336)
        : alert['severity'] == 'medium'
        ? const Color(0xFFFFA726)
        : const Color(0xFF4CAF50);

    String typeLabel = alert['type'];

    return GestureDetector(
      onTap: () {
        final tabIndex = alert['type'] == '평소와 다름' ? 1 : 2;
        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (context) => HealthAlertsScreen(
              initialTabIndex: tabIndex,
              elderName: alert['elder'] as String,
            ),
          ),
        );
      },
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: typeColor.withOpacity(0.08),
          border: Border.all(color: typeColor.withOpacity(0.2)),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Row(
          children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: typeColor.withOpacity(0.15),
              ),
              child: Icon(
                alert['severity'] == 'high'
                    ? Icons.warning_rounded
                    : Icons.notifications_rounded,
                color: typeColor,
                size: 20,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${alert['elder']} - $typeLabel',
                    style: GoogleFonts.notoSansKr(
                      fontSize: 18,
                      fontWeight: FontWeight.w600,
                      color: eInk,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    alert['time'],
                    style: const TextStyle(fontSize: 15, color: eInkSoft),
                  ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right_rounded, color: eInkSoft),
          ],
        ),
      ),
    );
  }

  Widget _buildQuickMenu({
    required String title,
    required IconData icon,
    required VoidCallback onTap,
  }) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        decoration: BoxDecoration(
          color: eCard,
          border: Border.all(color: eLine),
          borderRadius: BorderRadius.circular(12),
        ),
        padding: const EdgeInsets.symmetric(vertical: 16),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, color: eAccent, size: 28),
            const SizedBox(height: 8),
            Text(
              title,
              style: GoogleFonts.notoSansKr(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: eInk,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
