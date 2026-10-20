import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../services/auth_service.dart';
import '../services/nulbom_api.dart';
import 'elderly_signup_screen.dart';
import 'elderly_gate.dart';
import 'role_selection_screen.dart';

const Color eBg = Color(0xFFEFF6FF);
const Color eCard = Color(0xFFFFFFFF);
const Color eInk = Color(0xFF0E2548);
const Color eInkSoft = Color(0xFF3C5C8C);
const Color eLine = Color(0xFFD6E4FF);
const Color eAccent = Color(0xFF1A6BFF);

class ElderlyLoginScreen extends StatefulWidget {
  const ElderlyLoginScreen({super.key});

  @override
  State<ElderlyLoginScreen> createState() => _ElderlyLoginScreenState();
}

class _ElderlyLoginScreenState extends State<ElderlyLoginScreen> {
  static const String _offline = '서버에 연결하지 못했어요. 잠시 뒤에 다시 해 주세요.';

  final TextEditingController _phoneController = TextEditingController();
  bool _isLoading = false;
  String? _errorMessage;

  @override
  void dispose() {
    _phoneController.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    if (_isLoading) return;
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

    // 이 폰에 열쇠가 없으면 새 폰이다: 보호자가 어르신 관리에서 번호를 고쳐 열어 둔 번호만 서버가 열쇠를 준다.
    final hasKey = (await NulbomApi.elderKey())?.isNotEmpty ?? false;
    if (!hasKey) {
      await _loginOnNewPhone();
      return;
    }

    final result = await AuthService.elderlyLogin(phone: _phoneController.text);
    if (!mounted) return;

    setState(() {
      _isLoading = false;
    });

    if (result['success']) {
      _enterGate();
    } else {
      setState(() {
        _errorMessage = result['message'];
      });
    }
  }

  /// 새 폰: 번호만으로 서버에 열쇠를 청한다. 보호자가 번호를 고쳐 둔 뒤 24시간 안에, 한 번만 받는다.
  Future<void> _loginOnNewPhone() async {
    final phone = _phoneController.text.trim();
    if (phone.length < 10) {
      setState(() {
        _isLoading = false;
        _errorMessage = '유효한 전화번호를 입력해주세요.';
      });
      return;
    }

    String? failure;
    try {
      final result = await NulbomApi.claimNewPhone(phone: phone);
      await AuthService.rememberElder(name: result.elderName, phone: phone);
    } on ApiException catch (error) {
      failure = error.message;
    } catch (_) {
      failure = _offline;
    }
    if (!mounted) return;

    if (failure == null) {
      _enterGate();
      return;
    }
    setState(() {
      _isLoading = false;
      _errorMessage = failure;
    });
  }

  void _enterGate() {
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (context) => const ElderlyGate()),
      (route) => false,
    );
  }

  InputDecoration _fieldDecoration(String hint) {
    return InputDecoration(
      hintText: hint,
      hintStyle: const TextStyle(color: eInkSoft),
      counterText: '',
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
    );
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
          style: GoogleFonts.notoSansKr(
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
                  style: GoogleFonts.notoSansKr(
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
                  style: GoogleFonts.notoSansKr(
                    fontSize: 20,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                  ),
                ),
                const SizedBox(height: 16),

                TextField(
                  key: const Key('elder-login-phone'),
                  controller: _phoneController,
                  keyboardType: TextInputType.phone,
                  enabled: !_isLoading,
                  decoration: _fieldDecoration('전화번호 (예: 01012345678)'),
                ),
                const SizedBox(height: 10),
                Text(
                  '폰을 바꿨다면 보호자가 어르신 관리에서 번호를 고친 뒤 24시간 안에 한 번 로그인할 수 있어요.',
                  style: GoogleFonts.notoSansKr(fontSize: 14, height: 1.5, color: eInkSoft),
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
