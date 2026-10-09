import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../models/nulbom_models.dart' show ElderSummary;
import '../services/nulbom_api.dart';
import 'elderly_detail_screen.dart' show ElderlyDetailScreen;

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
  List<ElderSummary>? _elders;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _elders = null;
      _error = null;
    });
    try {
      final list = await NulbomApi.guardianElders();
      if (!mounted) return;
      setState(() => _elders = list);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error is ApiException
            ? error.message
            : '어르신 목록을 불러오지 못했어요. 잠시 뒤에 다시 해 주세요.';
      });
    }
  }

  /// 서버에 아직 없는 기능(어르신 추가·삭제)은 가짜로 동작하지 않는다.
  void _notYet(String what) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('$what 기능은 추후 제공됩니다.'), backgroundColor: eAccent),
    );
  }

  /// 낮을수록 평소와 같다: 30점부터 주의, 60점부터 경보.
  static String _statusText(ElderSummary elder) {
    if (elder.status == 'pending') return '승인 대기';
    if (elder.status != 'active') return '동의 전';
    final score = elder.weekAvgScore;
    if (score == null) return '기록 없음';
    if (score >= 60) return '경보';
    if (score >= 30) return '주의';
    return '정상';
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
                if (_error != null) ...[
                  Text(_error!, style: const TextStyle(fontSize: 14, color: eInkSoft)),
                  TextButton(onPressed: _load, child: const Text('다시 시도')),
                ] else if (_elders == null)
                  const Center(child: CircularProgressIndicator())
                else ...[
                  Text(
                    '현재 관리 중인 어르신 (${_elders!.length}명)',
                    style: GoogleFonts.notoSerifKr(
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                      color: eInk,
                    ),
                  ),
                  const SizedBox(height: 16),
                  if (_elders!.isEmpty)
                    Container(
                      padding: const EdgeInsets.symmetric(vertical: 40),
                      alignment: Alignment.center,
                      child: const Text(
                        '관리 중인 어르신이 없습니다.',
                        style: TextStyle(fontSize: 16, color: eInkSoft),
                      ),
                    )
                  else
                    for (final elder in _elders!)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: GestureDetector(
                          onTap: elder.status == 'pending'
                              ? null
                              : () => Navigator.push(
                                    context,
                                    MaterialPageRoute(
                                      builder: (context) => ElderlyDetailScreen(
                                        elderlyId: elder.elderId,
                                        elderlyName: elder.name,
                                      ),
                                    ),
                                  ),
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
                                        elder.name,
                                        style: GoogleFonts.notoSansKr(
                                          fontSize: 16,
                                          fontWeight: FontWeight.w700,
                                          color: eInk,
                                        ),
                                      ),
                                      const SizedBox(height: 4),
                                      Text(
                                        _statusText(elder),
                                        style: const TextStyle(fontSize: 14, color: eInkSoft),
                                      ),
                                      const SizedBox(height: 6),
                                      Text(
                                        '이번 주 통화 ${elder.weekCalls}회',
                                        style: const TextStyle(
                                          fontSize: 12,
                                          color: eAccent,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                GestureDetector(
                                  onTap: () => _notYet('어르신 삭제'),
                                  child: Container(
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 12,
                                      vertical: 6,
                                    ),
                                    decoration: BoxDecoration(
                                      color: const Color(0xFFF44336).withOpacity(0.1),
                                      borderRadius: BorderRadius.circular(6),
                                      border: Border.all(
                                        color: const Color(0xFFF44336).withOpacity(0.3),
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
                ],

                const SizedBox(height: 24),

                // 추가 버튼
                SizedBox(
                  width: double.infinity,
                  height: 50,
                  child: ElevatedButton(
                    onPressed: () => _notYet('어르신 추가'),
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
