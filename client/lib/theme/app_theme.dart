import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// 안심케어 팔레트.
///
/// 이전에는 화면 6곳에 같은 상수가 중복 정의돼 있어서 색 하나 바꾸려면
/// 6군데를 고쳐야 했다. 여기 한 곳으로 모은다.
///
/// 어르신 화면은 대비를 높게, 글자를 크게 가져간다 — 저시력 대응.
const Color eBg = Color(0xFFFBF6ED);
const Color eBg2 = Color(0xFFF3E7D3);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);
const Color eAccentSoft = Color(0xFFFBE4D3);
const Color eBrass = Color(0xFFB78A4A);

/// 위험 등급 색 — 서버가 준 risk_level을 그대로 매핑한다.
/// 색을 앱에서 임의로 판단하지 않는다(설계 3.2).
const Color eRiskNormal = Color(0xFF5B8C5A);
const Color eRiskWatch = Color(0xFFD9A441);
const Color eRiskAlert = Color(0xFFC1553B);

Color riskColor(String riskLevel) => switch (riskLevel) {
      'alert' => eRiskAlert,
      'watch' => eRiskWatch,
      _ => eRiskNormal,
    };

String riskLabel(String riskLevel) => switch (riskLevel) {
      'alert' => '경보',
      'watch' => '주의',
      _ => '정상',
    };

ThemeData buildAppTheme(BuildContext context) {
  return ThemeData(
    useMaterial3: true,
    scaffoldBackgroundColor: eBg,
    colorScheme: ColorScheme.fromSeed(
      seedColor: eAccent,
      brightness: Brightness.light,
    ),
    textTheme: GoogleFonts.notoSansKrTextTheme(
      Theme.of(context).textTheme,
    ).copyWith(
      headlineSmall: GoogleFonts.notoSerifKr(
        fontSize: 24,
        fontWeight: FontWeight.w700,
        color: eInk,
      ),
      titleLarge: GoogleFonts.notoSerifKr(
        fontSize: 21,
        fontWeight: FontWeight.w700,
        color: eInk,
      ),
    ),
  );
}
