import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../services/auth_service.dart';
import 'role_selection_screen.dart';
import 'elderly_management_screen.dart';

const Color eBg = Color(0xFFFBF6ED);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);

class GuardianAccountScreen extends StatefulWidget {
  const GuardianAccountScreen({super.key});

  @override
  State<GuardianAccountScreen> createState() => _GuardianAccountScreenState();
}

class _GuardianAccountScreenState extends State<GuardianAccountScreen> {
  late Map<String, dynamic> _guardianInfo;
  bool _isLoading = true;
  bool _notificationsEnabled = true;
  bool _emailNotificationsEnabled = true;
  bool _smsNotificationsEnabled = false;
  bool _showConnectionCode = false;

  @override
  void initState() {
    super.initState();
    _loadGuardianInfo();
  }

  Future<void> _loadGuardianInfo() async {
    final info = await AuthService.getUserInfo();
    setState(() {
      _guardianInfo = info;
      _isLoading = false;
    });
  }

  void _logout() {
    showDialog(
      context: context,
      builder: (BuildContext context) {
        return AlertDialog(
          backgroundColor: eCard,
          title: Text(
            '로그아웃',
            style: GoogleFonts.notoSansKr(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: eInk,
            ),
          ),
          content: Text(
            '로그아웃 하시겠습니까?',
            style: GoogleFonts.notoSansKr(fontSize: 14, color: eInkSoft),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
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
              onPressed: () async {
                await AuthService.logout();
                if (!mounted) return;
                Navigator.pushReplacement(
                  context,
                  MaterialPageRoute(
                    builder: (context) => const RoleSelectionScreen(),
                  ),
                );
              },
              child: Text(
                '로그아웃',
                style: GoogleFonts.notoSansKr(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: const Color(0xFFF44336),
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return Scaffold(
        backgroundColor: eBg,
        body: const Center(
          child: CircularProgressIndicator(
            valueColor: AlwaysStoppedAnimation<Color>(eAccent),
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        title: Text(
          '계정 관리',
          style: GoogleFonts.notoSerifKr(
            fontSize: 24,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded, color: eInk),
          onPressed: () => Navigator.pop(context),
        ),
      ),
      body: SingleChildScrollView(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 프로필 섹션
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: eCard,
                  border: Border.all(color: eLine),
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          width: 80,
                          height: 80,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: eAccent.withOpacity(0.15),
                          ),
                          child: const Icon(
                            Icons.person_rounded,
                            size: 40,
                            color: eAccent,
                          ),
                        ),
                        const SizedBox(width: 16),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                _guardianInfo['name'] ?? '보호자',
                                style: GoogleFonts.notoSansKr(
                                  fontSize: 20,
                                  fontWeight: FontWeight.w700,
                                  color: eInk,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                _guardianInfo['email'] ?? 'email@example.com',
                                style: const TextStyle(
                                  fontSize: 13,
                                  color: eInkSoft,
                                ),
                              ),
                              const SizedBox(height: 8),
                              Row(
                                children: [
                                  Container(
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 10,
                                      vertical: 4,
                                    ),
                                    decoration: BoxDecoration(
                                      color: const Color(
                                        0xFF4CAF50,
                                      ).withOpacity(0.15),
                                      borderRadius: BorderRadius.circular(6),
                                    ),
                                    child: const Text(
                                      '활성 중',
                                      style: TextStyle(
                                        fontSize: 11,
                                        fontWeight: FontWeight.w600,
                                        color: Color(0xFF4CAF50),
                                      ),
                                    ),
                                  ),
                                  const SizedBox(width: 8),
                                  TextButton(
                                    onPressed: () {
                                      setState(() {
                                        _showConnectionCode =
                                            !_showConnectionCode;
                                      });
                                    },
                                    style: TextButton.styleFrom(
                                      padding: EdgeInsets.zero,
                                      minimumSize: Size.zero,
                                      tapTargetSize:
                                          MaterialTapTargetSize.shrinkWrap,
                                    ),
                                    child: Text(
                                      _showConnectionCode
                                          ? '연결코드 숨기기'
                                          : '연결코드 확인하기',
                                      style: GoogleFonts.notoSansKr(
                                        fontSize: 11,
                                        fontWeight: FontWeight.w600,
                                        color: eAccent,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                              if (_showConnectionCode) ...[
                                const SizedBox(height: 10),
                                Container(
                                  width: double.infinity,
                                  padding: const EdgeInsets.all(10),
                                  decoration: BoxDecoration(
                                    color: eAccent.withOpacity(0.08),
                                    borderRadius: BorderRadius.circular(8),
                                    border: Border.all(
                                      color: eAccent.withOpacity(0.25),
                                    ),
                                  ),
                                  child: Text(
                                    '보호자 연결 코드: '
                                    '${_guardianInfo['connectionCode'] ?? '-'}',
                                    style: GoogleFonts.notoSansKr(
                                      fontSize: 13,
                                      fontWeight: FontWeight.w600,
                                      color: eAccent,
                                    ),
                                  ),
                                ),
                              ],
                            ],
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 28),

              // 기본 정보
              Text(
                '기본 정보',
                style: GoogleFonts.notoSerifKr(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),
              _buildInfoCard(
                icon: Icons.person_outline_rounded,
                label: '이름',
                value: _guardianInfo['name'] ?? '-',
              ),
              const SizedBox(height: 12),
              _buildInfoCard(
                icon: Icons.email_outlined,
                label: '이메일',
                value: _guardianInfo['email'] ?? '-',
              ),
              const SizedBox(height: 28),

              // 알림 설정
              Text(
                '알림 설정',
                style: GoogleFonts.notoSerifKr(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: eCard,
                  border: Border.all(color: eLine),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Column(
                  children: [
                    _buildNotificationOption(
                      title: '푸시 알림',
                      subtitle: '건강 경고 및 중요 이벤트 알림',
                      value: _notificationsEnabled,
                      onChanged: (val) {
                        setState(() {
                          _notificationsEnabled = val;
                        });
                      },
                    ),
                    const Divider(color: eLine, height: 24),
                    _buildNotificationOption(
                      title: '이메일 알림',
                      subtitle: '일일 요약 및 주간 보고서',
                      value: _emailNotificationsEnabled,
                      onChanged: (val) {
                        setState(() {
                          _emailNotificationsEnabled = val;
                        });
                      },
                    ),
                    const Divider(color: eLine, height: 24),
                    _buildNotificationOption(
                      title: 'SMS 알림',
                      subtitle: '긴급 상황 알림만',
                      value: _smsNotificationsEnabled,
                      onChanged: (val) {
                        setState(() {
                          _smsNotificationsEnabled = val;
                        });
                      },
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 28),

              // 관리 중인 어르신
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    '관리 중인 어르신',
                    style: GoogleFonts.notoSerifKr(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: eInk,
                    ),
                  ),
                  GestureDetector(
                    onTap: () {
                      Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (context) => const ElderlyManagementScreen(),
                        ),
                      );
                    },
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 6,
                      ),
                      decoration: BoxDecoration(
                        color: eAccent,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        '수정',
                        style: GoogleFonts.notoSansKr(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: Colors.white,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: eCard,
                  border: Border.all(color: eLine),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _buildElderlyItem('김할머니', '78세', '정상'),
                    const Divider(color: eLine, height: 20),
                    _buildElderlyItem('이할아버지', '82세', '주의'),
                  ],
                ),
              ),
              const SizedBox(height: 28),

              // 계정 보안
              Text(
                '계정 보안',
                style: GoogleFonts.notoSerifKr(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),
              GestureDetector(
                onTap: () {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('비밀번호 변경 기능은 추후 제공됩니다.'),
                      backgroundColor: eAccent,
                      duration: Duration(seconds: 2),
                    ),
                  );
                },
                child: Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: eCard,
                    border: Border.all(color: eLine),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Row(
                        children: [
                          const Icon(
                            Icons.lock_outline_rounded,
                            color: eAccent,
                            size: 24,
                          ),
                          const SizedBox(width: 12),
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '비밀번호 변경',
                                style: GoogleFonts.notoSansKr(
                                  fontSize: 14,
                                  fontWeight: FontWeight.w600,
                                  color: eInk,
                                ),
                              ),
                              const SizedBox(height: 2),
                              const Text(
                                '계정 보안을 위해 비밀번호를 변경하세요',
                                style: TextStyle(fontSize: 12, color: eInkSoft),
                              ),
                            ],
                          ),
                        ],
                      ),
                      const Icon(Icons.chevron_right_rounded, color: eInkSoft),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 28),

              // 로그아웃 버튼
              SizedBox(
                width: double.infinity,
                height: 56,
                child: ElevatedButton.icon(
                  onPressed: _logout,
                  icon: const Icon(Icons.logout_rounded, size: 20),
                  label: Text(
                    '로그아웃',
                    style: GoogleFonts.notoSansKr(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: Colors.white,
                    ),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFFF44336),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 20),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildInfoCard({
    required IconData icon,
    required String label,
    required String value,
  }) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: eCard,
        border: Border.all(color: eLine),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Icon(icon, color: eAccent, size: 24),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: TextStyle(
                    fontSize: 12,
                    color: eInkSoft,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  value,
                  style: GoogleFonts.notoSansKr(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: eInk,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildNotificationOption({
    required String title,
    required String subtitle,
    required bool value,
    required Function(bool) onChanged,
  }) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: GoogleFonts.notoSansKr(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                subtitle,
                style: const TextStyle(fontSize: 12, color: eInkSoft),
              ),
            ],
          ),
        ),
        Switch(
          value: value,
          onChanged: onChanged,
          activeColor: eAccent,
          inactiveThumbColor: eInkSoft,
        ),
      ],
    );
  }

  Widget _buildElderlyItem(String name, String age, String status) {
    final statusColor = status == '정상'
        ? const Color(0xFF4CAF50)
        : const Color(0xFFFFA726);

    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              name,
              style: GoogleFonts.notoSansKr(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: eInk,
              ),
            ),
            const SizedBox(height: 2),
            Text(age, style: const TextStyle(fontSize: 12, color: eInkSoft)),
          ],
        ),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            color: statusColor.withOpacity(0.15),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Text(
            status,
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: statusColor,
            ),
          ),
        ),
      ],
    );
  }
}
