import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../main.dart' show eAccent, eBg, eCard, eInk, eInkSoft, eLine;
import '../services/email_proof.dart';
import '../services/nulbom_api.dart';

const Color _danger = Color(0xFFF44336);
const String _notYet = '아직 인증되지 않았어요. 메일의 링크를 누른 뒤 다시 눌러 주세요.';
const String _failed = '인증을 확인하지 못했어요. 잠시 뒤에 다시 해 주세요.';
const String _sendFailed = '인증 메일을 보내지 못했어요. 잠시 뒤에 다시 해 주세요.';

/// 보호자가 가입한 이메일이 본인 것임을 Firebase 인증 메일로 확인한다.
///
/// 비밀번호를 받으면(가입 직후) 바로 인증 메일을 보낸다. 비밀번호가 없고 이 폰에 Firebase
/// 세션도 없으면(계정 화면에서 열었을 때 등) 비밀번호를 다시 입력받아 보낸다. "인증했어요"를
/// 누르면 Firebase가 준 증명서(ID 토큰)를 서버에 보내고, 서버가 기록하면 true로 닫힌다.
/// "나중에 하기"·뒤로 가기는 false(또는 null)다. 비밀번호는 저장하거나 기록하지 않는다.
/// 오류는 SnackBar가 아니라 화면 안 문장으로 보여 준다.
class EmailVerificationScreen extends StatefulWidget {
  const EmailVerificationScreen({
    super.key,
    required this.email,
    this.password,
    this.proof,
    this.verify,
  });

  final String email;
  final String? password;

  /// 없으면 [FirebaseEmailProof]. 테스트에서 가짜로 바꾼다.
  final EmailProof? proof;

  /// 없으면 [NulbomApi.verifyEmail]. 서버가 인증을 기록했으면 true.
  final Future<bool> Function(String idToken)? verify;

  @override
  State<EmailVerificationScreen> createState() => _EmailVerificationScreenState();
}

class _EmailVerificationScreenState extends State<EmailVerificationScreen> {
  late final EmailProof _proof = widget.proof ?? FirebaseEmailProof();
  late final Future<bool> Function(String idToken) _verify =
      widget.verify ?? NulbomApi.verifyEmail;
  final TextEditingController _passwordController = TextEditingController();

  bool _busy = false;
  bool _needsPassword = false;
  String? _message;
  bool _messageIsError = false;

  @override
  void initState() {
    super.initState();
    final password = widget.password;
    if (password != null && password.isNotEmpty) {
      _busy = true;
      _send(password);
    } else {
      _needsPassword = !_hasSession();
    }
  }

  @override
  void dispose() {
    _passwordController.dispose();
    super.dispose();
  }

  /// Firebase가 초기화되지 않은 폰에서도 화면은 떠야 한다 — 그때는 세션이 없는 것으로 본다.
  bool _hasSession() {
    try {
      return _proof.hasSession;
    } catch (_) {
      return false;
    }
  }

  void _show(String message, {required bool error}) {
    setState(() {
      _busy = false;
      _message = message;
      _messageIsError = error;
    });
  }

  Future<void> _send(String password) async {
    try {
      await _proof.sendVerification(email: widget.email, password: password);
      if (!mounted) return;
      setState(() {
        _busy = false;
        _needsPassword = false;
        _message = null;
      });
      _passwordController.clear();
    } catch (error) {
      if (!mounted) return;
      _needsPassword = !_hasSession(); // 로그인하지 못했으면 비밀번호를 다시 받아 보낸다
      _show(error is EmailProofException ? error.message : _sendFailed, error: true);
    }
  }

  Future<void> _sendWithTypedPassword() async {
    if (_busy) return;
    final password = _passwordController.text;
    if (password.isEmpty) {
      _show('비밀번호를 입력해 주세요.', error: true);
      return;
    }
    setState(() {
      _busy = true;
      _message = null;
    });
    await _send(password);
  }

