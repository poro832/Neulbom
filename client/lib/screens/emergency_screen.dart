import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../models/nulbom_models.dart';
import '../services/nulbom_api.dart';

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
  // 보호자(서버가 DB에서 채운다)와 어르신이 추가한 연락처를 한 목록으로 보여 준다.
  // 'id'가 있는 것만 어르신이 추가한 연락처라 길게 눌러 지울 수 있다.
  List<Map<String, String>> contacts = [];
  bool _loading = true;
  String? _loadError;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final mine = await NulbomApi.myContacts();
      if (!mounted) return;
      setState(() {
        contacts = [
          for (final g in mine.guardians)
            {'name': g.name, 'relation': g.relation, 'number': g.phone, 'id': ''},
          for (final c in mine.contacts)
            {
              'name': c.name,
              'relation': c.relation,
              'number': c.phone,
              'id': '${c.contactId}',
            },
        ];
        _loading = false;
        _loadError = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _loadError = error is ApiException
            ? error.message
            : '연락처를 불러오지 못했어요. 잠시 뒤에 다시 해 주세요.';
      });
    }
  }

  Future<void> _addContact(BuildContext dialogContext, String name, String relation,
      String number) async {
    try {
      await NulbomApi.addContact(name: name, relation: relation, phone: number);
      if (!mounted) return;
      Navigator.pop(dialogContext);
      await _load();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$name 연락처가 추가되었습니다.'), duration: const Duration(seconds: 2)),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(error is ApiException ? error.message : '추가하지 못했어요.'),
          duration: const Duration(seconds: 3),
        ),
      );
    }
  }

  Future<void> _confirmDelete(Map<String, String> contact) async {
    final id = int.tryParse(contact['id'] ?? '');
    if (id == null) return; // 보호자는 지울 수 없다
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('${contact['name']} 연락처를 지울까요?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('아니요')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('지우기')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await NulbomApi.deleteContact(id);
      await _load();
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error is ApiException ? error.message : '지우지 못했어요.')),
      );
    }
  }

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
                _addContact(
                  context,
                  nameController.text.trim(),
                  relationController.text.trim(),
                  numberController.text.trim(),
                );
              } else {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('모든 항목을 입력해주세요.'),
                    duration: Duration(seconds: 2),
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
              if (_loading)
                const Padding(
                  padding: EdgeInsets.all(24),
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (_loadError != null)
                Padding(
                  padding: const EdgeInsets.all(24),
                  child: Text(_loadError!, style: const TextStyle(fontSize: 18, color: eInkSoft)),
                )
              else if (contacts.isEmpty)
                const Padding(
                  padding: EdgeInsets.all(24),
                  child: Text('등록된 연락처가 없어요.', style: TextStyle(fontSize: 18, color: eInkSoft)),
                ),
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
                      GestureDetector(
                        onLongPress: () => _confirmDelete(contacts[index]),
                        child: _buildContactButton(
                          context,
                          contacts[index]['name']!,
                          contacts[index]['relation']!,
                          contacts[index]['number']!,
                          bgColor,
                          iconColor,
                        ),
                      ),
                      if (index < contacts.length - 1)
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
