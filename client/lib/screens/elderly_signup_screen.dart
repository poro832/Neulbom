import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../services/auth_service.dart';
import '../services/nulbom_api.dart';
import 'elderly_gate.dart';

const Color eBg = Color(0xFFEFF6FF);
const Color eCard = Color(0xFFFFFFFF);
const Color eInk = Color(0xFF0E2548);
const Color eInkSoft = Color(0xFF3C5C8C);
const Color eLine = Color(0xFFD6E4FF);
const Color eAccent = Color(0xFF1A6BFF);

/// 어르신이 보호자 없이 먼저 가입한다. 가입하면 서버가 이 폰 전용 열쇠와 8자리 연결 코드(24시간)를
/// 주고, 어르신이 그 코드를 보호자에게 알려 준다. 보호자가 코드를 확인해 연결하기 전에는 전화가 오지 않는다.
class ElderlySignupScreen extends StatefulWidget {
  const ElderlySignupScreen({super.key});

  @override
  State<ElderlySignupScreen> createState() => _ElderlySignupScreenState();
}

class _ElderlySignupScreenState extends State<ElderlySignupScreen> {
  final TextEditingController _nameController = TextEditingController();
  final TextEditingController _phoneController = TextEditingController();
  bool _isLoading = false;
  bool _isSignupComplete = false;
  String? _errorMessage;
  String? _connectionCode;
  String? _codeError;
  bool _agreed = false;

  static const String _offline = '서버에 연결하지 못했어요. 잠시 뒤에 다시 해 주세요.';

  @override
  void dispose() {
    _nameController.dispose();
    _phoneController.dispose();
    super.dispose();
  }

  Future<void> _signup() async {
    final name = _nameController.text.trim();
    final phone = _phoneController.text.trim();

    if (name.isEmpty) {
      setState(() {
        _errorMessage = '이름을 입력해주세요.';
      });
      return;
    }

    if (phone.isEmpty) {
      setState(() {
        _errorMessage = '전화번호를 입력해주세요.';
      });
      return;
    }

    if (phone.length < 10) {
      setState(() {
        _errorMessage = '유효한 전화번호를 입력해주세요.';
      });
      return;
    }

    // 서버도 동의 없는 가입을 거절한다(400). 그 전에 화면에서 막아 서버를 부르지 않는다.
    if (!_agreed) {
      setState(() {
        _errorMessage = '안부 전화를 받는 데 동의해 주세요.';
      });
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    String? code;
    try {
      // 서버가 이 폰 전용 열쇠와 고정 연결 코드를 주고, NulbomApi가 열쇠를 폰에 저장한다.
      code = (await NulbomApi.elderSignup(name: name, phone: phone, agreed: true)).linkCode;
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _isLoading = false;
        _errorMessage = error is ApiException ? error.message : _offline;
      });
      return;
    }
    await AuthService.rememberElder(name: name, phone: phone);

