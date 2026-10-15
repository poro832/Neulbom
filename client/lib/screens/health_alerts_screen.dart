import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../models/nulbom_models.dart' show AlertItem;
import '../services/nulbom_api.dart';

const Color eBg = Color(0xFFEFF6FF);
const Color eCard = Color(0xFFFFFFFF);
const Color eInk = Color(0xFF0E2548);
const Color eInkSoft = Color(0xFF3C5C8C);
const Color eLine = Color(0xFFD6E4FF);
const Color eAccent = Color(0xFF1A6BFF);

/// 어르신이 통화에서 약에 대해 한 말 한 건 - 서버의 통화 요약에서 모은다.
class MedicationEntry {
  final String elder;
  final DateTime at;
  final String medication; // taken | not_taken | unknown

  const MedicationEntry({required this.elder, required this.at, required this.medication});
}

class HealthAlert {
  final String alertId;
  final String type;
  final String elder;
  final String message;
  final String time;
  final String severity;
  final String action;

  HealthAlert({
    required this.alertId,
    required this.type,
    required this.elder,
    required this.message,
    required this.time,
    required this.severity,
    required this.action,
  });
}

class HealthAlertsScreen extends StatefulWidget {
  final int initialTabIndex;
  final String? elderName;

  const HealthAlertsScreen({
    super.key,
    this.initialTabIndex = 0,
    this.elderName,
  }) : assert(initialTabIndex >= 0 && initialTabIndex < 3);

  @override
  State<HealthAlertsScreen> createState() => _HealthAlertsScreenState();
}

