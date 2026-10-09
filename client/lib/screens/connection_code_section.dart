import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../main.dart';
import '../models/nulbom_models.dart';
import '../services/nulbom_api.dart';

/// 어르신마다 연결 코드를 발급해 보여 준다. 어르신이 가입 화면에 이 코드와 전화번호를
/// 입력하면 그 폰이 이 어르신과 연결된다. 새로 발급하면 이전 코드는 쓸 수 없다.
class ConnectionCodeSection extends StatefulWidget {
  const ConnectionCodeSection({super.key});

  @override
  State<ConnectionCodeSection> createState() => _ConnectionCodeSectionState();
}

class _ConnectionCodeSectionState extends State<ConnectionCodeSection> {
  late Future<List<ElderSummary>> _elders;
  final Map<int, PairingCode> _codes = {};
  final Map<int, String> _errors = {};
  final Set<int> _busy = {};

  @override
  void initState() {
    super.initState();
    _elders = NulbomApi.guardianElders();
  }

  Future<void> _issue(int elderId) async {
    setState(() {
      _busy.add(elderId);
      _errors.remove(elderId);
    });
    try {
      final code = await NulbomApi.issuePairingCode(elderId);
      if (!mounted) return;
      setState(() => _codes[elderId] = code);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _errors[elderId] =
            error is ApiException ? error.message : '코드를 만들지 못했어요. 잠시 뒤에 다시 해 주세요.';
      });
    } finally {
      if (mounted) setState(() => _busy.remove(elderId));
    }
  }

  static String _expiry(DateTime time) =>
      '${time.month}월 ${time.day}일 ${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}까지';

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<ElderSummary>>(
      future: _elders,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Padding(
            padding: EdgeInsets.only(top: 10),
            child: LinearProgressIndicator(),
          );
        }
        if (snapshot.hasError) {
          final error = snapshot.error!;
          return _box(Text(
            error is ApiException ? error.message : '어르신 목록을 불러오지 못했어요.',
            style: GoogleFonts.notoSansKr(fontSize: 13, color: eInkSoft),
          ));
        }
        final elders = snapshot.data!;
        if (elders.isEmpty) {
          return _box(Text(
            '연결할 어르신이 아직 없어요.',
            style: GoogleFonts.notoSansKr(fontSize: 13, color: eInkSoft),
          ));
        }
        return Column(
          children: [for (final elder in elders) _elderRow(elder)],
        );
      },
    );
  }

  Widget _elderRow(ElderSummary elder) {
    final code = _codes[elder.elderId];
    final error = _errors[elder.elderId];
    return _box(
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  elder.name,
                  style: GoogleFonts.notoSansKr(
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                  ),
                ),
              ),
              TextButton(
                onPressed: _busy.contains(elder.elderId) ? null : () => _issue(elder.elderId),
                child: Text(
                  code == null ? '코드 발급' : '새 코드 발급',
                  style: GoogleFonts.notoSansKr(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: eAccent,
                  ),
                ),
              ),
            ],
          ),
          if (code != null) ...[
            const SizedBox(height: 6),
            SelectableText(
              code.code,
              style: GoogleFonts.notoSansKr(
                fontSize: 28,
                fontWeight: FontWeight.w800,
                letterSpacing: 4,
                color: eAccent,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              '${_expiry(code.expiresAt)} 쓸 수 있어요. 어르신 앱의 가입 화면에 이 코드와 어르신 전화번호를 입력하세요.',
              style: GoogleFonts.notoSansKr(fontSize: 11, color: eInkSoft),
            ),
          ],
          if (error != null) ...[
            const SizedBox(height: 6),
            Text(error, style: const TextStyle(fontSize: 12, color: Color(0xFFC0553F))),
          ],
        ],
      ),
    );
  }

  Widget _box(Widget child) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: eAccent.withOpacity(0.08),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: eAccent.withOpacity(0.25)),
      ),
      child: child,
    );
  }
}
