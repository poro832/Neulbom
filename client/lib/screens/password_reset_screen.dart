import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../main.dart' show eAccent, eBg, eCard, eInk, eInkSoft, eLine;
import '../services/email_proof.dart';
import '../services/nulbom_api.dart';

const Color _danger = Color(0xFFF44336);
const String _guide = '메일의 링크를 눌러 새 비밀번호를 정한 뒤, 같은 비밀번호를 아래에 입력해 주세요.';
const String _mismatch = '비밀번호가 동일하지 않습니다.';
const String _tooShort = '비밀번호는 8자 이상이어야 합니다.';
const String _sendFailed = '비밀번호 재설정 메일을 보내지 못했어요. 잠시 뒤에 다시 해 주세요.';
const String _changeFailed = '비밀번호를 바꾸지 못했어요. 잠시 뒤에 다시 해 주세요.';

/// 비밀번호를 바꾼 뒤 보여 주는 안내. 로그인 화면도 돌아와서 같은 문장을 보인다.
const String passwordResetDoneMessage = '비밀번호를 바꿨어요. 새 비밀번호로 로그인해 주세요.';

/// 서버(app_data.py MIN_PASSWORD)와 같은 최소 길이.
const int _minPassword = 8;

/// 비밀번호를 잊은 보호자가 Firebase 재설정 메일로 이메일 소유를 증명하고 서버 비밀번호를 바꾼다.
///
/// 1단계: 이메일로 Firebase 재설정 메일을 보낸다. 2단계: 보호자가 메일의 링크에서 새 비밀번호를 정한 뒤 같은
/// 비밀번호를 여기에 입력하면, 그 비밀번호로 Firebase에 로그인해 받은 증명서와 새 비밀번호를 서버에 보낸다.
/// 서버가 바꾸면 true로 닫힌다(그 보호자의 모든 폰은 로그아웃된다). 뒤로 가기는 false다.
/// 비밀번호는 저장하거나 기록하지 않는다. 오류는 SnackBar가 아니라 화면 안 문장으로 보여 준다.
class PasswordResetScreen extends StatefulWidget {
  const PasswordResetScreen({
    super.key,
    this.email = '',
    this.proof,
    this.reset,
  });

  static const Key emailField = Key('password-reset-email');
  static const Key newPasswordField = Key('password-reset-new');
  static const Key confirmPasswordField = Key('password-reset-confirm');

  /// 로그인 화면에서 입력한 이메일. 1단계 칸에 미리 채운다.
  final String email;

  /// 없으면 [FirebaseEmailProof]. 테스트에서 가짜로 바꾼다.
  final EmailProof? proof;

  /// 없으면 [NulbomApi.resetPassword]. 서버가 거절하면 [ApiException].
  final Future<void> Function(String idToken, String newPassword)? reset;

  @override
  State<PasswordResetScreen> createState() => _PasswordResetScreenState();
}

class _PasswordResetScreenState extends State<PasswordResetScreen> {
  late final EmailProof _proof = widget.proof ?? FirebaseEmailProof();
  late final Future<void> Function(String idToken, String newPassword) _reset =
      widget.reset ?? NulbomApi.resetPassword;
  late final TextEditingController _emailController = TextEditingController(text: widget.email.trim());
  final TextEditingController _newController = TextEditingController();
  final TextEditingController _confirmController = TextEditingController();

  bool _busy = false;
  bool _done = false;

  /// 재설정 메일을 보낸 이메일. null이면 1단계(메일 보내기)다.
  String? _sentTo;
  String? _message;
  bool _messageIsError = false;
  bool _obscureNew = true;
  bool _obscureConfirm = true;

  // 확인 칸에 무언가 입력했는데 위 칸과 다르면 입력하는 동안 바로 알린다.
  bool get _showsMismatch =>
      _confirmController.text.isNotEmpty && _confirmController.text != _newController.text;

  bool get _locked => _busy || _done;

  @override
  void dispose() {
    _emailController.dispose();
    _newController.dispose();
    _confirmController.dispose();
    super.dispose();
  }

  void _show(String message, {required bool error}) {
    setState(() {
      _busy = false;
      _message = message;
      _messageIsError = error;
    });
  }

  void _startBusy() {
    setState(() {
      _busy = true;
      _message = null;
    });
  }

  Future<void> _sendMail() async {
    if (_locked) return;
    final email = _emailController.text.trim();
    if (email.isEmpty) {
      _show('이메일을 입력해 주세요.', error: true);
      return;
    }
    _startBusy();
    try {
      await _proof.sendPasswordReset(email: email);
      if (!mounted) return;
      setState(() {
        _busy = false;
        _sentTo = email;
        _message = null;
      });
    } on EmailProofException catch (e) {
      if (!mounted) return;
      _show(e.message, error: true);
    } catch (_) {
      if (!mounted) return;
      _show(_sendFailed, error: true);
    }
  }

  Future<void> _resendMail() async {
    final email = _sentTo;
    if (_locked || email == null) return;
    _startBusy();
    try {
      await _proof.sendPasswordReset(email: email);
      if (!mounted) return;
      _show('재설정 메일을 다시 보냈어요.', error: false);
    } on EmailProofException catch (e) {
      if (!mounted) return;
      _show(e.message, error: true);
    } catch (_) {
      if (!mounted) return;
      _show(_sendFailed, error: true);
    }
  }

