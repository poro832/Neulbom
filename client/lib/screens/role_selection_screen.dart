import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'elderly_login_screen.dart';
import 'guardian_login_screen.dart';

// 색상
const Color eBg = Color(0xFFEFF6FF);
const Color eCard = Color(0xFFFFFFFF);
const Color eInk = Color(0xFF0E2548);
const Color eAccent = Color(0xFF1A6BFF);

class RoleSelectionScreen extends StatelessWidget {
  const RoleSelectionScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: eBg,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 26, vertical: 60),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              // 타이틀
              Text(
                '늘봄',
                textAlign: TextAlign.center,
                style: GoogleFonts.notoSansKr(
                  fontSize: 48,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 16),
              Text(
                '당신의 역할을 선택해주세요',
                textAlign: TextAlign.center,
                style: GoogleFonts.notoSansKr(
                  fontSize: 18,
                  fontWeight: FontWeight.w400,
                  color: eInk,
                  height: 1.5,
                ),
              ),
              const SizedBox(height: 80),

              // 어르신 버튼
              GestureDetector(
                onTap: () {
                  Navigator.pushReplacement(
                    context,
                    MaterialPageRoute(
                      builder: (context) => const ElderlyLoginScreen(),
                    ),
                  );
                },
                child: Container(
                  width: double.infinity,
                  height: 140,
                  decoration: BoxDecoration(
                    color: eCard,
                    border: Border.all(color: eAccent, width: 2),
                    borderRadius: BorderRadius.circular(20),
                    boxShadow: [
                      BoxShadow(
                        color: eAccent.withOpacity(0.1),
                        blurRadius: 12,
                        offset: const Offset(0, 4),
                      ),
                    ],
                  ),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(
                        Icons.person_outline_rounded,
                        size: 48,
                        color: eAccent,
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '어르신',
                        style: GoogleFonts.notoSansKr(
                          fontSize: 24,
                          fontWeight: FontWeight.w700,
                          color: eInk,
                        ),
                      ),
                    ],
                  ),
                ),
              ),

              const SizedBox(height: 24),

              // 보호자 버튼
              GestureDetector(
                onTap: () {
                  Navigator.pushReplacement(
                    context,
                    MaterialPageRoute(
                      builder: (context) => const GuardianLoginScreen(),
                    ),
                  );
                },
                child: Container(
                  width: double.infinity,
                  height: 140,
                  decoration: BoxDecoration(
                    color: eCard,
                    border: Border.all(color: eAccent, width: 2),
                    borderRadius: BorderRadius.circular(20),
                    boxShadow: [
                      BoxShadow(
                        color: eAccent.withOpacity(0.1),
                        blurRadius: 12,
                        offset: const Offset(0, 4),
                      ),
                    ],
                  ),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(
                        Icons.shield_outlined,
                        size: 48,
                        color: eAccent,
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '보호자',
                        style: GoogleFonts.notoSansKr(
                          fontSize: 24,
                          fontWeight: FontWeight.w700,
                          color: eInk,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
