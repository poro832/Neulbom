import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../services/auth_service.dart';
import '../services/nulbom_api.dart';
import 'link_code_renew.dart';
import 'elderly_login_screen.dart';
import 'emergency_screen.dart';
import 'history_screen.dart';
import 'main_screen.dart';

const Color eBg = Color(0xFFEFF6FF);
const Color eCard = Color(0xFFFFFFFF);
const Color eInk = Color(0xFF0E2548);
const Color eInkSoft = Color(0xFF3C5C8C);
const Color eLine = Color(0xFFD6E4FF);
const Color eAccent = Color(0xFF1A6BFF);

class ElderlyHomePage extends StatefulWidget {
  const ElderlyHomePage({super.key});

  @override
  State<ElderlyHomePage> createState() => _ElderlyHomePageState();
}

class _ElderlyHomePageState extends State<ElderlyHomePage> {
  int _tabIndex = 0;

  Future<void> _logout() async {
    await AuthService.logout();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (context) => const ElderlyLoginScreen()),
      (route) => false,
    );
  }

  Future<void> _confirmLogout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: eCard,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
        ),
        title: Text(
          '로그아웃',
          style: GoogleFonts.notoSansKr(
            fontSize: 28,
            fontWeight: FontWeight.w800,
            color: eInk,
          ),
        ),
        content: Text(
          '지금 로그아웃할까요?',
          style: GoogleFonts.notoSansKr(
            fontSize: 20,
            fontWeight: FontWeight.w700,
            color: eInk,
            height: 1.5,
          ),
        ),
        actionsPadding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
        actions: [
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: () => Navigator.pop(context, false),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: eInk,
                    side: const BorderSide(color: eLine, width: 1.5),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                  child: Text(
                    '취소',
                    style: GoogleFonts.notoSansKr(
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: ElevatedButton(
                  onPressed: () => Navigator.pop(context, true),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: eAccent,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                  child: Text(
                    '로그아웃',
                    style: GoogleFonts.notoSansKr(
                      fontSize: 18,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );

    if (confirmed == true) {
      await _logout();
    }
  }

  Future<bool> _askTwice(String title, String message, String confirmLabel) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: eCard,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: Text(
          title,
          style: GoogleFonts.notoSansKr(fontSize: 26, fontWeight: FontWeight.w800, color: eInk),
        ),
        content: Text(
          message,
          style: GoogleFonts.notoSansKr(
              fontSize: 19, fontWeight: FontWeight.w700, color: eInk, height: 1.5),
        ),
        actionsPadding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
        actions: [
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: () => Navigator.pop(context, false),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: eInk,
                    side: const BorderSide(color: eLine, width: 1.5),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                  child: Text('취소',
                      style: GoogleFonts.notoSansKr(fontSize: 18, fontWeight: FontWeight.w700)),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: ElevatedButton(
                  onPressed: () => Navigator.pop(context, true),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFFD92D20),
                    foregroundColor: Colors.white,
                    elevation: 0,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                  child: Text(confirmLabel,
                      style: GoogleFonts.notoSansKr(fontSize: 18, fontWeight: FontWeight.w800)),
                ),
              ),
            ],
          ),
        ],
      ),
    );
    return result == true;
  }

  /// 어르신 탈퇴. 되돌릴 수 없어서 두 번 묻는다.
  Future<void> _confirmDeleteAccount() async {
    if (!await _askTwice(
      '탈퇴하기',
      '탈퇴하면 이 폰의 정보와 지금까지의 통화 기록이 모두 지워지고, 안부 전화도 멈춰요.',
      '계속',
    )) {
      return;
    }
    if (!mounted) return;
    if (!await _askTwice('정말 탈퇴할까요?', '지운 기록은 다시 볼 수 없어요.', '탈퇴하기')) return;
    if (!mounted) return;
    // 지우는 동안은 뒤로가기로 빠져나가지 못하게 막는다 — 서버에서 지워졌는데 화면만 남는 일을 막는다.
    final navigator = Navigator.of(context, rootNavigator: true);
    final messenger = ScaffoldMessenger.of(context);
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => const PopScope(
        canPop: false,
        child: Center(child: CircularProgressIndicator()),
      ),
    );
    try {
      await AuthService.deleteElderAccount();
    } on ApiException catch (e) {
      navigator.pop(); // 진행 표시 닫기
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
      return;
    } catch (_) {
      navigator.pop();
      messenger.showSnackBar(
          const SnackBar(content: Text('서버에 연결하지 못했어요. 잠시 뒤에 다시 해 주세요.')));
      return;
    }
    // 화면이 닫혔어도(mounted 아님) 가져다 둔 navigator로 처음 화면으로 돌아간다.
    navigator.pushAndRemoveUntil(
      MaterialPageRoute(builder: (context) => const ElderlyLoginScreen()),
      (route) => false,
    );
    messenger.showSnackBar(const SnackBar(content: Text('탈퇴했어요.')));
  }

  Widget _buildMenuRow({
    required IconData icon,
    required String label,
  }) {
    return Row(
      children: [
        Container(
          width: 36,
          height: 36,
          decoration: BoxDecoration(
            color: const Color(0xFFE6F0FF),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Icon(icon, color: eAccent, size: 20),
        ),
        const SizedBox(width: 12),
        Text(
          label,
          style: GoogleFonts.notoSansKr(
            fontSize: 17,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
      ],
    );
  }

  /// 내 고정 연결 코드를 보여 준다. 바뀌지 않고, 연결된 뒤에도 언제든 다시 볼 수 있다.
  /// 코드가 새어 나갔을 때만 "새 코드 만들기"로 바꾼다(확인을 받는다).
  Future<void> _showConnectionCode() async {
    // 대화상자가 그려지기 전에 거절이 와도 처리되지 않은 오류가 되지 않게 한다.
    var loading = NulbomApi.myLinkCode()..ignore();

    await showDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setLocal) => AlertDialog(
          backgroundColor: eCard,
          title: Text(
            '내 연결코드',
            style: GoogleFonts.notoSansKr(
              fontSize: 24,
              fontWeight: FontWeight.w800,
              color: eInk,
            ),
          ),
          content: FutureBuilder<String>(
            future: loading,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const SizedBox(
                  height: 80,
                  child: Center(child: CircularProgressIndicator()),
                );
              }
              if (snapshot.hasError) {
                final error = snapshot.error;
                return Text(
                  error is ApiException
                      ? error.message
                      : '연결코드를 받지 못했어요. 잠시 뒤에 다시 해 주세요.',
                  style: GoogleFonts.notoSansKr(
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                    height: 1.5,
                  ),
                );
              }
              return Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    '보호자에게 아래 코드를 알려주세요.',
                    style: GoogleFonts.notoSansKr(fontSize: 16, color: eInkSoft),
                  ),
                  const SizedBox(height: 20),
                  SelectableText(
                    snapshot.data!,
                    style: GoogleFonts.notoSansKr(
                      fontSize: 30,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 3,
                      color: eAccent,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    '이 코드는 바뀌지 않아요. 언제든 여기서 다시 볼 수 있어요.',
                    textAlign: TextAlign.center,
                    style: GoogleFonts.notoSansKr(fontSize: 14, color: eInkSoft),
                  ),
                ],
              );
            },
          ),
          actions: [
            TextButton(
              key: const Key('renew-link-code'),
              onPressed: () async {
                try {
                  final code = await renewLinkCodeWithConfirm(dialogContext);
                  if (code == null || !dialogContext.mounted) return;
                  setLocal(() {
                    loading = Future.value(code);
                  });
                } catch (error) {
                  if (!dialogContext.mounted) return;
                  setLocal(() {
                    loading = Future.error(error)..ignore();
                  });
                }
              },
              child: Text(
                '새 코드 만들기',
                style: GoogleFonts.notoSansKr(fontSize: 15, color: eInkSoft),
              ),
            ),
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: Text(
                '닫기',
                style: GoogleFonts.notoSansKr(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: eAccent,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      child: Scaffold(
        backgroundColor: eBg,
        appBar: _tabIndex != 0
            ? null
            : AppBar(
                backgroundColor: eBg,
                elevation: 0,
                automaticallyImplyLeading: false,
                actions: [
                  Padding(
                    padding: const EdgeInsets.only(right: 16),
                    child: Center(
                      child: PopupMenuButton<String>(
                        offset: const Offset(0, 48),
                        color: eCard,
                        elevation: 6,
                        shadowColor: eInk.withValues(alpha: 0.12),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(16),
                          side: const BorderSide(color: eLine),
                        ),
                        onSelected: (value) {
                          if (value == 'connection_code') {
                            _showConnectionCode();
                          } else if (value == 'logout') {
                            _confirmLogout();
                          } else if (value == 'delete_account') {
                            _confirmDeleteAccount();
                          }
                        },
                        itemBuilder: (context) => [
                          PopupMenuItem(
                            value: 'connection_code',
                            child: _buildMenuRow(
                              icon: Icons.qr_code_2_rounded,
                              label: '내 연결코드',
                            ),
                          ),
                          const PopupMenuDivider(height: 1),
                          PopupMenuItem(
                            value: 'logout',
                            child: _buildMenuRow(
                              icon: Icons.logout_rounded,
                              label: '로그아웃',
                            ),
                          ),
                          const PopupMenuDivider(height: 1),
                          PopupMenuItem(
                            value: 'delete_account',
                            child: _buildMenuRow(
                              icon: Icons.person_remove_alt_1_rounded,
                              label: '탈퇴하기',
                            ),
                          ),
                        ],
                        child: Container(
                          width: 48,
                          height: 48,
                          decoration: BoxDecoration(
                            color: eCard,
                            shape: BoxShape.circle,
                            border: Border.all(color: eLine, width: 1.5),
                            boxShadow: [
                              BoxShadow(
                                color: eAccent.withValues(alpha: 0.08),
                                blurRadius: 8,
                                offset: const Offset(0, 2),
                              ),
                            ],
                          ),
                          child: const Icon(
                            Icons.more_horiz_rounded,
                            color: eAccent,
                            size: 26,
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
        body: IndexedStack(
          index: _tabIndex,
          children: [
            MainScreen(onOpenEmergency: () => setState(() => _tabIndex = 2)),
            const HistoryScreen(),
            const EmergencyScreen(),
          ],
        ),
        bottomNavigationBar: Container(
          decoration: const BoxDecoration(
            color: eCard,
            border: Border(top: BorderSide(color: eLine)),
          ),
          child: SafeArea(
            child: SizedBox(
              height: 72,
              child: BottomNavigationBar(
                currentIndex: _tabIndex,
                onTap: (index) => setState(() => _tabIndex = index),
                backgroundColor: eCard,
                elevation: 0,
                type: BottomNavigationBarType.fixed,
                selectedItemColor: eAccent,
                unselectedItemColor: eInkSoft,
                selectedLabelStyle: GoogleFonts.notoSansKr(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                ),
                unselectedLabelStyle: GoogleFonts.notoSansKr(
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                ),
                iconSize: 28,
                items: const [
                  BottomNavigationBarItem(
                    icon: Icon(Icons.home_rounded),
                    label: '홈',
                  ),
                  BottomNavigationBarItem(
                    icon: Icon(Icons.history_rounded),
                    label: '통화기록',
                  ),
                  BottomNavigationBarItem(
                    icon: Icon(Icons.warning_amber_rounded),
                    label: '비상연락',
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
