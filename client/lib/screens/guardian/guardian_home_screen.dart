import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';

import '../../models/call_summary.dart';
import '../../services/api_service.dart';
import '../../theme/app_theme.dart';

/// 보호자가 아침에 한 번 열어 "어머니 괜찮으신가"를 몇 초 안에 확인하는 화면.
///
/// 그래서 큰 숫자를 먼저 보여주지 않는다. 설계 3.2가 "절대값보다 개인 기준선
/// 대비 변화"라고 정한 대로 지표는 항상 '지금 / 평소' 쌍으로 붙여 둔다.
/// 0.31이라는 값 자체는 보호자에게 의미가 없고, "평소 50%였는데 오늘 31%"가
/// 의미다.
class GuardianHomeScreen extends StatefulWidget {
  const GuardianHomeScreen({super.key});

  @override
  State<GuardianHomeScreen> createState() => _GuardianHomeScreenState();
}

class _GuardianHomeScreenState extends State<GuardianHomeScreen> {
  late Future<GuardianOverview> _overview;

  @override
  void initState() {
    super.initState();
    _overview = ApiService.fetchGuardianOverview();
  }

  Future<void> _reload() async {
    setState(() {
      _overview = ApiService.fetchGuardianOverview();
    });
    await _overview;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _reload,
          color: eAccent,
          child: FutureBuilder<GuardianOverview>(
            future: _overview,
            builder: (context, snapshot) {
              if (snapshot.connectionState == ConnectionState.waiting) {
                return const Center(
                  child: CircularProgressIndicator(color: eAccent),
                );
              }
              if (snapshot.hasError || snapshot.data == null) {
                return _ErrorState(onRetry: _reload);
              }
              return _Overview(data: snapshot.data!);
            },
          ),
        ),
      ),
    );
  }
}

class _Overview extends StatelessWidget {
  const _Overview({required this.data});

  final GuardianOverview data;

  @override
  Widget build(BuildContext context) {
    final latest = data.latest;
    return ListView(
      padding: const EdgeInsets.fromLTRB(24, 28, 24, 40),
      children: [
        Text(
          data.elderName,
          style: GoogleFonts.notoSerifKr(
            fontSize: 16,
            fontWeight: FontWeight.w600,
            color: eBrass,
            letterSpacing: 1,
          ),
        ),
        const SizedBox(height: 20),
        if (latest == null)
          Text(
            '아직 분석된 통화가 없어요.',
            style: GoogleFonts.notoSerifKr(
              fontSize: 26,
              height: 1.45,
              fontWeight: FontWeight.w700,
              color: eInk,
            ),
          )
        else ...[
          Text(
            latest.summary ?? '요약을 만들지 못했어요.',
            style: GoogleFonts.notoSerifKr(
              fontSize: 26,
              height: 1.45,
              fontWeight: FontWeight.w700,
              color: eInk,
            ),
          ),
          const SizedBox(height: 20),
          _RiskChip(level: latest.riskLevel, degraded: latest.degraded),
          const SizedBox(height: 28),
          _ChangeBlock(analysis: latest),
        ],
        const SizedBox(height: 32),
        const _SectionLine(title: '최근 2주'),
        const SizedBox(height: 16),
        _TrendBars(scores: data.trend),
        const SizedBox(height: 32),
        const _SectionLine(title: '통화 기록'),
        const SizedBox(height: 4),
        for (final call in data.recentCalls) _CallRow(call: call),
      ],
    );
  }
}

/// 위험 등급은 서버가 정한 값을 그대로 보여준다. 앱이 점수로 다시 판단하지 않는다.
class _RiskChip extends StatelessWidget {
  const _RiskChip({required this.level, required this.degraded});

  final String? level;
  final bool degraded;

  @override
  Widget build(BuildContext context) {
    if (level == null) {
      return const _Pill(color: eInkSoft, text: '측정하지 못했어요');
    }
    return Row(
      children: [
        _Pill(color: riskColor(level!), text: riskLabel(level!)),
        if (degraded) ...[
          const SizedBox(width: 8),
          const _Pill(color: eInkSoft, text: '정확도 낮음'),
        ],
      ],
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.color, required this.text});

