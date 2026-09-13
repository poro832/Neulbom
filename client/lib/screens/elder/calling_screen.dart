import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../../theme/app_theme.dart';


class CallingScreen extends StatefulWidget {
  final String callerName;

  const CallingScreen({
    super.key,
    required this.callerName,
  });

  @override
  State<CallingScreen> createState() => _CallingScreenState();
}

class _CallingScreenState extends State<CallingScreen>
    with SingleTickerProviderStateMixin {
  late Duration _callDuration;
  late DateTime _callStartTime;
  late AnimationController _pulseController;

  @override
  void initState() {
    super.initState();
    _callStartTime = DateTime.now();
    _callDuration = Duration.zero;
    _startTimer();

    _pulseController = AnimationController(
      duration: const Duration(milliseconds: 2400),
      vsync: this,
    )..repeat();
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  void _startTimer() {
    Future.delayed(const Duration(seconds: 1), () {
      if (mounted) {
        setState(() {
          _callDuration = DateTime.now().difference(_callStartTime);
        });
        _startTimer();
      }
    });
  }

  String _formatDuration(Duration duration) {
    String twoDigits(int n) => n.toString().padLeft(2, '0');
    String twoDigitMinutes = twoDigits(duration.inMinutes.remainder(60));
    String twoDigitSeconds = twoDigits(duration.inSeconds.remainder(60));
    return "${twoDigits(duration.inHours)}:$twoDigitMinutes:$twoDigitSeconds";
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
          child: Column(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              // 상단 여백
              const SizedBox(height: 50),

              // 중앙: 아바타 + 이름 + 타이머
              Column(
                children: [
                  // 아바타 (맥박 애니메이션)
                  SizedBox(
                    width: 160,
                    height: 160,
                    child: Stack(
                      alignment: Alignment.center,
                      children: [
                        // 펄스 링 1
                        ScaleTransition(
                          scale: Tween<double>(begin: 0.75, end: 1.15).animate(
                            CurvedAnimation(
                              parent: _pulseController,
                              curve: const Interval(0, 1, curve: Curves.easeOut),
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

                        // 펄스 링 2 (딜레이)
                        ScaleTransition(
                          scale: Tween<double>(begin: 0.75, end: 1.15).animate(
                            CurvedAnimation(
                              parent: _pulseController,
                              curve: const Interval(0.33, 1, curve: Curves.easeOut),
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

                        // 아바타
                        Container(
                          width: 130,
                          height: 130,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: Colors.white.withOpacity(0.25),
                          ),
                          child: const Icon(
                            Icons.person,
                            size: 60,
                            color: Colors.white,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),

                  // 이름
                  Text(
                    _callDurationFormattedName,
                    style: GoogleFonts.notoSerifKr(
                      fontSize: 24,
                      fontWeight: FontWeight.w700,
                      color: Colors.white,
                    ),
                  ),
                  const SizedBox(height: 6),

                  // 타이머
                  Text(
                    _formatDuration(_callDuration),
                    style: TextStyle(
                      fontSize: 17,
                      color: Colors.white.withOpacity(0.85),
                      fontFeatures: const [FontFeature.tabularFigures()],
                    ),
                  ),
                ],
              ),

              // 하단: 통화 종료 버튼
              Padding(
                padding: const EdgeInsets.only(bottom: 40),
                child: Column(
                  children: [
                    GestureDetector(
                      onTap: () {
                        Navigator.pop(context);
                      },
                      child: Container(
                        width: 64,
                        height: 64,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: Colors.white,
                          boxShadow: [
                            BoxShadow(
                              color: Colors.black.withOpacity(0.25),
                              blurRadius: 24,
                              offset: const Offset(0, 10),
                            ),
                          ],
                        ),
                        child: const Icon(
                          Icons.call_end,
                          color: Color(0xFFC0553F),
                          size: 28,
                        ),
                      ),
                    ),
                    const SizedBox(height: 10),
                    const Text(
                      '종료',
                      style: TextStyle(
                        fontSize: 14,
                        color: Colors.white,
                      ),
                    ),
                    const SizedBox(height: 14),
                    Text(
                      '대화 내용이 자동으로 녹음되며\n분석 결과는 보호자에게 전송됩니다',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 13,
                        color: Colors.white.withOpacity(0.8),
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

  String get _callDurationFormattedName {
    return widget.callerName;
  }
}
