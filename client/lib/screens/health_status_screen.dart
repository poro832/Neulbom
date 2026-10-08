import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

const Color eBg = Color(0xFFFBF6ED);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);

class HealthStatusScreen extends StatelessWidget {
  const HealthStatusScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: eBg,
      appBar: AppBar(
        backgroundColor: eBg,
        elevation: 0,
        title: Text(
          '건강 현황',
          style: GoogleFonts.notoSerifKr(
            fontSize: 28,
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
              // 실시간 상태
              Text(
                '실시간 건강 지표',
                style: GoogleFonts.notoSerifKr(
                  fontSize: 22,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),

              // 상태 카드들
              _buildHealthCard(
                title: '혈압',
                value: '120/80',
                unit: 'mmHg',
                status: '정상',
                color: const Color(0xFF4CAF50),
              ),
              const SizedBox(height: 12),

              _buildHealthCard(
                title: '심박수',
                value: '72',
                unit: 'bpm',
                status: '정상',
                color: const Color(0xFF4CAF50),
              ),
              const SizedBox(height: 12),

              _buildHealthCard(
                title: '혈당',
                value: '95',
                unit: 'mg/dL',
                status: '정상',
                color: const Color(0xFF4CAF50),
              ),
              const SizedBox(height: 12),

              _buildHealthCard(
                title: '체온',
                value: '36.5',
                unit: '도',
                status: '정상',
                color: const Color(0xFF4CAF50),
              ),
              const SizedBox(height: 24),

              // 일일 활동
              Text(
                '일일 활동',
                style: GoogleFonts.notoSerifKr(
                  fontSize: 22,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),

              Container(
                decoration: BoxDecoration(
                  color: eCard,
                  border: Border.all(color: eLine),
                  borderRadius: BorderRadius.circular(12),
                ),
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          '걸음수',
                          style: GoogleFonts.notoSansKr(
                            fontSize: 20,
                            fontWeight: FontWeight.w700,
                            color: eInk,
                          ),
                        ),
                        Text(
                          '7,245 / 10,000',
                          style: TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w700,
                            color: eAccent,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: LinearProgressIndicator(
                        value: 7245 / 10000,
                        minHeight: 8,
                        backgroundColor: eLine,
                        valueColor: AlwaysStoppedAnimation(eAccent),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),

              Container(
                decoration: BoxDecoration(
                  color: eCard,
                  border: Border.all(color: eLine),
                  borderRadius: BorderRadius.circular(12),
                ),
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          '수면시간',
                          style: GoogleFonts.notoSansKr(
                            fontSize: 20,
                            fontWeight: FontWeight.w700,
                            color: eInk,
                          ),
                        ),
                        Text(
                          '7.5시간',
                          style: TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w700,
                            color: const Color(0xFF2196F3),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: LinearProgressIndicator(
                        value: 7.5 / 8,
                        minHeight: 8,
                        backgroundColor: eLine,
                        valueColor: const AlwaysStoppedAnimation(Color(0xFF2196F3)),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),

              // 약물 일정
              Text(
                '약물 복용 일정',
                style: GoogleFonts.notoSerifKr(
                  fontSize: 22,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 12),

              Container(
                decoration: BoxDecoration(
                  color: eCard,
                  border: Border.all(color: eLine),
                  borderRadius: BorderRadius.circular(12),
                ),
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: [
                    _buildMedicationItem(
                      '혈압약',
                      '09:00',
                      true,
                    ),
                    const SizedBox(height: 12),
                    _buildMedicationItem(
                      '당뇨약',
                      '12:00',
                      true,
                    ),
                    const SizedBox(height: 12),
                    _buildMedicationItem(
                      '수면제',
                      '21:00',
                      false,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHealthCard({
    required String title,
    required String value,
    required String unit,
    required String status,
    required Color color,
  }) {
    return Container(
      decoration: BoxDecoration(
        color: eCard,
        border: Border.all(color: eLine),
        borderRadius: BorderRadius.circular(12),
      ),
      padding: const EdgeInsets.all(16),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: GoogleFonts.notoSansKr(
                  fontSize: 18,
                  fontWeight: FontWeight.w600,
                  color: eInkSoft,
                ),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Text(
                    value,
                    style: GoogleFonts.notoSansKr(
                      fontSize: 28,
                      fontWeight: FontWeight.w700,
                      color: eInk,
                    ),
                  ),
                  const SizedBox(width: 4),
                  Text(
                    unit,
                    style: TextStyle(
                      fontSize: 16,
                      color: eInkSoft,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ],
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: color.withOpacity(0.15),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              status,
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: color,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMedicationItem(
    String name,
    String time,
    bool taken,
  ) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                name,
                style: GoogleFonts.notoSansKr(
                  fontSize: 18,
                  fontWeight: FontWeight.w600,
                  color: eInk,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                time,
                style: const TextStyle(
                  fontSize: 16,
                  color: eInkSoft,
                ),
              ),
            ],
          ),
        ),
        Icon(
          taken ? Icons.check_circle_rounded : Icons.schedule_rounded,
          color: taken ? const Color(0xFF4CAF50) : eInkSoft,
          size: 24,
        ),
      ],
    );
  }
}