class _HealthAlertsScreenState extends State<HealthAlertsScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  // 건강 경고 탭은 서버의 실제 알림을, 약물 복용 탭은 서버의 통화 요약을 보여 준다.
  // (건강 확인 탭은 아직 서버 자료가 없다.)
  List<HealthAlert>? _serverAlerts;
  String? _alertsError;

  List<MedicationEntry>? _medEntries;
  List<String> _medUnconsented = const [];
  String? _medError;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(
      length: 3,
      vsync: this,
      initialIndex: widget.initialTabIndex,
    );
    _loadAlerts();
    _loadMedication();
  }

  Future<void> _loadAlerts() async {
    setState(() {
      _serverAlerts = null;
      _alertsError = null;
    });
    try {
      final items = await NulbomApi.guardianAlerts(limit: 50);
      if (!mounted) return;
      setState(() => _serverAlerts = items.map(_toHealthAlert).toList());
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _alertsError = error is ApiException
            ? error.message
            : '알림을 불러오지 못했어요. 잠시 뒤에 다시 해 주세요.';
      });
    }
  }

  static const String _medFailure = '약 복용 이야기를 불러오지 못했어요. 잠시 뒤에 다시 해 주세요.';

  Future<void> _loadMedication() async {
    setState(() {
      _medEntries = null;
      _medError = null;
    });
    try {
      var elders = await NulbomApi.guardianElders();
      if (widget.elderName != null) {
        elders = elders.where((e) => e.name == widget.elderName).toList();
      }
      // 승인 대기 어르신은 아직 통화 자료를 볼 수 없다.
      elders = elders.where((e) => e.status != 'pending').toList();
      final entries = <MedicationEntry>[];
      final unconsented = <String>[];
      var failed = 0;
      for (final elder in elders) {
        try {
          final result = await NulbomApi.elderCalls(elder.elderId, limit: 14);
          if (!result.shareAgreed) {
            unconsented.add(elder.name);
            continue;
          }
          for (final call in result.calls) {
            final medication = call.medication;
            if (medication == null) continue;
            entries.add(MedicationEntry(elder: elder.name, at: call.startedAt, medication: medication));
          }
        } catch (_) {
          failed++;
        }
      }
      if (elders.isNotEmpty && failed == elders.length) {
        throw const ApiException(0, _medFailure);
      }
      entries.sort((a, b) => b.at.compareTo(a.at));
      if (!mounted) return;
      setState(() {
        _medEntries = entries;
        _medUnconsented = unconsented;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _medError = error is ApiException && error.message.isNotEmpty ? error.message : _medFailure;
      });
    }
  }

  static String _medicationText(String medication) {
    switch (medication) {
      case 'taken':
        return '약을 드셨다고 하셨어요';
      case 'not_taken':
        return '아직 안 드셨다고 하셨어요';
      default:
        return '약 이야기가 없었어요';
    }
  }

  static HealthAlert _toHealthAlert(AlertItem item) {
    final noAnswer = item.type == 'no_answer';
    final String severity;
    switch (item.severity) {
      case 'critical':
        severity = 'high';
      case 'warning':
        severity = 'medium';
      default:
        severity = 'low';
    }
    return HealthAlert(
      alertId: '${item.alertId}',
      type: noAnswer ? '미응답' : '평소와 다름',
      elder: item.elderName,
      message: item.message,
      time: _timeText(item.createdAt),
      severity: severity,
      action: noAnswer
          ? '다시 연락해 보세요'
          : (item.severity == 'critical' ? '가능하면 직접 연락해 보세요' : '안부를 한 번 확인해 보세요'),
    );
  }

  static String _timeText(DateTime time) {
    final t = time.toLocal();
    final now = DateTime.now();
    final hm = '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
    final days = DateTime(now.year, now.month, now.day)
        .difference(DateTime(t.year, t.month, t.day))
        .inDays;
    if (days == 0) return '오늘 $hm';
    if (days == 1) return '어제 $hm';
    return '${t.year}-${t.month.toString().padLeft(2, '0')}-${t.day.toString().padLeft(2, '0')} $hm';
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        title: Text(
          '건강 알림',
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
        bottom: TabBar(
          controller: _tabController,
          labelColor: eAccent,
          unselectedLabelColor: eInkSoft,
          indicatorColor: eAccent,
          labelStyle: GoogleFonts.notoSansKr(fontWeight: FontWeight.w700),
          tabs: const [
            Tab(text: '약물 복용'),
            Tab(text: '건강 경고'),
            Tab(text: '건강 확인'),
          ],
        ),
      ),
      body: Column(
        children: [
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: [
                _buildMedicationTab(),
                _buildHealthAlertTab(),
                _buildHealthCheckTab(),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMedicationTab() {
    if (_medError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                _medError!,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 14, color: eInkSoft),
              ),
              const SizedBox(height: 12),
              TextButton(onPressed: _loadMedication, child: const Text('다시 시도')),
            ],
          ),
        ),
      );
    }
    final entries = _medEntries;
    if (entries == null) {
      return const Center(child: CircularProgressIndicator());
    }

    return SingleChildScrollView(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '최근 통화에서 약에 대해 하신 말씀',
              style: GoogleFonts.notoSansKr(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: eInk,
              ),
            ),
            const SizedBox(height: 16),
            for (final name in _medUnconsented)
              _medCard(elder: name, line: '통화 내용 공유에 동의하기 전이에요', when: null),
            if (entries.isEmpty && _medUnconsented.isEmpty)
              const Text(
                '아직 약 복용에 대한 이야기가 없어요.',
                style: TextStyle(fontSize: 14, color: eInkSoft),
              ),
            for (final entry in entries)
              _medCard(
                elder: entry.elder,
                line: _medicationText(entry.medication),
                when: _timeText(entry.at),
              ),
          ],
        ),
      ),
    );
  }

  Widget _medCard({required String elder, required String line, required String? when}) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
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
            elder,
            style: GoogleFonts.notoSansKr(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: eInk,
            ),
          ),
          if (when != null) ...[
            const SizedBox(height: 2),
            Text(when, style: const TextStyle(fontSize: 12, color: eInkSoft)),
          ],
          const SizedBox(height: 8),
          Text(line, style: const TextStyle(fontSize: 14, color: eInk, height: 1.5)),
        ],
      ),
    );
  }

  Widget _buildHealthAlertTab() {
    if (_alertsError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                _alertsError!,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 14, color: eInkSoft),
              ),
              const SizedBox(height: 12),
              TextButton(onPressed: _loadAlerts, child: const Text('다시 시도')),
            ],
          ),
        ),
      );
    }
    final alerts = _serverAlerts;
    if (alerts == null) {
      return const Center(child: CircularProgressIndicator());
    }

    final filteredAlerts = widget.elderName == null
        ? alerts
        : alerts.where((alert) => alert.elder == widget.elderName).toList();
    if (filteredAlerts.isEmpty) {
      return const Center(
        child: Text('아직 알림이 없어요.', style: TextStyle(fontSize: 14, color: eInkSoft)),
      );
    }

    final changeAlerts = filteredAlerts.where((a) => a.type == '평소와 다름').toList();
    final noResponseAlerts = filteredAlerts.where((a) => a.type == '미응답').toList();

    return SingleChildScrollView(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (changeAlerts.isNotEmpty) ...[
              _buildAlertSection(
                title: '평소와 다름',
                color: const Color(0xFFF44336),
                alerts: changeAlerts,
              ),
              const SizedBox(height: 20),
            ],
            if (noResponseAlerts.isNotEmpty)
              _buildAlertSection(
                title: '미응답',
                color: const Color(0xFFFFA726),
                alerts: noResponseAlerts,
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildAlertSection({
    required String title,
    required Color color,
    required List<HealthAlert> alerts,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(
              title,
              style: GoogleFonts.notoSansKr(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: eInk,
              ),
            ),
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: color.withOpacity(0.15),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                '${alerts.length}건',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: color,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        ...alerts.map((alert) => _buildAlertCard(alert, color)).toList(),
      ],
    );
  }

  Widget _buildAlertCard(HealthAlert alert, Color typeColor) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: eCard,
        border: Border.all(color: typeColor.withOpacity(0.3), width: 1.5),
        borderRadius: BorderRadius.circular(12),
      ),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      alert.elder,
                      style: GoogleFonts.notoSansKr(
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                        color: eInk,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      alert.time,
                      style: const TextStyle(fontSize: 12, color: eInkSoft),
                    ),
                  ],
                ),
              ),
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
                  alert.type,
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: typeColor,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            alert.message,
            style: const TextStyle(fontSize: 13, color: eInk, height: 1.5),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Icon(Icons.lightbulb_outline_rounded, size: 16, color: typeColor),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '권고사항: ${alert.action}',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: typeColor,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildHealthCheckTab() {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(24),
        child: Text(
          '준비 중인 기능이에요',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 14, color: eInkSoft),
        ),
      ),
    );
  }
}
