import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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
  final TextEditingController _codeController = TextEditingController();
  bool _isLoading = false;
  String? _errorMessage;

  /// 이 폰에 어르신 열쇠가 있는가. 읽는 동안은 null이고, 그동안 연결 코드 칸을 그리지 않는다(깜빡이지 않게).
  /// 열쇠가 없으면 운영자·보호자가 미리 등록한 어르신이 보호자 앱에서 받은 6자리 코드로 이 폰을 연결한다.
  bool? _hasKey;
  late final Future<void> _keyRead;

  @override
  void initState() {
    super.initState();
    _keyRead = _readKey();
  }

  Future<void> _readKey() async {
    final key = await NulbomApi.elderKey();
    if (!mounted) return;
    setState(() => _hasKey = key != null && key.isNotEmpty);
  }

  @override
  void dispose() {
    _phoneController.dispose();
    _codeController.dispose();
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
    // 열쇠를 다 읽기 전에 눌렀으면 읽기를 기다린다. 없으면 코드 칸이 나타나고 아래에서 코드를 달라고 안내한다.
    if (_hasKey == null) {
      await _keyRead;
      if (!mounted || _hasKey == null) return;
    }
    if (_hasKey!) {
      await _loginWithSavedKey();
    } else {
      await _pairThisPhone();
    }
  }

  /// 이 폰에 어르신 열쇠가 있다: 지금처럼 번호만으로 들어간다.
  Future<void> _loginWithSavedKey() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

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

  /// 이 폰에 열쇠가 없다: 번호와 보호자가 만든 6자리 코드로 서버에서 이 폰 전용 열쇠를 받는다.
  /// 코드는 일회용이고 틀리면 서버가 횟수를 센다 — 진행 중에는 다시 보내지 않는다.
  Future<void> _pairThisPhone() async {
    final phone = _phoneController.text.trim();
    final code = _codeController.text.trim();
    if (phone.length < 10) {
      setState(() => _errorMessage = '유효한 전화번호를 입력해주세요.');
      return;
    }
    if (!RegExp(r'^\d{6}$').hasMatch(code)) {
      setState(() => _errorMessage = '연결 코드 6자리를 입력해 주세요.');
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    String? failure;
    try {
      final result = await NulbomApi.pair(code: code, phone: phone);
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

                // 이 폰에 어르신 열쇠가 없을 때만: 보호자 앱에서 받은 6자리 연결 코드
                if (_hasKey == false) ...[
                  const SizedBox(height: 20),
                  Text(
                    '처음 이 폰으로 들어오시나요? 보호자 앱에서 받은 6자리 코드를 입력해 주세요.',
                    style: GoogleFonts.notoSansKr(
                      fontSize: 15,
                      fontWeight: FontWeight.w500,
                      height: 1.5,
                      color: eInkSoft,
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    key: const Key('elder-pairing-code'),
                    controller: _codeController,
                    keyboardType: TextInputType.number,
                    maxLength: 6,
                    inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                    enabled: !_isLoading,
                    decoration: _fieldDecoration('연결 코드(6자리)'),
                  ),
                ],

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
