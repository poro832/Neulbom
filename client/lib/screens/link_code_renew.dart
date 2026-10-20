import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../services/nulbom_api.dart';

/// 어르신이 "새 코드 만들기"를 눌렀을 때. 먼저 한 번 확인을 받고, 서버에서 새 고정 코드를 받아 돌려준다.
///
/// 새 코드를 만들면 옛 코드는 바로 못 쓰게 된다 — 이미 연결된 보호자는 그대로지만, 옛 코드를 받아 둔 사람은
/// 연결할 수 없다. 취소하면 null이다. 서버가 거절하거나 연결이 안 되면 [ApiException] 등을 그대로 던진다.
Future<String?> renewLinkCodeWithConfirm(BuildContext context) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      backgroundColor: Colors.white,
      title: Text(
        '새 코드를 만들까요?',
        style: GoogleFonts.notoSansKr(
          fontSize: 22,
          fontWeight: FontWeight.w800,
          color: const Color(0xFF0E2548),
        ),
      ),
      content: Text(
        '지금 코드는 더 이상 쓸 수 없게 돼요.\n이미 연결된 보호자는 그대로예요.',
        style: GoogleFonts.notoSansKr(fontSize: 17, height: 1.5, color: const Color(0xFF3C5C8C)),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, false),
          child: Text('취소', style: GoogleFonts.notoSansKr(fontSize: 17, color: const Color(0xFF3C5C8C))),
        ),
        TextButton(
          onPressed: () => Navigator.pop(context, true),
          child: Text(
            '새로 만들기',
            style: GoogleFonts.notoSansKr(
              fontSize: 17,
              fontWeight: FontWeight.w700,
              color: const Color(0xFF1A6BFF),
            ),
          ),
        ),
      ],
    ),
  );
  if (ok != true) return null;
  return NulbomApi.renewLinkCode();
}
