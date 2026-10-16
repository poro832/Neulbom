import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../main.dart' show eAccent, eCard, eInk, eInkSoft, eLine;
import '../services/nulbom_api.dart';

/// 보호자가 고를 수 있는 안부 전화 시간: 07:00부터 21:00까지 30분 단위 29개(서버 app_data.py의 범위와 같다).
final List<String> callTimeChoices = [
  for (var m = 7 * 60; m <= 21 * 60; m += 30)
    '${(m ~/ 60).toString().padLeft(2, '0')}:${(m % 60).toString().padLeft(2, '0')}',
];

/// 서버의 `HH:MM`(24시간)을 한국어 12시간 표기로 바꾼다: `13:30` → `오후 1:30`.
/// 정오는 `오후 12:00`, 자정 쪽은 `오전 12:30`이다.
String formatCallTime(String hhmm) {
  final parts = hhmm.split(':');
  final hour = int.parse(parts[0]);
  final minute = parts.length > 1 ? parts[1].padLeft(2, '0') : '00';
  final period = hour < 12 ? '오전' : '오후';
  final hour12 = hour % 12 == 0 ? 12 : hour % 12;
  return '$period $hour12:$minute';
}

/// 보호자: 하루 한 번 AI가 어르신께 전화하는 시간을 보고 바꾼다.
///
/// 서버의 스케줄러는 이 값을 매분 새로 읽는다. 방금(30분 안에) 지난 시간으로 바꾸면 곧바로 전화가 걸리므로
/// 서버가 409로 거절하고, 그 문장을 시트 안에 그대로 보인다. 화면은 서버가 저장했다고 답한 값만 보인다.
class ElderCallTimeCard extends StatefulWidget {
  final int elderId;

  /// 테스트에서 바꾼다. 기본은 [NulbomApi.callTime].
  final Future<String> Function(int elderId)? fetch;

  /// 테스트에서 바꾼다. 기본은 [NulbomApi.setCallTime].
  final Future<String> Function(int elderId, String hhmm)? save;

  const ElderCallTimeCard({super.key, required this.elderId, this.fetch, this.save});

  @override
  State<ElderCallTimeCard> createState() => _ElderCallTimeCardState();
}

class _ElderCallTimeCardState extends State<ElderCallTimeCard> {
  String? _value; // 서버가 알려 준 지금 시간(HH:MM)
  Object? _loadError;
  bool _loading = true;
  bool _saving = false; // 시트를 닫은 뒤에도 저장이 끝나기 전에는 다시 열지 못하게 한다

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final value = await (widget.fetch ?? NulbomApi.callTime)(widget.elderId);
      if (!mounted) return;
      setState(() {
        _value = value;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loadError = error;
        _loading = false;
      });
    }
  }

  /// 시트가 부른다. 성공하면 카드 값을 바꾸고 알린다 — 그 사이 시트를 닫았어도 카드는 새 값을 안다.
  Future<void> _save(String hhmm) async {
    setState(() => _saving = true);
    try {
      final saved = await (widget.save ?? NulbomApi.setCallTime)(widget.elderId, hhmm);
      if (!mounted) return;
      setState(() => _value = saved);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('안부 전화 시간을 ${formatCallTime(saved)}으로 바꿨어요')),
      );
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _openSheet() async {
    final current = _value;
    if (current == null || _saving) return;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: eCard,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (_) => _CallTimeSheet(current: current, save: _save),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '안부 전화 시간',
          style: GoogleFonts.notoSansKr(
            fontSize: 18,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
        const SizedBox(height: 8),
        Container(
          width: double.infinity,
          decoration: BoxDecoration(
            color: eCard,
            border: Border.all(color: eLine),
            borderRadius: BorderRadius.circular(12),
          ),
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '하루에 한 번, 이 시간에 AI가 어르신께 전화해요.',
                style: TextStyle(fontSize: 14, color: eInkSoft, height: 1.5),
              ),
              const SizedBox(height: 12),
              _buildBody(),
              const SizedBox(height: 12),
              const Divider(height: 1, color: eLine),
              const SizedBox(height: 10),
              const Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(Icons.info_outline_rounded, size: 16, color: eInkSoft),
                  SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      '이미 지난 시간으로 바꾸면 내일부터 걸려요. 방금 지난 시간은 고를 수 없어요.',
                      style: TextStyle(fontSize: 12, color: eInkSoft, height: 1.5),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildBody() {
    final value = _value;
    if (_loading) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 8),
        child: LinearProgressIndicator(),
      );
    }
    if (_loadError != null || value == null) {
      final error = _loadError;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('불러오지 못했어요', style: TextStyle(fontSize: 14, color: eInk)),
          const SizedBox(height: 4),
          Text(
            error is ApiException ? error.message : '잠시 뒤에 다시 해 주세요.',
            style: const TextStyle(fontSize: 13, color: eInkSoft),
          ),
          TextButton(
            onPressed: _load,
            style: TextButton.styleFrom(padding: EdgeInsets.zero),
            child: const Text('다시 시도', style: TextStyle(color: eAccent)),
          ),
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          formatCallTime(value),
          style: GoogleFonts.notoSansKr(
            fontSize: 26,
            fontWeight: FontWeight.w800,
            color: eAccent,
          ),
        ),
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          height: 48,
          child: OutlinedButton(
            onPressed: _saving ? null : _openSheet,
            style: OutlinedButton.styleFrom(
              foregroundColor: eAccent,
              side: const BorderSide(color: eAccent, width: 1.5),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            ),
            child: Text(
              '시간 바꾸기',
              style: GoogleFonts.notoSansKr(fontSize: 15, fontWeight: FontWeight.w700),
            ),
          ),
        ),
      ],
    );
  }
}

