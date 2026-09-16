import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';

/// "곧 전화가 갑니다" 대기 화면 (전화망 설계 5장).
///
/// 이 화면은 통화를 하지 않는다. 서버에 전화를 걸어 달라고 요청하고,
/// 어르신 전화기가 울리기를 기다릴 뿐이다. 종료 버튼을 두지 않는 이유는
/// 앱이 전화망 통화를 끊을 수 없기 때문이다 — 눌렀는데 안 끊기면
/// 가장 나쁜 종류의 혼란이 된다.
class CallingScreen extends StatefulWidget {
  final String callerName;
  final int elderId;

  const CallingScreen({
    super.key,
    required this.callerName,
    this.elderId = 1,
  });

  @override
  State<CallingScreen> createState() => _CallingScreenState();
}

enum _Phase { requesting, waiting, failed }

class _CallingScreenState extends State<CallingScreen>
    with SingleTickerProviderStateMixin {
  late AnimationController _pulseController;
  _Phase _phase = _Phase.requesting;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      duration: const Duration(milliseconds: 2400),
      vsync: this,
    )..repeat();
    _request();
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  Future<void> _request() async {
    try {
      await ApiService.requestCall(elderId: widget.elderId);
      // 409(이미 진행 중)도 성공으로 다룬다. 어르신 입장에서는
      // "전화가 오고 있다"로 똑같다.
      if (mounted) setState(() => _phase = _Phase.waiting);
    } catch (_) {
      if (mounted) setState(() => _phase = _Phase.failed);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: BoxDecoration(
          gradient: RadialGradient(
            center: const Alignment(0.5, 0.3),
            colors: [
              const Color(0xFFE68F5E),
              eAccent,
              const Color(0xFFA3502C),
            ],
            stops: const [0, 0.65, 0.75],
          ),
        ),
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _avatar(),
                const SizedBox(height: 32),
                Text(
                  _headline,
                  textAlign: TextAlign.center,
                  style: GoogleFonts.notoSerifKr(
                    fontSize: 30,
                    height: 1.4,
                    fontWeight: FontWeight.w700,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(height: 16),
                Text(
                  _detail,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 19,
                    height: 1.6,
                    color: Colors.white.withOpacity(0.9),
                  ),
                ),
                const SizedBox(height: 40),
                _action(),
              ],
            ),
          ),
        ),
      ),
    );
  }

  String get _headline {
    switch (_phase) {
      case _Phase.requesting:
        return '전화를 거는 중이에요';
      case _Phase.waiting:
        return '곧 전화가\n갑니다';
      case _Phase.failed:
        return '전화를 걸지\n못했어요';
    }
  }

  String get _detail {
    switch (_phase) {
      case _Phase.requesting:
        return '잠시만 기다려 주세요';
      case _Phase.waiting:
        return '전화기가 울리면 받아 주세요.\n대화 내용은 보호자에게 전해집니다.';
      case _Phase.failed:
        return '잠시 후 다시 시도해 주세요';
    }
  }

  Widget _action() {
    if (_phase == _Phase.failed) {
      return _button('다시 시도', () {
        setState(() => _phase = _Phase.requesting);
        _request();
      });
    }
    return _button('닫기', () => Navigator.pop(context));
  }

  Widget _button(String label, VoidCallback onTap) {
    return SizedBox(
      width: double.infinity,
      height: 64,
      child: ElevatedButton(
        onPressed: onTap,
        style: ElevatedButton.styleFrom(
          backgroundColor: Colors.white,
          foregroundColor: const Color(0xFFC0553F),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
        ),
        child: Text(label, style: const TextStyle(fontSize: 21)),
      ),
    );
  }

  Widget _avatar() {
    return SizedBox(
      width: 160,
      height: 160,
      child: Stack(
        alignment: Alignment.center,
        children: [
          for (final start in const [0.0, 0.33])
            ScaleTransition(
              scale: Tween<double>(begin: 0.75, end: 1.15).animate(
                CurvedAnimation(
                  parent: _pulseController,
                  curve: Interval(start, 1, curve: Curves.easeOut),
                ),
              ),
              child: Container(
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: Colors.white.withOpacity(0.4),
                    width: 1.5,
                    strokeAlign: BorderSide.strokeAlignOutside,
                  ),
                ),
              ),
            ),
          Container(
            width: 130,
            height: 130,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: Colors.white.withOpacity(0.25),
            ),
            child: const Icon(Icons.phone_in_talk, size: 60, color: Colors.white),
          ),
        ],
      ),
    );
  }
}