  Future<void> _change() async {
    final email = _sentTo;
    if (_locked || email == null) return;
    final password = _newController.text;
    if (password.isEmpty) {
      _show('새 비밀번호를 입력해 주세요.', error: true);
      return;
    }
    if (password.length < _minPassword) {
      _show(_tooShort, error: true);
      return;
    }
    if (password != _confirmController.text) {
      _show(_mismatch, error: true);
      return;
    }
    _startBusy();
    try {
      final idToken = await _proof.idTokenForReset(email: email, password: password);
      if (!mounted) return;
      await _reset(idToken, password);
      if (!mounted) return;
      setState(() {
        _busy = false;
        _done = true;
        _message = passwordResetDoneMessage;
        _messageIsError = false;
      });
      Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (!mounted) return;
      _show(e.message, error: true);
    } on EmailProofException catch (e) {
      if (!mounted) return;
      _show(e.message, error: true);
    } catch (_) {
      if (!mounted) return;
      _show(_changeFailed, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sentTo = _sentTo;
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
              const Icon(Icons.lock_reset_rounded, color: eAccent, size: 56),
              const SizedBox(height: 20),
              Text(
                '비밀번호 찾기',
                style: GoogleFonts.notoSansKr(
                  fontSize: 28,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),
              if (sentTo == null) ..._buildMailStep() else ..._buildPasswordStep(sentTo),
            ],
          ),
        ),
      ),
    );
  }

  List<Widget> _buildMailStep() {
    return [
      _buildBody('가입한 이메일을 입력하면 비밀번호를 다시 정할 수 있는 메일을 보내 드려요.'),
      const SizedBox(height: 24),
      _buildLabel('이메일'),
      const SizedBox(height: 8),
      _buildField(
        key: PasswordResetScreen.emailField,
        controller: _emailController,
        hint: '이메일을 입력해주세요',
        keyboardType: TextInputType.emailAddress,
      ),
      const SizedBox(height: 16),
      if (_message != null) ...[
        _buildMessage(_message!),
        const SizedBox(height: 16),
      ],
      _buildPrimaryButton(label: '재설정 메일 보내기', onPressed: _sendMail),
    ];
  }

  List<Widget> _buildPasswordStep(String sentTo) {
    return [
      _buildBody('$sentTo로 비밀번호 재설정 메일을 보냈어요. 메일이 안 보이면 스팸함도 확인해 주세요.'),
      const SizedBox(height: 8),
      _buildBody(_guide, color: eInk),
      const SizedBox(height: 24),
      _buildLabel('새 비밀번호'),
      const SizedBox(height: 8),
      _buildField(
        key: PasswordResetScreen.newPasswordField,
        controller: _newController,
        hint: '새 비밀번호',
        helper: '8자 이상, 메일의 링크에서 정한 비밀번호와 같게',
        obscure: _obscureNew,
        onToggleObscure: () => setState(() => _obscureNew = !_obscureNew),
      ),
      const SizedBox(height: 16),
      _buildLabel('새 비밀번호 확인'),
      const SizedBox(height: 8),
      _buildField(
        key: PasswordResetScreen.confirmPasswordField,
        controller: _confirmController,
        hint: '새 비밀번호 다시 입력',
        error: _showsMismatch ? _mismatch : null,
        obscure: _obscureConfirm,
        onToggleObscure: () => setState(() => _obscureConfirm = !_obscureConfirm),
      ),
      const SizedBox(height: 16),
      if (_message != null) ...[
        _buildMessage(_message!),
        const SizedBox(height: 16),
      ],
      _buildPrimaryButton(label: '비밀번호 바꾸기', onPressed: _change),
      const SizedBox(height: 8),
      Center(
        child: TextButton(
          onPressed: _locked ? null : _resendMail,
          child: Text(
            '메일 다시 보내기',
            style: GoogleFonts.notoSansKr(
              fontSize: 15,
              fontWeight: FontWeight.w600,
              color: _locked ? eInkSoft : eAccent,
            ),
          ),
        ),
      ),
    ];
  }

  Widget _buildBody(String text, {Color color = eInkSoft}) {
    return Text(
      text,
      style: GoogleFonts.notoSansKr(
        fontSize: 16,
        height: 1.6,
        color: color,
      ),
    );
  }

  Widget _buildLabel(String text) {
    return Text(
      text,
      style: GoogleFonts.notoSansKr(
        fontSize: 14,
        fontWeight: FontWeight.w600,
        color: eInk,
      ),
    );
  }

  Widget _buildField({
    required Key key,
    required TextEditingController controller,
    required String hint,
    String? helper,
    String? error,
    TextInputType? keyboardType,
    bool? obscure,
    VoidCallback? onToggleObscure,
  }) {
    return TextField(
      key: key,
      controller: controller,
      enabled: !_locked,
      keyboardType: keyboardType,
      obscureText: obscure ?? false,
      autocorrect: obscure == null,
      enableSuggestions: obscure == null,
      onChanged: (_) => setState(() {}),
      decoration: InputDecoration(
        hintText: hint,
        hintStyle: const TextStyle(color: eInkSoft),
        helperText: helper,
        helperStyle: const TextStyle(color: eInkSoft),
        errorText: error,
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
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: _danger),
        ),
        focusedErrorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: _danger, width: 2),
        ),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 14,
          vertical: 12,
        ),
        suffixIcon: onToggleObscure == null
            ? null
            : IconButton(
                icon: Icon(
                  (obscure ?? false) ? Icons.visibility_off_rounded : Icons.visibility_rounded,
                  color: eInkSoft,
                ),
                onPressed: onToggleObscure,
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
        onPressed: _locked ? null : onPressed,
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
