import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'calling_screen.dart';
import 'ai_chat_screen.dart';

// 색상
const Color eBg = Color(0xFFFBF6ED);
const Color eBg2 = Color(0xFFF3E7D3);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);
const Color eAccentSoft = Color(0xFFFBE4D3);
const Color eBrass = Color(0xFFB78A4A);

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  late String _currentTime;
  String _friendName = 'AI 친구';

  @override
  void initState() {
    super.initState();
    _updateTime();
    _loadFriendName();
  }

  Future<void> _loadFriendName() async {
    final prefs = await SharedPreferences.getInstance();
    final savedName = prefs.getString('ai_friend_name');

    if (savedName == null) {
      // 친구 이름이 설정되지 않았으면 다이얼로그 표시
      if (mounted) {
        _showSetFriendNameDialog();
      }
    } else {
      setState(() {
        _friendName = savedName;
      });
    }
  }

  void _showSetFriendNameDialog() {
    final nameController = TextEditingController();

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        backgroundColor: eCard,
        title: Text(
          'AI 친구 이름 설정',
          style: GoogleFonts.notoSerifKr(
            fontSize: 20,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '함께할 AI 친구의 이름을 지어주세요!\n(5자 이내)',
                style: GoogleFonts.notoSansKr(
                  fontSize: 14,
                  color: eInkSoft,
                  height: 1.5,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 16),
              TextField(
                controller: nameController,
                maxLength: 5,
                textAlign: TextAlign.center,
                decoration: InputDecoration(
                  hintText: '예: 루나, 친구, 봉봉',
                  hintStyle: const TextStyle(color: eInkSoft),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                    borderSide: const BorderSide(color: eLine),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                    borderSide: const BorderSide(color: eAccent, width: 2),
                  ),
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 12,
                  ),
                ),
                style: GoogleFonts.notoSansKr(
                  fontSize: 16,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ],
          ),
        ),
        actions: [
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: () async {
                if (nameController.text.isNotEmpty) {
                  final prefs = await SharedPreferences.getInstance();
                  await prefs.setString('ai_friend_name', nameController.text);

                  setState(() {
                    _friendName = nameController.text;
                  });

                  if (mounted) {
                    Navigator.pop(context);
                  }
                }
              },
              style: ElevatedButton.styleFrom(
                backgroundColor: eAccent,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
                padding: const EdgeInsets.symmetric(vertical: 12),
              ),
              child: Text(
                '설정 완료',
                style: GoogleFonts.notoSansKr(
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                  color: Colors.white,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _updateTime() {
    setState(() {
      _currentTime = DateFormat('H:mm').format(DateTime.now());
    });
    Future.delayed(const Duration(minutes: 1), _updateTime);
  }

  @override
  Widget build(BuildContext context) {
    final screenHeight = MediaQuery.of(context).size.height;
    final screenWidth = MediaQuery.of(context).size.width;

    return Scaffold(
      backgroundColor: eBg,
      body: SafeArea(
        child: SingleChildScrollView(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                // 인사말
                Text(
                  '오늘도\n평안한 하루\n보내세요',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.notoSerifKr(
                    fontSize: 32,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 28),

                // 다이얼 버튼 - 크기 증가
                GestureDetector(
                  onTap: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (context) =>
                            CallingScreen(callerName: _friendName),
                      ),
                    );
                  },
                  child: Container(
                    width: screenWidth * 0.65,
                    height: screenWidth * 0.65,
                    margin: const EdgeInsets.only(bottom: 12),
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: RadialGradient(
                        center: Alignment.center,
                        radius: 1.0,
                        colors: [
                          const Color(0xFFF4A574),
                          const Color(0xFFF4A574).withOpacity(0.75),
                          const Color(0xFFF4A574).withOpacity(0.45),
                          const Color(0xFFF4A574).withOpacity(0.15),
                          Colors.transparent,
                        ],
                        stops: const [0.0, 0.28, 0.50, 0.68, 0.82],
                      ),
                      boxShadow: [
                        BoxShadow(
                          color: const Color(0xFFF4A574).withOpacity(0.4),
                          blurRadius: 24,
                          spreadRadius: 8,
                        ),
                      ],
                    ),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          Icons.phone_rounded,
                          size: 52,
                          color: const Color(0xFF7B4020),
                        ),
                        const SizedBox(height: 12),
                        Text(
                          '$_friendName과 통화하기',
                          style: GoogleFonts.notoSerifKr(
                            fontSize: 28,
                            fontWeight: FontWeight.w800,
                            color: const Color(0xFF7B4020),
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          '편하게 누르세요',
                          style: GoogleFonts.notoSansKr(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                            color: const Color(0xFF7B4020).withOpacity(0.8),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),

                const SizedBox(height: 24),

                _buildMenuCard(
                  title: 'AI 채팅',
                  description: '글로 편하게 이야기해요',
                  backgroundColor: Color(0xFFF3E4D8),
                  iconColor: eBrass,
                  icon: Icons.chat_bubble_outline,
                  onTap: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (context) => const AiChatScreen(),
                      ),
                    );
                  },
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildMenuCard({
    required String title,
    required String description,
    required Color backgroundColor,
    required Color iconColor,
    required IconData icon,
    required VoidCallback onTap,
  }) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        decoration: BoxDecoration(
          color: eCard,
          border: Border.all(color: eLine, width: 2),
          borderRadius: BorderRadius.circular(22),
          boxShadow: [
            BoxShadow(
              color: eInk.withOpacity(0.08),
              blurRadius: 8,
              spreadRadius: 2,
            ),
          ],
        ),
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 28),
        child: Row(
          children: [
            Container(
              width: 76,
              height: 76,
              decoration: BoxDecoration(
                color: backgroundColor,
                borderRadius: BorderRadius.circular(18),
              ),
              child: Icon(icon, color: iconColor, size: 36),
            ),
            const SizedBox(width: 20),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: GoogleFonts.notoSansKr(
                      fontSize: 26,
                      fontWeight: FontWeight.w900,
                      color: eInk,
                      letterSpacing: 0.5,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    description,
                    style: GoogleFonts.notoSansKr(
                      fontSize: 16,
                      fontWeight: FontWeight.w500,
                      color: eInkSoft,
                    ),
                  ),
                ],
              ),
            ),
            Text(
              '›',
              style: TextStyle(
                fontSize: 32,
                fontWeight: FontWeight.bold,
                color: eAccent,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