    // 가입은 끝났다. 코드를 못 받았어도 다음 화면과 메뉴의 "내 연결코드"에서 다시 볼 수 있다.
    String? codeError;
    if (code == null) {
      try {
        code = await NulbomApi.myLinkCode();
      } catch (error) {
        codeError = error is ApiException ? error.message : _offline;
      }
    }
    if (!mounted) return;
    setState(() {
      _isLoading = false;
      _isSignupComplete = true;
      _connectionCode = code;
      _codeError = codeError;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_isSignupComplete) {
      return _buildSignupCompleteScreen();
    }

    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded, color: eInk),
          onPressed: () => Navigator.pop(context),
        ),
      ),
      body: SingleChildScrollView(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 26, vertical: 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '회원가입',
                style: GoogleFonts.notoSansKr(
                  fontSize: 28,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                '어르신의 정보를 입력해주세요',
                style: TextStyle(fontSize: 14, color: eInkSoft),
              ),
              const SizedBox(height: 32),

              // 이름
              Text(
                '이름',
                style: GoogleFonts.notoSansKr(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _nameController,
                enabled: !_isLoading,
                decoration: InputDecoration(
                  hintText: '이름을 입력해주세요',
                  hintStyle: const TextStyle(color: eInkSoft),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                    borderSide: const BorderSide(color: eLine),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                    borderSide: const BorderSide(color: eLine),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                    borderSide: const BorderSide(color: eAccent, width: 2),
                  ),
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 12,
                  ),
                ),
              ),
              const SizedBox(height: 20),

              // 전화번호
              Text(
                '전화번호',
                style: GoogleFonts.notoSansKr(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _phoneController,
                enabled: !_isLoading,
                keyboardType: TextInputType.phone,
                decoration: InputDecoration(
                  hintText: '전화번호 (예: 01012345678)',
                  hintStyle: const TextStyle(color: eInkSoft),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                    borderSide: const BorderSide(color: eLine),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                    borderSide: const BorderSide(color: eLine),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                    borderSide: const BorderSide(color: eAccent, width: 2),
                  ),
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 12,
                  ),
                ),
              ),
              const SizedBox(height: 20),

              // 안부 전화·통화 내용 공유 동의 (서버가 동의 없는 가입을 거절한다)
              CheckboxListTile(
                value: _agreed,
                onChanged: _isLoading ? null : (value) => setState(() => _agreed = value ?? false),
                controlAffinity: ListTileControlAffinity.leading,
                contentPadding: EdgeInsets.zero,
                activeColor: eAccent,
                title: Text(
                  '늘봄 AI가 안부 전화를 거는 데 동의하고, 통화 내용이 보호자에게 요약과 원문으로 공유되는 것에 동의합니다.',
                  style: GoogleFonts.notoSansKr(fontSize: 14, color: eInk),
                ),
              ),

              // 에러 메시지
              if (_errorMessage != null)
                Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF44336).withOpacity(0.1),
                      border: Border.all(color: const Color(0xFFF44336)),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      _errorMessage!,
                      style: const TextStyle(
                        color: Color(0xFFF44336),
                        fontSize: 13,
                      ),
                    ),
                  ),
                ),
              const SizedBox(height: 40),

              // 회원가입 버튼
              SizedBox(
                width: double.infinity,
                height: 56,
                child: ElevatedButton(
                  onPressed: _isLoading ? null : _signup,
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
                          '회원가입 완료',
                          style: GoogleFonts.notoSansKr(
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                            color: Colors.white,
                          ),
                        ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSignupCompleteScreen() {
    final code = _connectionCode;
    return Scaffold(
      backgroundColor: eBg,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 26, vertical: 32),
            child: Column(
              children: [
                const Icon(
                  Icons.check_circle_rounded,
                  color: eAccent,
                  size: 72,
                ),
                const SizedBox(height: 24),
                Text(
                  '회원가입이 완료되었습니다',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.notoSansKr(
                    fontSize: 25,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                  ),
                ),
                const SizedBox(height: 32),
                Text(
                  code != null
                      ? '보호자에게 아래 연결코드를 알려주세요.'
                      : '연결코드를 받지 못했어요. 다음 화면에서 다시 볼 수 있어요.',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.notoSansKr(fontSize: 16, color: eInkSoft),
                ),
                if (code == null && _codeError != null) ...[
                  const SizedBox(height: 8),
                  Text(
                    _codeError!,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 14, color: Color(0xFFF44336)),
                  ),
                ],
                if (code != null) ...[
                  const SizedBox(height: 16),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.symmetric(vertical: 22),
                    decoration: BoxDecoration(
                      color: eCard,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: eLine, width: 1.5),
                    ),
                    child: SelectableText(
                      code,
                      textAlign: TextAlign.center,
                      style: GoogleFonts.notoSansKr(
                        fontSize: 32,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 4,
                        color: eAccent,
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    '이 코드는 바뀌지 않아요. 메뉴의 "내 연결코드"에서 언제든 다시 볼 수 있어요.\n'
                    '보호자가 이 코드를 입력해 연결하면 안부 전화가 시작돼요.',
                    textAlign: TextAlign.center,
                    style: GoogleFonts.notoSansKr(
                      fontSize: 14,
                      height: 1.6,
                      color: eInkSoft,
                    ),
                  ),
                ],
                const SizedBox(height: 36),
                SizedBox(
                  width: double.infinity,
                  height: 56,
                  child: ElevatedButton(
                    onPressed: () {
                      // 열쇠는 이미 폰에 있다. 어르신 문이 서버 상태(연결 대기·활성)를 보고 갈 곳을 정한다.
                      Navigator.pushAndRemoveUntil(
                        context,
                        MaterialPageRoute(
                          builder: (context) => ElderlyGate(linkCode: code),
                        ),
                        (route) => false,
                      );
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: eAccent,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                    child: Text(
                      '확인',
                      style: GoogleFonts.notoSansKr(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: Colors.white,
                      ),
                    ),
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
