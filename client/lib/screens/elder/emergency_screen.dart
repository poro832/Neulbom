import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../../theme/app_theme.dart';


class EmergencyScreen extends StatelessWidget {
  const EmergencyScreen({super.key});

  void _handleEmergencyCall(BuildContext context, String name, String number) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(
          '$name 에게 전화',
          style: GoogleFonts.notoSansKr(
            fontSize: 24,
            fontWeight: FontWeight.w700,
          ),
        ),
        content: Text(
          '전화번호: $number',
          style: const TextStyle(fontSize: 18),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('취소', style: TextStyle(fontSize: 18)),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text('$name 에게 전화 중... ($number)'),
                  duration: const Duration(seconds: 3),
                ),
              );
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFFC0553F),
              padding: const EdgeInsets.symmetric(
                horizontal: 20,
                vertical: 12,
              ),
            ),
            child: const Text(
              '전화',
              style: TextStyle(
                fontSize: 18,
                color: Colors.white,
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: const Color(0xFFC0553F),
        elevation: 0,
        title: Text(
          '비상 연락',
          style: GoogleFonts.notoSerifKr(
            fontSize: 28,
            fontWeight: FontWeight.w700,
            color: Colors.white,
          ),
        ),
        centerTitle: true,
      ),
      body: SingleChildScrollView(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            children: [
              // 119 응급 버튼
              GestureDetector(
                onTap: () {
                  _handleEmergencyCall(context, '응급차', '119');
                },
                child: Container(
                  width: double.infinity,
                  decoration: BoxDecoration(
                    color: const Color(0xFFC0553F),
                    borderRadius: BorderRadius.circular(18),
                    boxShadow: [
                      BoxShadow(
                        color: const Color(0xFFC0553F).withOpacity(0.6),
                        blurRadius: 15,
                        offset: const Offset(0, 8),
                      ),
                    ],
                  ),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 20,
                    vertical: 20,
                  ),
                  child: Row(
                    children: [
                      Container(
                        width: 48,
                        height: 48,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: Colors.white.withOpacity(0.22),
                        ),
                        child: const Icon(
                          Icons.phone,
                          color: Colors.white,
                          size: 24,
                        ),
                      ),
                      const SizedBox(width: 14),
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '119 응급 전화',
                            style: GoogleFonts.notoSerifKr(
                              fontSize: 18.5,
                              fontWeight: FontWeight.w700,
                              color: Colors.white,
                            ),
                          ),
                          const SizedBox(height: 3),
                          Text(
                            '도움이 필요하면 바로 눌러주세요',
                            style: TextStyle(
                              fontSize: 14.5,
                              color: Colors.white.withOpacity(0.9),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 28),

              // 가족 연락처
              Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  '가족 연락처',
                  style: GoogleFonts.notoSansKr(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                    letterSpacing: 0.5,
                  ),
                ),
              ),
              const SizedBox(height: 12),
              _buildContactButton(
                context,
                '김보호 (딸)',
                '보호자',
                '010-1234-5678',
                const Color(0xFFE5F3EA),
                const Color(0xFF2E8F5E),
              ),
              const SizedBox(height: 10),
              _buildContactButton(
                context,
                '이효준 (아들)',
                '보호자',
                '010-2345-6789',
                const Color(0xFFE1E9F7),
                const Color(0xFF1F5C56),
              ),
              const SizedBox(height: 10),
              _buildContactButton(
                context,
                '박은숙 (며느리)',
                '보호자',
                '010-3456-7890',
                eAccentSoft,
                eAccent,
              ),
              const SizedBox(height: 30),

              // 기타 연락처
              Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  '기타 연락처',
                  style: GoogleFonts.notoSansKr(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                    letterSpacing: 0.5,
                  ),
                ),
              ),
              const SizedBox(height: 12),
              _buildContactButton(
                context,
                '은평구청',
                '복지담당',
                '02-351-4114',
                const Color(0xFFF0E8D5),
                const Color(0xFF8B6F47),
              ),
              const SizedBox(height: 10),
              _buildContactButton(
                context,
                '김영희 요양보호사',
                '돌봄 담당',
                '010-9876-5432',
                const Color(0xFFFFEDD5),
                const Color(0xFFE65100),
              ),
              const SizedBox(height: 10),
              _buildContactButton(
                context,
                '서울의료원',
                '병원',
                '02-2276-8114',
                const Color(0xFFE0F2F1),
                const Color(0xFF00695C),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildContactButton(
    BuildContext context,
    String name,
    String relation,
    String number,
    Color backgroundColor,
    Color iconColor,
  ) {
    return GestureDetector(
      onTap: () {
        _handleEmergencyCall(context, name, number);
      },
      child: Container(
        decoration: BoxDecoration(
          color: eCard,
          border: Border.all(color: eLine, width: 1),
          borderRadius: BorderRadius.circular(15),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
        child: Row(
          children: [
            Container(
              width: 60,
              height: 60,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: backgroundColor,
              ),
              child: Icon(
                Icons.call,
                color: iconColor,
                size: 28,
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    name,
                    style: GoogleFonts.notoSansKr(
                      fontSize: 17,
                      fontWeight: FontWeight.w700,
                      color: eInk,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    relation,
                    style: TextStyle(
                      fontSize: 13.5,
                      color: eInkSoft,
                    ),
                  ),
                ],
              ),
            ),
            Icon(
              Icons.chevron_right,
              color: iconColor,
              size: 28,
            ),
          ],
        ),
      ),
    );
  }
}