  Future<void> _resend() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      await _proof.resend();
      if (!mounted) return;
      _show('인증 메일을 다시 보냈어요.', error: false);
    } catch (error) {
      if (!mounted) return;
      _needsPassword = !_hasSession();
      _show(error is EmailProofException ? error.message : _sendFailed, error: true);
    }
  }

  Future<void> _confirm() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      final token = await _proof.verifiedIdToken();
      if (!mounted) return;
      if (token == null) {
        _show(_notYet, error: false);
        return;
      }
      final recorded = await _verify(token);
      if (!mounted) return;
      if (recorded) {
        Navigator.pop(context, true);
        return;
      }
      _show(_failed, error: true);
    } on ApiException catch (e) {
      if (!mounted) return;
      _show(e.message, error: true);
    } on EmailProofException catch (e) {
      if (!mounted) return;
      _show(e.message, error: true);
    } catch (_) {
      if (!mounted) return;
      _show(_failed, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded, color: eInk),
          onPressed: () => Navigator.pop(context, false),
        ),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 26, vertical: 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.mark_email_unread_rounded, color: eAccent, size: 56),
              const SizedBox(height: 20),
              Text(
                '이메일 인증',
                style: GoogleFonts.notoSansKr(
                  fontSize: 28,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),
              Text(
                _needsPassword
                    ? '${widget.email}로 인증 메일을 보낼게요. 가입할 때 정한 비밀번호를 입력해 주세요.'
                    : '${widget.email}로 인증 메일을 보냈어요. 메일의 링크를 누른 뒤 아래 버튼을 눌러 주세요. 메일이 안 보이면 스팸함도 확인해 주세요.',
                style: GoogleFonts.notoSansKr(
                  fontSize: 16,
                  height: 1.6,
                  color: eInkSoft,
                ),
              ),
              const SizedBox(height: 24),
              if (_needsPassword) ...[
                TextField(
                  controller: _passwordController,
                  enabled: !_busy,
                  obscureText: true,
                  decoration: InputDecoration(
                    hintText: '비밀번호',
                    hintStyle: const TextStyle(color: eInkSoft),
                    filled: true,
                    fillColor: eCard,
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
                const SizedBox(height: 16),
              ],
              if (_message != null) ...[
                _buildMessage(_message!),
                const SizedBox(height: 16),
              ],
              _buildPrimaryButton(
                label: _needsPassword ? '인증 메일 보내기' : '인증했어요',
                onPressed: _needsPassword ? _sendWithTypedPassword : _confirm,
              ),
              if (!_needsPassword) ...[
                const SizedBox(height: 8),
                Center(
                  child: TextButton(
                    onPressed: _busy ? null : _resend,
                    child: Text(
                      '다시 보내기',
                      style: GoogleFonts.notoSansKr(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        color: _busy ? eInkSoft : eAccent,
                      ),
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 24),
              Center(
                child: TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: Text(
                    '나중에 하기',
                    style: GoogleFonts.notoSansKr(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: eInkSoft,
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

  Widget _buildMessage(String message) {
    final color = _messageIsError ? _danger : eAccent;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        border: Border.all(color: color.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        message,
        style: GoogleFonts.notoSansKr(fontSize: 14, height: 1.5, color: _messageIsError ? _danger : eInk),
      ),
    );
  }

  Widget _buildPrimaryButton({required String label, required VoidCallback onPressed}) {
    return SizedBox(
      width: double.infinity,
      height: 56,
      child: ElevatedButton(
        onPressed: _busy ? null : onPressed,
        style: ElevatedButton.styleFrom(
          backgroundColor: eAccent,
          disabledBackgroundColor: eInkSoft.withValues(alpha: 0.3),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
        child: Text(
          label,
          style: GoogleFonts.notoSansKr(
            fontSize: 16,
            fontWeight: FontWeight.w700,
            color: Colors.white,
          ),
        ),
      ),
    );
  }
}
