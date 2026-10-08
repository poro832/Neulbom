import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

const Color eBg = Color(0xFFFBF6ED);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);
const Color eAccentSoft = Color(0xFFFBE4D3);

class ElderlyManagementScreen extends StatefulWidget {
  const ElderlyManagementScreen({super.key});

  @override
  State<ElderlyManagementScreen> createState() =>
      _ElderlyManagementScreenState();
}

class _ElderlyManagementScreenState extends State<ElderlyManagementScreen> {
  late List<Map<String, dynamic>> _elders;

  // Mock 어르신 데이터
  final List<Map<String, dynamic>> _initialElders = [
    {
      'id': 1,
      'name': '김할머니',
      'age': 78,
      'status': '정상',
      'contacts': [
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
      ],
    },
    {
      'id': 2,
      'name': '이할아버지',
      'age': 82,
      'status': '주의',
      'contacts': [
        {
          'name': '이순신 (아들)',
          'relation': '보호자',
          'number': '010-4567-8901',
        },
        {
          'name': '정욕심 (딸)',
          'relation': '보호자',
          'number': '010-5678-9012',
        },
      ],
    },
  ];

  @override
  void initState() {
    super.initState();
    _elders = List.from(_initialElders);
  }

  void _addElderly() {
    final nameController = TextEditingController();
    final ageController = TextEditingController();

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: eCard,
        title: Text(
          '어르신 추가',
          style: GoogleFonts.notoSerifKr(
            fontSize: 18,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: nameController,
              decoration: InputDecoration(
                hintText: '이름',
                hintStyle: const TextStyle(color: eInkSoft),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: const BorderSide(color: eLine),
                ),
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 10,
                ),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: ageController,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(
                hintText: '나이',
                hintStyle: const TextStyle(color: eInkSoft),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: const BorderSide(color: eLine),
                ),
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 10,
                ),
              ),
            ),
          ],
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
              if (nameController.text.isNotEmpty &&
                  ageController.text.isNotEmpty) {
                setState(() {
                  _elders.add({
                    'id': _elders.length + 1,
                    'name': nameController.text,
                    'age': int.parse(ageController.text),
                    'status': '정상',
                    'contacts': [],
                  });
                });
                Navigator.pop(context);
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('어르신이 추가되었습니다.'),
                    backgroundColor: eAccent,
                    duration: Duration(seconds: 2),
                  ),
                );
              }
            },
            child: Text(
              '추가',
              style: GoogleFonts.notoSansKr(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: eAccent,
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _deleteElderly(int index) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: eCard,
        title: Text(
          '어르신 삭제',
          style: GoogleFonts.notoSerifKr(
            fontSize: 18,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        content: Text(
          '${_elders[index]['name']}을(를) 정말로 삭제하시겠습니까?',
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
              setState(() {
                _elders.removeAt(index);
              });
              Navigator.pop(context);
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('어르신이 삭제되었습니다.'),
                  backgroundColor: eAccent,
                  duration: Duration(seconds: 2),
                ),
              );
            },
            child: Text(
              '삭제',
              style: GoogleFonts.notoSansKr(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: const Color(0xFFF44336),
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _showContactsManager(int elderIndex) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: eCard,
        title: Text(
          '${_elders[elderIndex]['name']} 연락처 관리',
          style: GoogleFonts.notoSerifKr(
            fontSize: 18,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if ((_elders[elderIndex]['contacts'] as List).isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 20),
                  child: Text(
                    '등록된 연락처가 없습니다.',
                    style: TextStyle(
                      fontSize: 14,
                      color: eInkSoft,
                    ),
                  ),
                )
              else
                ...List.generate(
                  (_elders[elderIndex]['contacts'] as List).length,
                  (contactIndex) {
                    final contact =
                        (_elders[elderIndex]['contacts'] as List)[contactIndex];
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Container(
                        decoration: BoxDecoration(
                          color: Colors.white,
                          border: Border.all(color: eLine),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        padding: const EdgeInsets.all(12),
                        child: Row(
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    contact['name'],
                                    style: GoogleFonts.notoSansKr(
                                      fontSize: 14,
                                      fontWeight: FontWeight.w600,
                                      color: eInk,
                                    ),
                                  ),
                                  const SizedBox(height: 2),
                                  Text(
                                    contact['number'],
                                    style: TextStyle(
                                      fontSize: 12,
                                      color: eInkSoft,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            GestureDetector(
                              onTap: () {
                                setState(() {
                                  (_elders[elderIndex]['contacts'] as List)
                                      .removeAt(contactIndex);
                                });
                                Navigator.pop(context);
                                _showContactsManager(elderIndex);
                              },
                              child: const Icon(
                                Icons.delete_outline,
                                color: Color(0xFFF44336),
                                size: 20,
                              ),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => _addContactToElderly(elderIndex),
            child: Text(
              '+ 연락처 추가',
              style: GoogleFonts.notoSansKr(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: eAccent,
              ),
            ),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(
              '닫기',
              style: GoogleFonts.notoSansKr(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: eInkSoft,
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _addContactToElderly(int elderIndex) {
    final nameController = TextEditingController();
    final relationController = TextEditingController();
    final numberController = TextEditingController();

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: eCard,
        title: Text(
          '연락처 추가',
          style: GoogleFonts.notoSerifKr(
            fontSize: 18,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: nameController,
              decoration: InputDecoration(
                hintText: '이름',
                hintStyle: const TextStyle(color: eInkSoft),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: const BorderSide(color: eLine),
                ),
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 10,
                ),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: relationController,
              decoration: InputDecoration(
                hintText: '관계 (예: 딸, 아들)',
                hintStyle: const TextStyle(color: eInkSoft),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: const BorderSide(color: eLine),
                ),
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 10,
                ),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: numberController,
              decoration: InputDecoration(
                hintText: '전화번호',
                hintStyle: const TextStyle(color: eInkSoft),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: const BorderSide(color: eLine),
                ),
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 10,
                ),
              ),
            ),
          ],
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
              if (nameController.text.isNotEmpty &&
                  relationController.text.isNotEmpty &&
                  numberController.text.isNotEmpty) {
                setState(() {
                  (_elders[elderIndex]['contacts'] as List).add({
                    'name': nameController.text,
                    'relation': relationController.text,
                    'number': numberController.text,
                  });
                });
                Navigator.pop(context);
                _showContactsManager(elderIndex);
              } else {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('모든 항목을 입력해주세요.'),
                    duration: Duration(seconds: 2),
                  ),
                );
              }
            },
            child: Text(
              '추가',
              style: GoogleFonts.notoSansKr(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: eAccent,
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
        backgroundColor: eBg,
        elevation: 0,
        leading: IconButton(
          icon: Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: Colors.white,
              border: Border.all(color: eLine, width: 2),
              boxShadow: [
                BoxShadow(
                  color: eInk.withOpacity(0.1),
                  blurRadius: 6,
                  spreadRadius: 1,
                ),
              ],
            ),
            child: const Icon(Icons.chevron_left, color: eInk, size: 24),
          ),
          onPressed: () => Navigator.pop(context),
          padding: EdgeInsets.zero,
          constraints: const BoxConstraints(
            minWidth: 44,
            minHeight: 44,
          ),
        ),
        title: Text(
          '어르신 관리',
          style: GoogleFonts.notoSerifKr(
            fontSize: 20,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        centerTitle: false,
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 어르신 목록
                Text(
                  '현재 관리 중인 어르신 (${_elders.length}명)',
                  style: GoogleFonts.notoSerifKr(
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                  ),
                ),
                const SizedBox(height: 16),

                if (_elders.isEmpty)
                  Container(
                    padding: const EdgeInsets.symmetric(vertical: 40),
                    alignment: Alignment.center,
                    child: Text(
                      '관리 중인 어르신이 없습니다.',
                      style: TextStyle(
                        fontSize: 16,
                        color: eInkSoft,
                      ),
                    ),
                  )
                else
                  ...List.generate(
                    _elders.length,
                    (index) => Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: GestureDetector(
                        onTap: () => _showContactsManager(index),
                        child: Container(
                          decoration: BoxDecoration(
                            color: eCard,
                            border: Border.all(color: eLine),
                            borderRadius: BorderRadius.circular(12),
                          ),
                          padding: const EdgeInsets.all(14),
                          child: Row(
                            children: [
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      _elders[index]['name'] as String,
                                      style: GoogleFonts.notoSansKr(
                                        fontSize: 16,
                                        fontWeight: FontWeight.w700,
                                        color: eInk,
                                      ),
                                    ),
                                    const SizedBox(height: 4),
                                    Text(
                                      '${_elders[index]['age']}세 • ${_elders[index]['status']}',
                                      style: TextStyle(
                                        fontSize: 14,
                                        color: eInkSoft,
                                      ),
                                    ),
                                    const SizedBox(height: 6),
                                    Text(
                                      '연락처: ${(_elders[index]['contacts'] as List).length}개',
                                      style: TextStyle(
                                        fontSize: 12,
                                        color: eAccent,
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              GestureDetector(
                                onTap: () => _deleteElderly(index),
                                child: Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 12,
                                    vertical: 6,
                                  ),
                                  decoration: BoxDecoration(
                                    color: const Color(0xFFF44336).withOpacity(0.1),
                                    borderRadius: BorderRadius.circular(6),
                                    border: Border.all(
                                      color: const Color(0xFFF44336)
                                          .withOpacity(0.3),
                                    ),
                                  ),
                                  child: Text(
                                    '삭제',
                                    style: GoogleFonts.notoSansKr(
                                      fontSize: 12,
                                      fontWeight: FontWeight.w600,
                                      color: const Color(0xFFF44336),
                                    ),
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),

                const SizedBox(height: 24),

                // 추가 버튼
                SizedBox(
                  width: double.infinity,
                  height: 50,
                  child: ElevatedButton(
                    onPressed: _addElderly,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: eAccent,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(
                          Icons.add_rounded,
                          color: Colors.white,
                          size: 22,
                        ),
                        const SizedBox(width: 8),
                        Text(
                          '어르신 추가',
                          style: GoogleFonts.notoSansKr(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                            color: Colors.white,
                          ),
                        ),
                      ],
                    ),
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