  final Color color;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.13),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 8),
          Text(
            text,
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

/// 지표를 '지금 / 평소' 쌍으로 나란히 둔다. 변화가 판정의 근거다(설계 3.2).
class _ChangeBlock extends StatelessWidget {
  const _ChangeBlock({required this.analysis});

  final CallAnalysis analysis;

  @override
  Widget build(BuildContext context) {
    final delta = analysis.baselineDelta;
    final metrics = analysis.metrics;

    final speechNow = metrics.speechRatio;
    final speechUsual = delta == null ? null : speechNow - delta.speechRatio;

    final delayNow = metrics.avgResponseDelayMs;
    final delayDelta = delta?.avgResponseDelayMs;
    final delayUsual =
        (delayDelta == null || delayNow == null) ? null : delayNow - delayDelta;

    return Column(
      children: [
        _ChangeLine(
          label: '말수',
          now: '${(speechNow * 100).round()}%',
          usual: speechUsual == null ? null : '${(speechUsual * 100).round()}%',
          worsened: delta != null && delta.speechRatio < -0.05,
        ),
        const SizedBox(height: 14),
        _ChangeLine(
          label: '대답까지',
          now: delayNow == null
              ? '대답 없음'
              : '${(delayNow / 1000).toStringAsFixed(1)}초',
          usual: delayUsual == null
              ? null
              : '${(delayUsual / 1000).toStringAsFixed(1)}초',
          worsened: delayDelta != null && delayDelta > 300,
        ),
      ],
    );
  }
}

class _ChangeLine extends StatelessWidget {
  const _ChangeLine({
    required this.label,
    required this.now,
    required this.usual,
    required this.worsened,
  });

  final String label;
  final String now;
  final String? usual;
  final bool worsened;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        SizedBox(
          width: 78,
          child: Text(label,
              style: const TextStyle(fontSize: 15, color: eInkSoft)),
        ),
        Text(
          now,
          style: GoogleFonts.notoSerifKr(
            fontSize: 22,
            fontWeight: FontWeight.w700,
            color: worsened ? eRiskAlert : eInk,
          ),
        ),
        if (usual != null) ...[
          const SizedBox(width: 12),
          Text('평소 $usual',
              style: const TextStyle(fontSize: 15, color: eInkSoft)),
        ],
      ],
    );
  }
}

class _SectionLine extends StatelessWidget {
  const _SectionLine({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Text(
          title,
          style: GoogleFonts.notoSerifKr(
            fontSize: 17,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        const SizedBox(width: 14),
        Expanded(child: Container(height: 1, color: eLine)),
      ],
    );
  }
}

/// 점수가 없는 날(미응답)은 낮은 회색 칸으로 남긴다 —
/// 0으로 그리면 "아주 좋음"으로 읽혀서 정반대 뜻이 된다.
class _TrendBars extends StatelessWidget {
  const _TrendBars({required this.scores});

  final List<int?> scores;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 72,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          for (final score in scores)
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 2),
                child: score == null
                    ? Container(
                        height: 6,
                        decoration: BoxDecoration(
                          color: eLine,
                          borderRadius: BorderRadius.circular(3),
                        ),
                      )
                    : Container(
                        height: 10 + (score / 100) * 60,
                        decoration: BoxDecoration(
                          color: riskColor(_levelOf(score))
                              .withValues(alpha: 0.85),
                          borderRadius: BorderRadius.circular(3),
                        ),
                      ),
              ),
            ),
        ],
      ),
    );
  }

  static String _levelOf(int score) {
    if (score >= 60) return 'alert';
    if (score >= 30) return 'watch';
    return 'normal';
  }
}

class _CallRow extends StatelessWidget {
  const _CallRow({required this.call});

  final CallRecord call;

  @override
  Widget build(BuildContext context) {
    final date = DateFormat('M월 d일 HH:mm').format(call.startedAt);
    final answered = call.status == 'completed';
    final seconds = call.durationSeconds ?? 0;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 16),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: eLine)),
      ),
      child: Row(
        children: [
          Expanded(
            child:
                Text(date, style: const TextStyle(fontSize: 16, color: eInk)),
          ),
          Text(
            answered ? '${seconds ~/ 60}분 ${seconds % 60}초' : '받지 않음',
            style: TextStyle(
              fontSize: 15,
              color: answered ? eInkSoft : eRiskWatch,
            ),
          ),
          const SizedBox(width: 14),
          SizedBox(
            width: 44,
            child: call.riskLevel == null
                ? const Text('—',
                    textAlign: TextAlign.right,
                    style: TextStyle(color: eInkSoft))
                : Text(
                    riskLabel(call.riskLevel!),
                    textAlign: TextAlign.right,
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: riskColor(call.riskLevel!),
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const SizedBox(height: 80),
        Text(
          '안부 기록을 불러오지 못했어요.',
          style: GoogleFonts.notoSerifKr(
            fontSize: 22,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        const SizedBox(height: 10),
        const Text(
          '인터넷 연결을 확인하고 다시 시도해 주세요.',
          style: TextStyle(fontSize: 15, color: eInkSoft, height: 1.5),
        ),
        const SizedBox(height: 24),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton(
            onPressed: onRetry,
            style: FilledButton.styleFrom(backgroundColor: eAccent),
            child: const Text('다시 불러오기'),
          ),
        ),
      ],
    );
  }
}
