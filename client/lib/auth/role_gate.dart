import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../theme/app_theme.dart';
import 'role.dart';

/// 첫 실행에서 한 번만 보이는 화면.
///
/// 두 선택지의 크기를 일부러 다르게 뒀다. 어르신 쪽이 큰 것은 장식이 아니라
/// 정보다 — 저시력·손떨림 사용자에게 필요한 터치 영역이 실제로 더 크다.
class RoleGate extends StatelessWidget {
  const RoleGate({super.key, required this.onSelected});

  final ValueChanged<AppRole> onSelected;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(28, 40, 28, 28),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                '늘봄',
                style: GoogleFonts.notoSerifKr(
                  fontSize: 17,
                  fontWeight: FontWeight.w600,
                  color: eBrass,
                  letterSpacing: 2,
                ),
              ),
              const SizedBox(height: 36),
              Text(
                '누가 쓰시나요?',
                style: GoogleFonts.notoSerifKr(
                  fontSize: 34,
                  height: 1.3,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 32),
              _RoleChoice(
                title: '어르신',
                description: 'AI 친구와 통화하고\n비상 연락을 씁니다',
                height: 184,
                titleSize: 32,
                filled: true,
                onTap: () => onSelected(AppRole.elder),
              ),
              const SizedBox(height: 16),
              _RoleChoice(
                title: '가족·보호자',
                description: '어르신 안부와 통화 기록을 봅니다',
                height: 124,
                titleSize: 22,
                filled: false,
                onTap: () => onSelected(AppRole.guardian),
              ),
              const Spacer(),
              Text(
                '나중에 설정에서 바꿀 수 있어요.',
                style: TextStyle(fontSize: 14, color: eInkSoft),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _RoleChoice extends StatelessWidget {
  const _RoleChoice({
    required this.title,
    required this.description,
    required this.height,
    required this.titleSize,
    required this.filled,
    required this.onTap,
  });

  final String title;
  final String description;
  final double height;
  final double titleSize;
  final bool filled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final foreground = filled ? Colors.white : eInk;
    return Semantics(
      button: true,
      label: '$title. $description',
      child: Material(
        color: filled ? eAccent : eCard,
        borderRadius: BorderRadius.circular(20),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(20),
          child: Ink(
            height: height,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(20),
              border: filled ? null : Border.all(color: eLine, width: 1.5),
            ),
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: GoogleFonts.notoSerifKr(
                    fontSize: titleSize,
                    fontWeight: FontWeight.w700,
                    color: foreground,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  description,
                  style: TextStyle(
                    fontSize: filled ? 17 : 15,
                    height: 1.5,
                    color: filled ? Colors.white.withValues(alpha: 0.92) : eInkSoft,
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
