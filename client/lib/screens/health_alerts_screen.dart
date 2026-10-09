import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../models/nulbom_models.dart' show AlertItem;
import '../services/nulbom_api.dart';

const Color eBg = Color(0xFFFBF6ED);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);

class MedicationAlert {
  final String elder;
  final String name;
  final String time;
  final String dosage;
  final String nextAlert;
  final bool notified;

  MedicationAlert({
    required this.elder,
    required this.name,
    required this.time,
    required this.dosage,
    required this.nextAlert,
    required this.notified,
  });
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

class HealthCheck {
  final String date;
  final String time;
  final String elder;
  final String duration;
  final String status;
  final String notes;

  HealthCheck({
    required this.date,
    required this.time,
    required this.elder,
    required this.duration,
    required this.status,
    required this.notes,
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

  // 건강 경고 탭은 서버의 실제 알림을 보여 준다. (약물·건강 확인 탭은 아직 서버 자료가 없다.)
  List<HealthAlert>? _serverAlerts;
  String? _alertsError;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(
      length: 3,
      vsync: this,
      initialIndex: widget.initialTabIndex,
    );
    _loadAlerts();
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
    final medications = <MedicationAlert>[
      MedicationAlert(
        elder: '김할머니',
        name: '혈압약',
        time: '09:00',
        dosage: '1일 1회',
        nextAlert: '내일 09:00',
        notified: true,
      ),
      MedicationAlert(
        elder: '김할머니',
        name: '당뇨약',
        time: '12:00',
        dosage: '1일 1회',
        nextAlert: '내일 12:00',
        notified: true,
      ),
      MedicationAlert(
        elder: '이할아버지',
        name: '수면제',
        time: '21:00',
        dosage: '1일 1회',
        nextAlert: '오늘 21:00',
        notified: false,
      ),
    ];

    final filteredMedications = widget.elderName == null
        ? medications
        : medications
              .where((medication) => medication.elder == widget.elderName)
              .toList();

    return SingleChildScrollView(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '약물 복용 일정 및 알림',
              style: GoogleFonts.notoSerifKr(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: eInk,
              ),
            ),
            const SizedBox(height: 16),
            ...filteredMedications.map((med) {
              return Container(
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
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              med.elder,
                              style: const TextStyle(
                                fontSize: 12,
                                color: eInkSoft,
                              ),
                            ),
                            const SizedBox(height: 2),
                            Text(
                              med.name,
                              style: GoogleFonts.notoSansKr(
                                fontSize: 16,
                                fontWeight: FontWeight.w700,
                                color: eInk,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              '${med.time} (${med.dosage})',
                              style: const TextStyle(
                                fontSize: 13,
                                color: eInkSoft,
                              ),
                            ),
                          ],
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 6,
                          ),
                          decoration: BoxDecoration(
                            color: med.notified
                                ? const Color(0xFF4CAF50).withOpacity(0.15)
                                : eAccent.withOpacity(0.15),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Text(
                            med.notified ? '알림 완료' : '알림 대기',
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: med.notified
                                  ? const Color(0xFF4CAF50)
                                  : eAccent,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        const Icon(
                          Icons.notifications_active_rounded,
                          size: 16,
                          color: eInkSoft,
                        ),
                        const SizedBox(width: 8),
                        Text(
                          '다음 알림: ${med.nextAlert}',
                          style: const TextStyle(fontSize: 12, color: eInkSoft),
                        ),
                      ],
                    ),
                  ],
                ),
              );
            }).toList(),
            const SizedBox(height: 16),
            Container(
              decoration: BoxDecoration(
                color: eAccent.withOpacity(0.1),
                border: Border.all(color: eAccent.withOpacity(0.2)),
                borderRadius: BorderRadius.circular(12),
              ),
              padding: const EdgeInsets.all(14),
              child: Row(
                children: [
                  const Icon(
                    Icons.info_outline_rounded,
                    color: eAccent,
                    size: 20,
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      '보호자와 어르신 모두에게 약물 복용 시간에 푸시 알림이 전송됩니다.',
                      style: TextStyle(
                        fontSize: 12,
                        color: eInkSoft,
                        height: 1.5,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
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
                icon: Icons.trending_up_rounded,
                color: const Color(0xFFF44336),
                alerts: changeAlerts,
              ),
              const SizedBox(height: 20),
            ],
            if (noResponseAlerts.isNotEmpty)
              _buildAlertSection(
                title: '미응답',
                icon: Icons.phone_missed_rounded,
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
    required IconData icon,
    required Color color,
    required List<HealthAlert> alerts,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, color: color, size: 24),
            const SizedBox(width: 12),
            Text(
              title,
              style: GoogleFonts.notoSerifKr(
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
    final healthChecks = <HealthCheck>[
      HealthCheck(
        date: '2024-12-15',
        time: '15:30',
        elder: '김할머니',
        duration: '15분',
        status: '정상',
        notes: '통화 종료 후 건강 상태 확인 완료. 특이사항 없음.',
      ),
      HealthCheck(
        date: '2024-12-14',
        time: '14:15',
        elder: '이할아버지',
        duration: '10분',
        status: '정상',
        notes: '건강 상태 점검. 모든 지표 정상 범위.',
      ),
      HealthCheck(
        date: '2024-12-13',
        time: '16:45',
        elder: '김할머니',
        duration: '25분',
        status: '정상',
        notes: '상세 건강 확인 완료. 긍정적인 감정 상태 유지.',
      ),
    ];

    final filteredHealthChecks = widget.elderName == null
        ? healthChecks
        : healthChecks
              .where((check) => check.elder == widget.elderName)
              .toList();

    return SingleChildScrollView(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: filteredHealthChecks.map((check) {
            return Container(
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
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            check.elder,
                            style: GoogleFonts.notoSansKr(
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                              color: eInk,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            '${check.date} ${check.time}',
                            style: const TextStyle(
                              fontSize: 12,
                              color: eInkSoft,
                            ),
                          ),
                        ],
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 6,
                        ),
                        decoration: BoxDecoration(
                          color: const Color(0xFF4CAF50).withOpacity(0.15),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          check.status,
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color: Color(0xFF4CAF50),
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: eBg,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(
                              Icons.phone_rounded,
                              size: 16,
                              color: eAccent,
                            ),
                            const SizedBox(width: 8),
                            Text(
                              '통화 시간: ${check.duration}',
                              style: const TextStyle(
                                fontSize: 12,
                                color: eInkSoft,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text(
                          check.notes,
                          style: const TextStyle(
                            fontSize: 12,
                            color: eInkSoft,
                            height: 1.5,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            );
          }).toList(),
        ),
      ),
    );
  }
}
