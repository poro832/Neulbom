import 'dart:async';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../services/nulbom_api.dart';

const Color _ink = Color(0xFF0E2548);
const Color _inkSoft = Color(0xFF3C5C8C);
const Color _accent = Color(0xFF1A6BFF);
const Color _card = Color(0xFFFFFFFF);

/// 어르신이 "통화하기"를 눌렀을 때. 화면을 바꾸지 않고 팝업으로 알린다.
///
/// 앱은 통화를 하지 않는다 — 서버에 전화를 걸어 달라고 요청하고, 어르신 전화기가 울리기를 기다릴 뿐이다.
/// 팝업은 [autoClose] 뒤에 저절로 닫힌다(전화가 올 시간이 지났으니 더 붙잡아 둘 이유가 없다).
Future<void> showCallRequestDialog(
  BuildContext context, {
  Duration autoClose = const Duration(minutes: 1),
}) {
  return showDialog<void>(
    context: context,
    builder: (_) => CallRequestDialog(autoClose: autoClose),
  );
}

class CallRequestDialog extends StatefulWidget {
  const CallRequestDialog({super.key, this.autoClose = const Duration(minutes: 1)});

  final Duration autoClose;

  @override
  State<CallRequestDialog> createState() => _CallRequestDialogState();
}

enum _Phase { requesting, requested, failed }

class _CallRequestDialogState extends State<CallRequestDialog> {
  _Phase _phase = _Phase.requesting;
  String? _failure;
  Timer? _closer;

  @override
  void initState() {
    super.initState();
    _closer = Timer(widget.autoClose, () {
      if (mounted) Navigator.of(context).maybePop();
    });
    _request();
  }

  @override
  void dispose() {
    _closer?.cancel();
    super.dispose();
  }

  Future<void> _request() async {
    try {
      await NulbomApi.requestMyCall();
      // 이미 전화가 오는 중(409)도 성공으로 다룬다 — 어르신 입장에서는 똑같이 "곧 전화가 간다"이다.
      if (mounted) setState(() => _phase = _Phase.requested);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _failure = e.message;
          _phase = _Phase.failed;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _phase = _Phase.failed);
    }
  }

  String get _message {
    switch (_phase) {
      case _Phase.requesting:
        return '전화를 요청하고 있어요';
      case _Phase.requested:
        return '전화가 곧 가요.\n전화가 오면 받아주세요.';
      case _Phase.failed:
        return _failure ?? '전화를 걸지 못했어요.\n잠시 뒤에 다시 눌러 주세요.';
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: _card,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      content: Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              _phase == _Phase.failed ? Icons.error_outline_rounded : Icons.phone_in_talk_rounded,
              size: 48,
              color: _phase == _Phase.failed ? const Color(0xFFD92D20) : _accent,
            ),
            const SizedBox(height: 16),
            Text(
              _message,
              textAlign: TextAlign.center,
              style: GoogleFonts.notoSansKr(
                fontSize: 22,
                fontWeight: FontWeight.w700,
                color: _ink,
                height: 1.5,
              ),
            ),
            if (_phase == _Phase.requested) ...[
              const SizedBox(height: 8),
              Text(
                '이 창은 1분 뒤에 저절로 닫혀요.',
                textAlign: TextAlign.center,
                style: GoogleFonts.notoSansKr(fontSize: 14, color: _inkSoft),
              ),
            ],
          ],
        ),
      ),
      actionsAlignment: MainAxisAlignment.center,
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).maybePop(),
          child: Text(
            '확인',
            style: GoogleFonts.notoSansKr(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: _accent,
            ),
          ),
        ),
      ],
    );
  }
}
