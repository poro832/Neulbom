import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../main.dart' show eAccent, eInk, eInkSoft;
import '../models/nulbom_models.dart';
import 'link_elder_dialog.dart' show showLinkElderDialog;

/// 어르신이 없는 보호자 홈의 연결 영역. 어르신이 앱에서 먼저 가입하고 받은 8자리 연결 코드를
/// 보호자가 입력해 연결한다(코드 입력 → 이름·가려진 번호 확인 → 연결). 연결하면 [onLinked]를 부른다.
///
/// 예전에는 여기서 보호자 개인 코드(`NulbomApi.issueInvite`)를 발급해 어르신이 가입 화면에
/// 입력했다. 어르신 가입 화면이 더는 보호자 코드를 받지 않아 화면에서만 내렸다 — 서버 주소와
/// `NulbomApi.issueInvite`는 그대로 있다.
class ConnectionCodeSection extends StatelessWidget {
  const ConnectionCodeSection({super.key, this.onLinked});

  final ValueChanged<LinkResult>? onLinked;

  Future<void> _link(BuildContext context) async {
    final linked = await showLinkElderDialog(context);
    if (linked != null) onLinked?.call(linked);
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: eAccent.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: eAccent.withValues(alpha: 0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '어르신 연결',
            style: GoogleFonts.notoSansKr(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: eInk,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            '어르신이 앱에서 가입하고 받은 연결 코드를 입력하세요.',
            style: GoogleFonts.notoSansKr(fontSize: 13, color: eInkSoft),
          ),
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            height: 48,
            child: ElevatedButton(
              key: const Key('link-elder-button'),
              onPressed: () => _link(context),
              style: ElevatedButton.styleFrom(
                backgroundColor: eAccent,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
              child: Text(
                '연결하기',
                style: GoogleFonts.notoSansKr(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
