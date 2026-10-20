import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';

import '../models/nulbom_models.dart' show ElderSummary;
import '../services/nulbom_api.dart';

const Color _ink = Color(0xFF0E2548);
const Color _inkSoft = Color(0xFF3C5C8C);
const Color _accent = Color(0xFF1A6BFF);
const Color _card = Color(0xFFFFFFFF);
const Color _danger = Color(0xFFD92D20);

/// 보호자가 어르신의 전화번호를 고친다(어르신이 새 폰을 쓸 때).
///
/// 번호가 바뀌면 서버가 옛 폰의 열쇠를 모두 지운다. 그래서 이어서 새 연결 코드를 만들어 보여 준다 —
/// 어르신은 새 폰의 로그인 화면에 새 번호와 이 코드를 넣는다. 고쳤으면 true를 돌려준다.
Future<bool> showElderEditDialog(BuildContext context, ElderSummary elder) async {
  final changed = await showDialog<bool>(
    context: context,
    barrierDismissible: false,
    builder: (_) => ElderEditDialog(elder: elder),
  );
  return changed == true;
}

class ElderEditDialog extends StatefulWidget {
  const ElderEditDialog({super.key, required this.elder});

  final ElderSummary elder;

  @override
  State<ElderEditDialog> createState() => _ElderEditDialogState();
}

class _ElderEditDialogState extends State<ElderEditDialog> {
  static const String _offline = '서버에 연결하지 못했어요. 잠시 뒤에 다시 해 주세요.';

  final TextEditingController _phone = TextEditingController();
  bool _loading = true;
  bool _saving = false;
  String? _error;
  String? _original;
  bool _changed = false;
  String? _code;
  String? _codeError;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _phone.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final phone = await NulbomApi.elderPhone(widget.elder.elderId);
      if (!mounted) return;
      setState(() {
        _original = phone;
        _phone.text = phone;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = error is ApiException ? error.message : _offline;
      });
    }
  }

  Future<void> _save() async {
    final value = _phone.text.trim();
    if (!RegExp(r'^[0-9+\- ]{9,20}$').hasMatch(value)) {
      setState(() => _error = '전화번호를 확인해 주세요.');
      return;
    }
    if (value == _original) {
      Navigator.pop(context, false);
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await NulbomApi.changeElderPhone(widget.elder.elderId, value);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = error is ApiException ? error.message : _offline;
      });
      return;
    }
    // 번호는 바뀌었다. 새 폰이 들어올 코드를 이어서 만든다 — 실패해도 번호는 이미 바뀐 상태다.
    String? code;
    String? codeError;
    try {
      code = (await NulbomApi.issuePairingCode(widget.elder.elderId)).code;
    } catch (error) {
      codeError = error is ApiException ? error.message : _offline;
    }
    if (!mounted) return;
    setState(() {
      _saving = false;
      _changed = true;
      _code = code;
      _codeError = codeError;
    });
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: !_saving,
      child: AlertDialog(
        backgroundColor: _card,
        title: Text(
          _changed ? '전화번호를 바꿨어요' : '${widget.elder.name} 어르신 정보 수정',
          style: GoogleFonts.notoSansKr(fontSize: 18, fontWeight: FontWeight.w700, color: _ink),
        ),
        content: _changed ? _doneBody() : _editBody(),
        actions: _changed
            ? [_button('확인', () => Navigator.pop(context, true))]
            : [
                _button('취소', _saving ? null : () => Navigator.pop(context, false), muted: true),
                _button('저장', _loading || _saving ? null : _save),
              ],
      ),
    );
  }

  Widget _editBody() {
    if (_loading) {
      return const SizedBox(height: 56, child: Center(child: CircularProgressIndicator()));
    }
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '어르신이 새 폰을 쓰면 새 번호로 고쳐 주세요. 옛 폰은 더 이상 어르신 기록을 볼 수 없게 돼요.',
          style: GoogleFonts.notoSansKr(fontSize: 14, height: 1.5, color: _inkSoft),
        ),
        const SizedBox(height: 14),
        TextField(
          key: const Key('elder-phone'),
          controller: _phone,
          keyboardType: TextInputType.phone,
          inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9+\- ]'))],
          decoration: const InputDecoration(labelText: '어르신 전화번호'),
        ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Text(_error!, style: const TextStyle(fontSize: 14, color: _danger)),
          ),
      ],
    );
  }

  Widget _doneBody() {
    final code = _code;
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (code != null) ...[
          Center(
            child: SelectableText(
              code,
              textAlign: TextAlign.center,
              style: GoogleFonts.notoSansKr(
                fontSize: 36,
                fontWeight: FontWeight.w800,
                letterSpacing: 6,
                color: _accent,
              ),
            ),
          ),
          const SizedBox(height: 12),
          Text(
            '새 폰의 로그인 화면에 새 번호와 이 코드를 입력하면 돼요. 24시간 안에 한 번만 쓸 수 있어요.',
            style: GoogleFonts.notoSansKr(fontSize: 14, height: 1.5, color: _inkSoft),
          ),
        ] else
          Text(
            '번호는 바뀌었어요. ${_codeError ?? '연결 코드를 만들지 못했어요.'}',
            style: const TextStyle(fontSize: 14, color: _danger),
          ),
      ],
    );
  }

  Widget _button(String label, VoidCallback? onPressed, {bool muted = false}) {
    return TextButton(
      onPressed: onPressed,
      child: Text(
        label,
        style: GoogleFonts.notoSansKr(
          fontWeight: FontWeight.w600,
          color: muted ? _inkSoft : _accent,
        ),
      ),
    );
  }
}
