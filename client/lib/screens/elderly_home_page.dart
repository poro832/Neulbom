import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../services/auth_service.dart';
import 'elderly_login_screen.dart';
import 'emergency_screen.dart';
import 'history_screen.dart';
import 'main_screen.dart';

const Color eBg = Color(0xFFFBF6ED);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);

class ElderlyHomePage extends StatefulWidget {
  const ElderlyHomePage({super.key});

  @override
  State<ElderlyHomePage> createState() => _ElderlyHomePageState();
}

class _ElderlyHomePageState extends State<ElderlyHomePage> {
  int _tabIndex = 0;

  void _logout() async {
    await AuthService.logout();
    if (!mounted) return;
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(builder: (context) => const ElderlyLoginScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: eBg,
      appBar: _tabIndex != 0
          ? null
          : AppBar(
        backgroundColor: eBg,
        elevation: 0,
        actions: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Center(
              child: PopupMenuButton<String>(
                onSelected: (value) {
                  if (value == 'logout') {
                    showDialog(
                      context: context,
                      builder: (context) => AlertDialog(
                        title: Text(
                          '로그아웃',
                          style: GoogleFonts.notoSansKr(
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        content: const Text('로그아웃하시겠습니까?'),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.pop(context),
                            child: const Text('취소'),
                          ),
                          TextButton(
                            onPressed: () {
                              Navigator.pop(context);
                              _logout();
                            },
                            child: const Text('로그아웃'),
                          ),
                        ],
                      ),
                    );
                  }
                },
                itemBuilder: (context) => [
                  const PopupMenuItem(
                    value: 'logout',
                    child: Text('로그아웃'),
                  ),
                ],
                child: Icon(
                  Icons.more_vert_rounded,
                  color: eInk,
                ),
              ),
            ),
          ),
        ],
      ),
      body: IndexedStack(
        index: _tabIndex,
        children: const [
          MainScreen(),
          HistoryScreen(),
          EmergencyScreen(),
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
    );
  }
}
