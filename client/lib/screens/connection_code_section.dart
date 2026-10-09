import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../main.dart' show eAccent, eInk, eInkSoft;
import '../models/nulbom_models.dart';
import '../services/nulbom_api.dart';

/// 보호자 개인 코드를 발급해 보여 준다. 어르신이 가입 화면에 이 코드를 입력하면 보호자 홈에
/// "승인 대기"로 나타나고, 보호자가 승인해야 안부 전화가 시작된다. 새로 발급하면 이전 코드는
/// 쓸 수 없다. 코드는 여러 어르신이 쓸 수 있다.
class ConnectionCodeSection extends StatefulWidget {
  const ConnectionCodeSection({super.key});

  @override
  State<ConnectionCodeSection> createState() => _ConnectionCodeSectionState();
}

class _ConnectionCodeSectionState extends State<ConnectionCodeSection> {
  InviteCode? _code;
  String? _error;
  bool _busy = false;

  Future<void> _issue() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final code = await NulbomApi.issueInvite();
      if (!mounted) return;
      setState(() => _code = code);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error is ApiException ? error.message : '코드를 만들지 못했어요. 잠시 뒤에 다시 해 주세요.';
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: eAccent.withOpacity(0.08),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: eAccent.withOpacity(0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '내 보호자 코드',
                  style: GoogleFonts.notoSansKr(
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                  ),
                ),
              ),
              TextButton(
                onPressed: _busy ? null : _issue,
                child: Text(
                  _code == null ? '코드 발급' : '새 코드 발급',
                  style: GoogleFonts.notoSansKr(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: eAccent,
                  ),
                ),
              ),
            ],
          ),
          if (_code != null) ...[
            const SizedBox(height: 6),
            SelectableText(
              _code!.code,
              style: GoogleFonts.notoSansKr(
                fontSize: 28,
                fontWeight: FontWeight.w800,
                letterSpacing: 4,
                color: eAccent,
              ),
            ),
          ],
          const SizedBox(height: 4),
          Text(
            '어르신이 가입 화면에 이 코드를 입력하면 보호자 홈에 승인 대기로 나타나요. '
            '새로 발급하면 이전 코드는 쓸 수 없어요.',
            style: GoogleFonts.notoSansKr(fontSize: 11, color: eInkSoft),
          ),
          if (_error != null) ...[
            const SizedBox(height: 6),
            Text(_error!, style: const TextStyle(fontSize: 12, color: Color(0xFFC0553F))),
          ],
        ],
      ),
    );
  }
}
