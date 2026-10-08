import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'elderly_detail_screen.dart';

const Color eBg = Color(0xFFFBF6ED);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);

class ElderlyListScreen extends StatefulWidget {
  const ElderlyListScreen({super.key});

  @override
  State<ElderlyListScreen> createState() => _ElderlyListScreenState();
}

class _ElderlyListScreenState extends State<ElderlyListScreen> {
  late List<Map<String, dynamic>> elderlies;

  @override
  void initState() {
    super.initState();
    elderlies = [
      {
        'id': 1,
        'name': '김할머니',
        'age': 78,
        'status': '정상',
        'statusColor': const Color(0xFF4CAF50),
        'lastContact': '오늘 14:30',
        'phone': '010-1234-5678',
        'relation': '모친',
      },
      {
        'id': 2,
        'name': '이할아버지',
        'age': 82,
        'status': '주의',
        'statusColor': const Color(0xFFFFA726),
        'lastContact': '어제 16:45',
        'phone': '010-9876-5432',
        'relation': '부친',
      },
    ];
  }

  void _showManagementMenu(
    BuildContext context,
    Map<String, dynamic> elderly,
  ) {
    showModalBottomSheet(
      context: context,
      builder: (BuildContext context) {
        return Container(
          color: eBg,
          child: SafeArea(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    children: [
                      Text(
                        '${elderly['name']} 관리',
                        style: GoogleFonts.notoSerifKr(
                          fontSize: 20,
                          fontWeight: FontWeight.w700,
                          color: eInk,
                        ),
                      ),
                      const SizedBox(height: 20),
                      _buildManagementOption(
                        icon: Icons.info_outline_rounded,
                        label: '상세 정보',
                        onTap: () {
                          Navigator.pop(context);
                          Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (context) => ElderlyDetailScreen(
                                elderlyId: elderly['id'],
                                elderlyName: elderly['name'],
                              ),
                            ),
                          );
                        },
                      ),
                      const SizedBox(height: 12),
                      _buildManagementOption(
                        icon: Icons.edit_outlined,
                        label: '정보 수정',
                        onTap: () {
                          Navigator.pop(context);
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                              content: Text('정보 수정 기능은 추후 제공됩니다.'),
                              backgroundColor: eAccent,
                            ),
                          );
                        },
                      ),
                      const SizedBox(height: 12),
                      _buildManagementOption(
                        icon: Icons.phone_rounded,
                        label: '연락처 편집',
                        onTap: () {
                          Navigator.pop(context);
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                              content: Text('연락처 편집 기능은 추후 제공됩니다.'),
                              backgroundColor: eAccent,
                            ),
                          );
                        },
                      ),
                      const SizedBox(height: 12),
                      _buildManagementOption(
                        icon: Icons.health_and_safety_outlined,
                        label: '건강 정보 관리',
                        color: const Color(0xFF2196F3),
                        onTap: () {
                          Navigator.pop(context);
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                              content: Text('건강 정보 관리 기능은 추후 제공됩니다.'),
                              backgroundColor: Color(0xFF2196F3),
                            ),
                          );
                        },
                      ),
                      const SizedBox(height: 12),
                      _buildManagementOption(
                        icon: Icons.delete_outline_rounded,
                        label: '관리 해제',
                        color: const Color(0xFFF44336),
                        onTap: () {
                          Navigator.pop(context);
                          _showDeleteConfirmation(context, elderly);
                        },
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  void _showDeleteConfirmation(
    BuildContext context,
    Map<String, dynamic> elderly,
  ) {
    showDialog(
      context: context,
      builder: (BuildContext context) {
        return AlertDialog(
          backgroundColor: eCard,
          title: Text(
            '관리 해제',
            style: GoogleFonts.notoSansKr(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: eInk,
            ),
          ),
          content: Text(
            '${elderly['name']}님을 관리 목록에서 제거하시겠습니까?',
            style: GoogleFonts.notoSansKr(
              fontSize: 14,
              color: eInkSoft,
            ),
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
              onPressed: () {
                Navigator.pop(context);
                setState(() {
                  elderlies.removeWhere((e) => e['id'] == elderly['id']);
                });
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text('${elderly['name']}님이 관리 목록에서 제거되었습니다.'),
                    backgroundColor: const Color(0xFF4CAF50),
                    duration: const Duration(seconds: 2),
                  ),
                );
              },
              child: Text(
                '해제',
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
    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        title: Text(
          '어르신 관리',
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
              // 통계 요약
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: eCard,
                  border: Border.all(color: eLine),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceAround,
                  children: [
                    Column(
                      children: [
                        Text(
                          '${elderlies.length}명',
                          style: GoogleFonts.notoSansKr(
                            fontSize: 20,
                            fontWeight: FontWeight.w700,
                            color: eAccent,
                          ),
                        ),
                        const SizedBox(height: 4),
                        const Text(
                          '관리 중',
                          style: TextStyle(
                            fontSize: 12,
                            color: eInkSoft,
                          ),
                        ),
                      ],
                    ),
                    Container(
                      width: 1,
                      height: 40,
                      color: eLine,
                    ),
                    Column(
                      children: [
                        Text(
                          '${elderlies.where((e) => e['status'] == '정상').length}명',
                          style: const TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w700,
                            color: Color(0xFF4CAF50),
                          ),
                        ),
                        const SizedBox(height: 4),
                        const Text(
                          '정상',
                          style: TextStyle(
                            fontSize: 12,
                            color: eInkSoft,
                          ),
                        ),
                      ],
                    ),
                    Container(
                      width: 1,
                      height: 40,
                      color: eLine,
                    ),
                    Column(
                      children: [
                        Text(
                          '${elderlies.where((e) => e['status'] == '주의').length}명',
                          style: const TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w700,
                            color: Color(0xFFFFA726),
                          ),
                        ),
                        const SizedBox(height: 4),
                        const Text(
                          '주의',
                          style: TextStyle(
                            fontSize: 12,
                            color: eInkSoft,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),

              // 어르신 목록
              Text(
                '관리 중인 어르신',
                style: GoogleFonts.notoSerifKr(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),
              ...elderlies.map((elderly) {
                return Container(
                  margin: const EdgeInsets.only(bottom: 12),
                  decoration: BoxDecoration(
                    color: eCard,
                    border: Border.all(color: eLine, width: 1),
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Material(
                    color: Colors.transparent,
                    child: InkWell(
                      borderRadius: BorderRadius.circular(14),
                      onTap: () {
                        Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (context) => ElderlyDetailScreen(
                              elderlyId: elderly['id'],
                              elderlyName: elderly['name'],
                            ),
                          ),
                        );
                      },
                      onLongPress: () {
                        _showManagementMenu(context, elderly);
                      },
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Container(
                                  width: 56,
                                  height: 56,
                                  decoration: BoxDecoration(
                                    shape: BoxShape.circle,
                                    color: eAccent.withOpacity(0.15),
                                  ),
                                  child: const Icon(
                                    Icons.person_outline_rounded,
                                    size: 28,
                                    color: eAccent,
                                  ),
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        elderly['name'],
                                        style: GoogleFonts.notoSansKr(
                                          fontSize: 16,
                                          fontWeight: FontWeight.w700,
                                          color: eInk,
                                        ),
                                      ),
                                      const SizedBox(height: 2),
                                      Text(
                                        '${elderly['age']}세 · ${elderly['relation']}',
                                        style: const TextStyle(
                                          fontSize: 12,
                                          color: eInkSoft,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 10,
                                    vertical: 6,
                                  ),
                                  decoration: BoxDecoration(
                                    color:
                                        elderly['statusColor'].withOpacity(0.15),
                                    borderRadius: BorderRadius.circular(8),
                                    border: Border.all(
                                      color: elderly['statusColor']
                                          .withOpacity(0.3),
                                    ),
                                  ),
                                  child: Text(
                                    elderly['status'],
                                    style: TextStyle(
                                      fontSize: 11,
                                      fontWeight: FontWeight.w600,
                                      color: elderly['statusColor'],
                                    ),
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 12),
                            Row(
                              children: [
                                Icon(
                                  Icons.phone_rounded,
                                  size: 14,
                                  color: eInkSoft,
                                ),
                                const SizedBox(width: 6),
                                Text(
                                  elderly['phone'],
                                  style: const TextStyle(
                                    fontSize: 12,
                                    color: eInkSoft,
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 4),
                            Row(
                              children: [
                                Icon(
                                  Icons.schedule_rounded,
                                  size: 14,
                                  color: eInkSoft,
                                ),
                                const SizedBox(width: 6),
                                Text(
                                  '마지막 연락: ${elderly['lastContact']}',
                                  style: const TextStyle(
                                    fontSize: 12,
                                    color: eInkSoft,
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 12),
                            Row(
                              children: [
                                Expanded(
                                  child: OutlinedButton.icon(
                                    onPressed: () {
                                      Navigator.push(
                                        context,
                                        MaterialPageRoute(
                                          builder: (context) =>
                                              ElderlyDetailScreen(
                                            elderlyId: elderly['id'],
                                            elderlyName: elderly['name'],
                                          ),
                                        ),
                                      );
                                    },
                                    icon: const Icon(
                                      Icons.info_outline_rounded,
                                      size: 16,
                                    ),
                                    label: const Text('상세보기'),
                                    style: OutlinedButton.styleFrom(
                                      foregroundColor: eAccent,
                                      side: const BorderSide(color: eAccent),
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 8),
                                OutlinedButton.icon(
                                  onPressed: () {
                                    _showManagementMenu(context, elderly);
                                  },
                                  icon: const Icon(
                                    Icons.more_vert_rounded,
                                    size: 16,
                                  ),
                                  label: const Text('관리'),
                                  style: OutlinedButton.styleFrom(
                                    foregroundColor: eInkSoft,
                                    side: const BorderSide(color: eLine),
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                );
              }).toList(),
              const SizedBox(height: 12),

              // 새로운 어르신 추가 버튼
              SizedBox(
                width: double.infinity,
                height: 56,
                child: OutlinedButton.icon(
                  onPressed: () {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('새 어르신 추가 기능은 추후 제공됩니다.'),
                        backgroundColor: eAccent,
                      ),
                    );
                  },
                  icon: const Icon(Icons.add_rounded),
                  label: const Text('새로운 어르신 추가'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: eAccent,
                    side: const BorderSide(color: eAccent),
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

  Widget _buildManagementOption({
    required IconData icon,
    required String label,
    Color color = eAccent,
    required VoidCallback onTap,
  }) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: eBg,
          border: Border.all(color: eLine),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Row(
          children: [
            Icon(icon, color: color, size: 20),
            const SizedBox(width: 12),
            Text(
              label,
              style: GoogleFonts.notoSansKr(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: color,
              ),
            ),
            const Spacer(),
            Icon(
              Icons.chevron_right_rounded,
              color: eInkSoft,
              size: 20,
            ),
          ],
        ),
      ),
    );
  }
}