/// 07:00~21:00 30분 단위 목록. 항목을 누르면 저장하고, 서버가 거절하면 그 문장을 여기 위에 보인다.
class _CallTimeSheet extends StatefulWidget {
  final String current;
  final Future<void> Function(String hhmm) save;

  const _CallTimeSheet({required this.current, required this.save});

  @override
  State<_CallTimeSheet> createState() => _CallTimeSheetState();
}

class _CallTimeSheetState extends State<_CallTimeSheet> {
  static const String _offline = '서버에 연결하지 못했어요. 잠시 뒤에 다시 해 주세요.';

  final GlobalKey _currentKey = GlobalKey();
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    // 늦은 시간(예: 오후 6시)이면 목록 아래쪽이다. 열자마자 지금 값이 보이게 끌어온다.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final target = _currentKey.currentContext;
      if (target != null) Scrollable.ensureVisible(target, alignment: 0.3);
    });
  }

  Future<void> _choose(String hhmm) async {
    if (_saving) return;
    if (hhmm == widget.current) {
      Navigator.of(context).pop(); // 바뀌는 것이 없다
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    String? error;
    try {
      await widget.save(hhmm);
    } on ApiException catch (e) {
      error = e.message;
    } catch (_) {
      error = _offline;
    }
    if (!mounted) return;
    if (error == null) {
      Navigator.of(context).pop();
      return;
    }
    setState(() {
      _saving = false;
      _error = error;
    });
  }

  @override
  Widget build(BuildContext context) {
    final error = _error;
    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.of(context).size.height * 0.75),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 20, 20, 8),
              child: Text(
                '안부 전화 시간 고르기',
                style: GoogleFonts.notoSansKr(fontSize: 18, fontWeight: FontWeight.w700, color: eInk),
              ),
            ),
            if (_saving) const LinearProgressIndicator(),
            if (error != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 4, 20, 8),
                child: Text(
                  error,
                  style: const TextStyle(fontSize: 14, color: Color(0xFFD92D20), height: 1.5),
                ),
              ),
            Flexible(
              child: ListView(
                shrinkWrap: true,
                children: [
                  for (final choice in callTimeChoices)
                    ListTile(
                      key: choice == widget.current ? _currentKey : null,
                      enabled: !_saving,
                      onTap: () => _choose(choice),
                      contentPadding: const EdgeInsets.symmetric(horizontal: 20),
                      title: Text(
                        formatCallTime(choice),
                        style: TextStyle(
                          fontSize: 16,
                          color: eInk,
                          fontWeight: choice == widget.current ? FontWeight.w700 : FontWeight.w400,
                        ),
                      ),
                      trailing: choice == widget.current
                          ? const Icon(Icons.check_rounded, color: eAccent)
                          : null,
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
