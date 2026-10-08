import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

const Color eBg = Color(0xFFFBF6ED);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);
const Color eAccentSoft = Color(0xFFFBE4D3);

class EmergencyScreen extends StatefulWidget {
  const EmergencyScreen({super.key});

  @override
  State<EmergencyScreen> createState() => _EmergencyScreenState();
}

class _EmergencyScreenState extends State<EmergencyScreen> {
  final List<Map<String, String>> contacts = [
    {
      'name': '김보호 (딸)',
      'relation': '보호자',
      'number': '010-1234-5678',
    },
    {
      'name': '이효준 (아들)',
      'relation': '보호자',
      'number': '010-2345-6789',
    },
    {
      'name': '박은숙 (며느리)',
      'relation': '보호자',
      'number': '010-3456-7890',
    },
  ];

  final List<Map<String, String>> otherContacts = [
    {
      'name': '은평구청',
      'relation': '복지담당',
      'number': '02-351-4114',
    },
    {
      'name': '김영희 요양보호사',
      'relation': '돌봄 담당',
      'number': '010-9876-5432',
    },
    {
      'name': '서울의료원',
      'relation': '병원',
      'number': '02-2276-8114',
    },
  ];

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

  void _showAddContactDialog(BuildContext context) {
    final nameController = TextEditingController();
    final relationController = TextEditingController();
    final numberController = TextEditingController();

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(
          '연락처 추가',
          style: GoogleFonts.notoSansKr(
            fontSize: 22,
            fontWeight: FontWeight.w700,
          ),
        ),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nameController,
                decoration: InputDecoration(
                  hintText: '이름',
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: relationController,
                decoration: InputDecoration(
                  hintText: '관계 (예: 딸, 아들)',
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: numberController,
                decoration: InputDecoration(
                  hintText: '전화번호',
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('취소'),
          ),
          ElevatedButton(
            onPressed: () {
              if (nameController.text.isNotEmpty &&
                  relationController.text.isNotEmpty &&
                  numberController.text.isNotEmpty) {
                setState(() {
                  contacts.add({
                    'name': nameController.text,
                    'relation': relationController.text,
                    'number': numberController.text,
                  });
                });
                Navigator.pop(context);
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text('${nameController.text} 연락처가 추가되었습니다.'),
                    duration: const Duration(seconds: 2),
                  ),
                );
              } else {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('모든 항목을 입력해주세요.'),
                    duration: const Duration(seconds: 2),
                  ),
                );
              }
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFFC0553F),
            ),
            child: const Text(
              '추가',
              style: TextStyle(color: Colors.white),
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
        automaticallyImplyLeading: false,
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
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    '가족 연락처',
                    style: GoogleFonts.notoSansKr(
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: eInk,
                      letterSpacing: 0.5,
                    ),
                  ),
                  GestureDetector(
                    onTap: () => _showAddContactDialog(context),
                    child: Container(
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: const Color(0xFFC0553F),
                      ),
                      padding: const EdgeInsets.all(8),
                      child: const Icon(
                        Icons.add,
                        color: Colors.white,
                        size: 20,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              ...List.generate(
                contacts.length,
                (index) {
                  final colors = [
                    (const Color(0xFFE5F3EA), const Color(0xFF2E8F5E)),
                    (const Color(0xFFE1E9F7), const Color(0xFF1F5C56)),
                    (eAccentSoft, eAccent),
                  ];
                  final (bgColor, iconColor) = colors[index % colors.length];

                  return Column(
                    children: [
                      _buildContactButton(
                        context,
                        contacts[index]['name']!,
                        contacts[index]['relation']!,
                        contacts[index]['number']!,
                        bgColor,
                        iconColor,
                      ),
                      if (index < contacts.length - 1)
                        const SizedBox(height: 10),
                    ],
                  );
                },
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
              ...List.generate(
                otherContacts.length,
                (index) {
                  final colors = [
                    (const Color(0xFFF0E8D5), const Color(0xFF8B6F47)),
                    (const Color(0xFFFFEDD5), const Color(0xFFE65100)),
                    (const Color(0xFFE0F2F1), const Color(0xFF00695C)),
                  ];
                  final (bgColor, iconColor) = colors[index % colors.length];

                  return Column(
                    children: [
                      _buildContactButton(
                        context,
                        otherContacts[index]['name']!,
                        otherContacts[index]['relation']!,
                        otherContacts[index]['number']!,
                        bgColor,
                        iconColor,
                      ),
                      if (index < otherContacts.length - 1)
                        const SizedBox(height: 10),
                    ],
                  );
                },
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
