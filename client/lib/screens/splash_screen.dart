import 'dart:async';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

const Color _bg = Color(0xFFEFF6FF);
const Color _ink = Color(0xFF0E2548);
const Color _inkSoft = Color(0xFF3C5C8C);
const Color _accent = Color(0xFF1A6BFF);
const Color _sun = Color(0xFFFFB400);
const Color _hill = Color(0xFFF3F8FF);

/// 앱을 켜면 소개 화면을 이 시간 이상 보여 준다. 로그인 상태 확인이 더 일찍 끝나도 이름과 로고를 알아볼 시간을 준다.
const Duration kSplashMinimum = Duration(milliseconds: 1600);

/// 한 줄 소개. 늘봄이 무엇인지 첫 화면에서 알린다.
const String kSplashTagline = '매일 안부를 전하는 AI 친구';

/// 앱 아이콘과 같은 모양의 로고 — 파란 바탕, 노란 해, 하얀 언덕, 그 위의 새싹(늘봄 = 늘 봄).
/// 사진이 아니라 그려서 크기를 키워도 선명하다.
class NulbomMark extends StatelessWidget {
  final double size;

  const NulbomMark({super.key, this.size = 132});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(painter: _MarkPainter()),
    );
  }
}

class _MarkPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width;
    final box = Offset.zero & size;
    canvas.save();
    canvas.clipRRect(RRect.fromRectAndRadius(box, Radius.circular(s * 0.24)));

    canvas.drawRect(box, Paint()..color = _accent);
    // 해
    canvas.drawCircle(Offset(s * 0.5, s * 0.42), s * 0.19, Paint()..color = _sun);
    // 언덕
    canvas.drawOval(Rect.fromLTRB(-s * 0.32, s * 0.60, s * 1.32, s * 1.55), Paint()..color = _hill);
    // 새싹
    final sprout = Paint()
      ..color = _accent
      ..style = PaintingStyle.stroke
      ..strokeWidth = s * 0.038
      ..strokeCap = StrokeCap.round;
    final path = Path()
      ..moveTo(s * 0.5, s * 0.88)
      ..lineTo(s * 0.5, s * 0.77)
      ..moveTo(s * 0.5, s * 0.77)
      ..lineTo(s * 0.43, s * 0.70)
      ..moveTo(s * 0.5, s * 0.77)
      ..lineTo(s * 0.57, s * 0.68);
    canvas.drawPath(path, sprout);
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/// 앱을 처음 켤 때 보이는 소개 화면 겸 로딩 화면.
class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> with SingleTickerProviderStateMixin {
  late final AnimationController _controller =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 900))..forward();
  late final Animation<double> _fade = CurvedAnimation(parent: _controller, curve: Curves.easeOut);
  late final Animation<Offset> _rise =
      Tween<Offset>(begin: const Offset(0, 0.06), end: Offset.zero).animate(_fade);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      key: const Key('splash-screen'),
      backgroundColor: _bg,
      body: SafeArea(
        child: SizedBox.expand(
          child: Column(
            children: [
              const Spacer(flex: 5),
              FadeTransition(
                opacity: _fade,
                child: SlideTransition(
                  position: _rise,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(32),
                          boxShadow: [
                            BoxShadow(color: _accent.withValues(alpha: 0.28), blurRadius: 36, offset: const Offset(0, 14)),
                          ],
                        ),
                        child: const NulbomMark(size: 132),
                      ),
                      const SizedBox(height: 32),
                      Text('늘봄',
                          style: GoogleFonts.notoSansKr(
                              fontSize: 56, fontWeight: FontWeight.w800, color: _ink, height: 1.1)),
                      const SizedBox(height: 14),
                      Text(kSplashTagline,
                          style: GoogleFonts.notoSansKr(
                              fontSize: 19, fontWeight: FontWeight.w500, color: _inkSoft, height: 1.4)),
                    ],
                  ),
                ),
              ),
              const Spacer(flex: 4),
              // 불러오는 동안 보이는 표시 — 이 화면이 로딩 화면을 겸한다.
              const SizedBox(
                key: Key('splash-loading'),
                width: 28,
                height: 28,
                child: CircularProgressIndicator(strokeWidth: 3, valueColor: AlwaysStoppedAnimation<Color>(_accent)),
              ),
              const SizedBox(height: 12),
              Text('불러오는 중이에요',
                  style: GoogleFonts.notoSansKr(fontSize: 14, fontWeight: FontWeight.w500, color: _inkSoft)),
              const SizedBox(height: 56),
            ],
          ),
        ),
      ),
    );
  }
}

/// 소개 화면을 보여 주다가, **최소 시간이 지나고 다음 화면이 정해지면** 부드럽게 바꾼다.
///
/// 다음 화면을 정하는 일(로그인 상태 확인)이 소개 시간보다 오래 걸리면 끝날 때까지 기다리고,
/// 더 빨리 끝나면 최소 시간까지 기다린다. 확인이 실패하면 [fallback]으로 간다.
class SplashGate extends StatefulWidget {
  final Future<Widget> destination;
  final Widget fallback;
  final Duration minimum;

  const SplashGate({
    super.key,
    required this.destination,
    required this.fallback,
    this.minimum = kSplashMinimum,
  });

  @override
  State<SplashGate> createState() => _SplashGateState();
}

class _SplashGateState extends State<SplashGate> {
  Timer? _timer;
  bool _timeUp = false;
  Widget? _ready;
  Widget? _shown;

  @override
  void initState() {
    super.initState();
    _timer = Timer(widget.minimum, () {
      _timeUp = true;
      _maybeShow();
    });
    widget.destination.then((screen) => screen, onError: (_) => widget.fallback).then((screen) {
      _ready = screen;
      _maybeShow();
    });
  }

  void _maybeShow() {
    if (!mounted || !_timeUp || _ready == null) return;
    setState(() => _shown = _ready);
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final shown = _shown;
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 380),
      child: shown == null
          ? const SplashScreen(key: ValueKey('splash'))
          : KeyedSubtree(key: const ValueKey('destination'), child: shown),
    );
  }
}
