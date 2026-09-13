import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'calling_screen.dart';
import 'ai_chat_screen.dart';
import 'emergency_screen.dart';
import '../../theme/app_theme.dart';

class MainScreen extends StatelessWidget {
  const MainScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: eBg,
      body: SafeArea(
        child: SingleChildScrollView(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 26, vertical: 46),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                // 인사말
                Text(
                  '오늘도\n평안한 하루\n보내세요',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.notoSerifKr(
                    fontSize: 27,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 38),

                // 다이얼 버튼
                GestureDetector(
                  onTap: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (context) => const CallingScreen(
                          callerName: 'AI 친구',
                        ),
                      ),
                    );
                  },
                  child: Container(
                    width: 216,
                    height: 216,
                    margin: const EdgeInsets.only(bottom: 16),
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      boxShadow: [
                        BoxShadow(
                          color: eAccent.withOpacity(0.38),
                          blurRadius: 32,
                          offset: const Offset(0, 16),
                        ),
                      ],
                    ),
                    child: Stack(
                      alignment: Alignment.center,
                      children: [
                        // 다이얼 링 (점선)
                        Container(
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            border: Border.all(
                              color: eBrass.withOpacity(0.4),
                              width: 2,
                              strokeAlign: BorderSide.strokeAlignOutside,
                            ),
                          ),
                        ),
                        // 다이얼 (그라데이션)
                        Container(
                          margin: const EdgeInsets.all(16),
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            gradient: RadialGradient(
                              center: const Alignment(0.35, 0.3),
                              colors: [
                                const Color(0xFFE68F5E),
                                eAccent,
                              ],
                            ),
                            boxShadow: [
                              BoxShadow(
                                color: eAccent.withOpacity(0.38),
                                blurRadius: 32,
                                offset: const Offset(0, 16),
                              ),
                            ],
                          ),
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(
                                Icons.phone,
                                size: 36,
                                color: Colors.white,
                              ),
                              const SizedBox(height: 10),
                              Text(
                                'AI 친구',
                                style: GoogleFonts.notoSerifKr(
                                  fontSize: 22,
                                  fontWeight: FontWeight.w700,
                                  color: Colors.white,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                '눌러서 통화하기',
                                style: TextStyle(
                                  fontSize: 14.5,
                                  color: Colors.white.withOpacity(0.9),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),

                const SizedBox(height: 30),

                // 메뉴 카드
                _buildMenuCard(
                  title: 'AI 채팅',
                  description: '글로 편하게 이야기해요',
                  backgroundColor: Color(0xFFF3E4D8),
                  iconColor: eBrass,
                  icon: Icons.chat_bubble_outline,
                  onTap: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (context) => const AiChatScreen(),
                      ),
                    );
                  },
                ),
                const SizedBox(height: 16),

                _buildMenuCard(
                  title: '비상 연락',
                  description: '도움이 필요할 때 눌러요',
                  backgroundColor: eAccentSoft,
                  iconColor: eAccent,
                  icon: Icons.warning_amber_rounded,
                  onTap: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (context) => const EmergencyScreen(),
                      ),
                    );
                  },
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildMenuCard({
    required String title,
    required String description,
    required Color backgroundColor,
    required Color iconColor,
    required IconData icon,
    required VoidCallback onTap,
  }) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        decoration: BoxDecoration(
          color: eCard,
          border: Border.all(color: eLine, width: 1),
          borderRadius: BorderRadius.circular(18),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 22),
        child: Row(
          children: [
            Container(
              width: 60,
              height: 60,
              decoration: BoxDecoration(
                color: backgroundColor,
                borderRadius: BorderRadius.circular(16),
              ),
              child: Icon(
                icon,
                color: iconColor,
                size: 28,
              ),
            ),
            const SizedBox(width: 18),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: GoogleFonts.notoSansKr(
                      fontSize: 22,
                      fontWeight: FontWeight.w800,
                      color: eInk,
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    description,
                    style: TextStyle(
                      fontSize: 15,
                      color: eInkSoft,
                    ),
                  ),
                ],
              ),
            ),
            Text(
              '›',
              style: TextStyle(
                fontSize: 24,
                color: eInkSoft,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
