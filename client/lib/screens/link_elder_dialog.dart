import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';

import '../main.dart' show eAccent, eCard, eInk, eInkSoft, eLine;
import '../models/nulbom_models.dart';
import '../services/nulbom_api.dart';

const Color _danger = Color(0xFFF44336);
const String _offline = '서버에 연결하지 못했어요. 잠시 뒤에 다시 해 주세요.';

String _errorText(Object error) => error is ApiException ? error.message : _offline;

/// 보호자가 어르신의 8자리 연결 코드로 어르신을 연결한다.
///
/// 코드 입력 → 서버 미리보기(이름·가려진 번호) → 보호자 확인 → 연결. 이 확인이 승인이다 —
/// 연결하는 순간 서버가 안부 전화 동의를 기록하고 전화가 시작된다. 연결했으면 결과를, 그만뒀으면 null.
/// 서버 거절(401 코드 확인, 403 운영자 확인 전, 409, 429)은 그 문장을 대화상자 안에 보여 준다.
/// 코드가 틀려도 보호자는 로그아웃되지 않는다 — NulbomApi가 연결 코드 호출의 401을 따로 다룬다.
Future<LinkResult?> showLinkElderDialog(BuildContext context) async {
  final found = await showDialog<_Found>(
    context: context,
    builder: (_) => const _CodeDialog(),
  );
  if (found == null || !context.mounted) return null;
  return showDialog<LinkResult>(
    context: context,
    builder: (_) => _ConfirmDialog(code: found.code, elder: found.elder),
  );
}

class _Found {
  final String code;
  final ElderPreview elder;

  const _Found(this.code, this.elder);
}

class _CodeDialog extends StatefulWidget {
  const _CodeDialog();

  @override
  State<_CodeDialog> createState() => _CodeDialogState();
}

class _CodeDialogState extends State<_CodeDialog> {
  final TextEditingController _code = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _next() async {
    final code = _code.text.trim();
    if (!RegExp(r'^\d{8}$').hasMatch(code)) {
      setState(() => _error = '8자리 숫자 연결코드를 입력해주세요.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final elder = await NulbomApi.previewLink(code);
      if (!mounted) return;
      Navigator.pop(context, _Found(code, elder));
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = _errorText(error);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: eCard,
      title: Text(
        '어르신 추가',
        style: GoogleFonts.notoSansKr(
          fontSize: 18,
          fontWeight: FontWeight.w700,
          color: eInk,
        ),
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '어르신이 앱에서 가입하고 받은 연결 코드를 입력하세요.',
            style: GoogleFonts.notoSansKr(fontSize: 13, color: eInkSoft),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('link-code-field'),
            controller: _code,
            enabled: !_busy,
            keyboardType: TextInputType.number,
            maxLength: 8,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            decoration: InputDecoration(
              labelText: '어르신 연결코드',
              hintText: '8자리 숫자를 입력해주세요',
              hintStyle: const TextStyle(color: eInkSoft),
              counterText: '',
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
                borderSide: const BorderSide(color: eLine),
              ),
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 12,
                vertical: 10,
              ),
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text(_error!, style: const TextStyle(fontSize: 13, color: _danger)),
          ],
        ],
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.pop(context),
          child: Text(
            '취소',
            style: GoogleFonts.notoSansKr(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: eInkSoft,
            ),
          ),
        ),
        TextButton(
          onPressed: _busy ? null : _next,
          child: Text(
            '추가',
            style: GoogleFonts.notoSansKr(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: eAccent,
            ),
          ),
        ),
      ],
    );
  }
}

/// 미리보기로 받은 이름과 가려진 번호를 보여 주고, 보호자가 맞다고 해야만 연결한다.
class _ConfirmDialog extends StatefulWidget {
  const _ConfirmDialog({required this.code, required this.elder});

  final String code;
  final ElderPreview elder;

  @override
  State<_ConfirmDialog> createState() => _ConfirmDialogState();
}

class _ConfirmDialogState extends State<_ConfirmDialog> {
  bool _busy = false;
  String? _error;

  Future<void> _link() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await NulbomApi.linkElder(widget.code);
      if (!mounted) return;
      Navigator.pop(context, result);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = _errorText(error);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: eCard,
      title: Text(
        '어르신 확인',
        style: GoogleFonts.notoSansKr(
          fontSize: 18,
          fontWeight: FontWeight.w700,
          color: eInk,
        ),
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${widget.elder.name} 어르신(${widget.elder.phoneMasked})이 맞나요?',
            style: GoogleFonts.notoSansKr(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: eInk,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '연결하면 이 어르신께 안부 전화가 시작돼요.',
            style: GoogleFonts.notoSansKr(fontSize: 13, color: eInkSoft),
          ),
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text(_error!, style: const TextStyle(fontSize: 13, color: _danger)),
          ],
        ],
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.pop(context),
          child: Text(
            '취소',
            style: GoogleFonts.notoSansKr(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: eInkSoft,
            ),
          ),
        ),
        TextButton(
          key: const Key('link-confirm'),
          onPressed: _busy ? null : _link,
          child: Text(
            '연결하기',
            style: GoogleFonts.notoSansKr(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: eAccent,
            ),
          ),
        ),
      ],
    );
  }
}
