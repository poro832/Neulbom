import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../services/auth_service.dart';
import 'elderly_signup_screen.dart';
import 'elderly_home_page.dart';
import 'role_selection_screen.dart';

const Color eBg = Color(0xFFFBF6ED);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);

class ElderlyLoginScreen extends StatefulWidget {
  const ElderlyLoginScreen({super.key});

  @override
  State<ElderlyLoginScreen> createState() => _ElderlyLoginScreenState();
}

class _ElderlyLoginScreenState extends State<ElderlyLoginScreen> {
  final TextEditingController _phoneController = TextEditingController();
  bool _isLoading = false;
  String? _errorMessage;

  @override
  void dispose() {
    _phoneController.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    if (_phoneController.text.isEmpty) {
      setState(() {
        _errorMessage = '전화번호를 입력해주세요.';
      });
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    final result = await AuthService.elderlyLogin(phone: _phoneController.text);

    setState(() {
      _isLoading = false;
    });

    if (result['success']) {
      if (!mounted) return;
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (context) => const ElderlyHomePage()),
      );
    } else {
      setState(() {
        _errorMessage = result['message'];
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        leading: Padding(
          padding: const EdgeInsets.all(8.0),
          child: IconButton(
            icon: Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: Colors.white,
                border: Border.all(color: eLine, width: 2),
                boxShadow: [
                  BoxShadow(
                    color: eInk.withOpacity(0.1),
                    blurRadius: 6,
                    spreadRadius: 1,
                  ),
                ],
              ),
              child: const Icon(Icons.chevron_left, color: eInk, size: 24),
            ),
            onPressed: () {
              Navigator.pushReplacement(
                context,
                MaterialPageRoute(
                  builder: (context) => const RoleSelectionScreen(),
                ),
              );
            },
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(
              minWidth: 44,
              minHeight: 44,
            ),
          ),
        ),
        title: Text(
          '어르신 로그인',
          style: GoogleFonts.notoSerifKr(
            fontSize: 21,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        centerTitle: false,
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 26, vertical: 46),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 로고/제목
                Text(
                  '늘봄',
                  style: GoogleFonts.notoSerifKr(
                    fontSize: 32,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  '어르신의 따뜻한 친구',
                  style: GoogleFonts.notoSansKr(
                    fontSize: 16,
                    fontWeight: FontWeight.w500,
                    color: eInkSoft,
                  ),
                ),
                const SizedBox(height: 54),

                // 전화번호 입력
                Text(
                  '전화번호 로그인',
                  style: GoogleFonts.notoSerifKr(
                    fontSize: 20,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                  ),
                ),
                const SizedBox(height: 16),

                TextField(
                  controller: _phoneController,
                  keyboardType: TextInputType.phone,
                  enabled: !_isLoading,
                  decoration: InputDecoration(
                    hintText: '전화번호 (예: 01012345678)',
                    hintStyle: const TextStyle(color: eInkSoft),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: const BorderSide(color: eLine),
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: const BorderSide(color: eLine),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: const BorderSide(color: eAccent, width: 2),
                    ),
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 14,
                    ),
                  ),
                ),

                // 에러 메시지
                if (_errorMessage != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(
                      _errorMessage!,
                      style: const TextStyle(
                        color: Color(0xFFF44336),
                        fontSize: 13,
                      ),
                    ),
                  ),

                const SizedBox(height: 24),

                // 로그인 버튼
                SizedBox(
                  width: double.infinity,
                  height: 56,
                  child: ElevatedButton(
                    onPressed: _isLoading ? null : _login,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: eAccent,
                      disabledBackgroundColor: eInkSoft.withOpacity(0.3),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                    child: _isLoading
                        ? const SizedBox(
                            width: 24,
                            height: 24,
                            child: CircularProgressIndicator(
                              valueColor: AlwaysStoppedAnimation<Color>(
                                Colors.white,
                              ),
                              strokeWidth: 2,
                            ),
                          )
                        : Text(
                            '로그인',
                            style: GoogleFonts.notoSansKr(
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                              color: Colors.white,
                            ),
                          ),
                  ),
                ),

                const SizedBox(height: 48),

                // 회원가입 링크
                Center(
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(
                        '계정이 없으신가요?',
                        style: TextStyle(
                          fontSize: 14,
                          color: eInkSoft,
                        ),
                      ),
                      const SizedBox(width: 8),
                      GestureDetector(
                        onTap: _isLoading
                            ? null
                            : () {
                                Navigator.push(
                                  context,
                                  MaterialPageRoute(
                                    builder: (context) =>
                                        const ElderlySignupScreen(),
                                  ),
                                );
                              },
                        child: Text(
                          '회원가입',
                          style: GoogleFonts.notoSansKr(
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                            color: eAccent,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
