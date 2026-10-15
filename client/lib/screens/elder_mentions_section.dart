import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../main.dart' show eAccent, eCard, eInk, eInkSoft, eLine;
import '../models/nulbom_models.dart';
import '../services/nulbom_api.dart';

/// 보호자: 어르신이 통화에서 직접 하신 건강·기분 이야기를 한 주씩 모아 보여 준다.
///
/// 서버는 통화 기록의 어르신이 한 번에 말씀하신 말을 그대로 저장한다. 이 구역은 그 말을 옮길 뿐 판단하지 않는다 —
/// 그래서 "진단이 아니에요" 안내가 늘 함께 보인다.
class ElderMentionsSection extends StatefulWidget {
  final int elderId;

  /// 테스트에서 바꾼다. 기본은 [NulbomApi.elderMentions].
  final Future<ElderMentions> Function(int elderId, {String? weekStart})? fetch;

  /// 테스트에서 바꾼다. 기본은 [DateTime.now].
  final DateTime Function()? now;

  const ElderMentionsSection({super.key, required this.elderId, this.fetch, this.now});

  @override
  State<ElderMentionsSection> createState() => _ElderMentionsSectionState();
}

class _ElderMentionsSectionState extends State<ElderMentionsSection> {
  static const int _maxWeeksBack = 4;

  int _weeksBack = 0; // 0이면 이번 주, 1이면 한 주 전 …
  late Future<ElderMentions> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<ElderMentions> _load() {
    final fetch = widget.fetch ?? NulbomApi.elderMentions;
    // 이번 주는 서버가 정한다(서버의 오늘 기준). 지난 주만 날짜를 보낸다.
    if (_weeksBack == 0) return fetch(widget.elderId);
    return fetch(widget.elderId, weekStart: _dateKey(_shownWeekStart()));
  }

  /// 지금 보는 주의 일요일. 오늘이 속한 주의 일요일에서 `7 * _weeksBack`일 앞이다.
  DateTime _shownWeekStart() {
    final today = (widget.now ?? DateTime.now)();
    // 날짜 생성자로 빼서 서머타임이 있는 시간대에서도 자정이 밀리지 않게 한다.
    return DateTime(today.year, today.month, today.day - today.weekday % 7 - 7 * _weeksBack);
  }

  static String _dateKey(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  void _show(int weeksBack) {
    setState(() {
      _weeksBack = weeksBack;
      _future = _load();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildHeader(),
        const SizedBox(height: 8),
        Container(
          width: double.infinity,
          decoration: BoxDecoration(
            color: eCard,
            border: Border.all(color: eLine),
            borderRadius: BorderRadius.circular(12),
          ),
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              FutureBuilder<ElderMentions>(
                future: _future,
                builder: (context, snapshot) {
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const Padding(
                      padding: EdgeInsets.symmetric(vertical: 8),
                      child: LinearProgressIndicator(),
                    );
                  }
                  if (snapshot.hasError) return _buildError(snapshot.error);
                  return _buildBody(snapshot.data!);
                },
              ),
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
                      '어르신이 통화에서 하신 말을 그대로 옮긴 것이에요. 진단이 아니에요.',
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

  Widget _buildHeader() {
    return Row(
      children: [
        Expanded(
          child: Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 8,
            children: [
              Text(
                '이번 주 어르신이 말씀하신 것',
                style: GoogleFonts.notoSansKr(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: eInk,
                ),
              ),
              if (_weeksBack > 0)
                Text('$_weeksBack주 전', style: const TextStyle(fontSize: 13, color: eInkSoft)),
            ],
          ),
        ),
        if (_weeksBack < _maxWeeksBack)
          TextButton(
            onPressed: () => _show(_weeksBack + 1),
            style: TextButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 8)),
            child: const Text('이전 주', style: TextStyle(color: eAccent)),
          ),
        if (_weeksBack > 0)
          TextButton(
            onPressed: () => _show(_weeksBack - 1),
            style: TextButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 8)),
            child: const Text('다음 주', style: TextStyle(color: eAccent)),
          ),
      ],
    );
  }

  Widget _buildError(Object? error) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('불러오지 못했어요.', style: TextStyle(fontSize: 14, color: eInk)),
        const SizedBox(height: 4),
        Text(
          error is ApiException ? error.message : '잠시 뒤에 다시 해 주세요.',
          style: const TextStyle(fontSize: 13, color: eInkSoft),
        ),
        TextButton(
          onPressed: () => _show(_weeksBack),
          style: TextButton.styleFrom(padding: EdgeInsets.zero),
          child: const Text('다시 시도', style: TextStyle(color: eAccent)),
        ),
      ],
    );
  }

  Widget _buildBody(ElderMentions mentions) {
    const plain = TextStyle(fontSize: 14, color: eInkSoft);
    if (!mentions.shareAgreed) {
      return const Text('어르신이 동의한 뒤에 볼 수 있어요.', style: plain);
    }
    final spoken = mentions.categories.where((c) => c.total > 0).toList();
    if (spoken.isEmpty) {
      final when = _weeksBack == 0 ? '이번 주에는' : '이 주에는';
      return Text('$when 어르신이 말씀하신 내용이 아직 없어요.', style: plain);
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [for (final category in spoken) _buildCategory(category)],
    );
  }

  Widget _buildCategory(MentionCategory category) {
    final counts = [
      if (category.negative > 0) '안 좋다 ${category.negative}',
      if (category.neutral > 0) '보통 ${category.neutral}',
      if (category.positive > 0) '좋다 ${category.positive}',
    ].join(' · ');
    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      childrenPadding: const EdgeInsets.only(bottom: 8),
      shape: const Border(),
      collapsedShape: const Border(),
      iconColor: eAccent,
      collapsedIconColor: eInkSoft,
      expandedCrossAxisAlignment: CrossAxisAlignment.start,
      title: Text(
        category.label,
        style: GoogleFonts.notoSansKr(fontSize: 15, fontWeight: FontWeight.w700, color: eInk),
      ),
      subtitle: Text(counts, style: const TextStyle(fontSize: 13, color: eInkSoft)),
      children: [for (final item in category.items) _buildItem(item)],
    );
  }

  Widget _buildItem(MentionItem item) {
    final feeling = switch (item.said) {
      'bad' => '안 좋다고 하셨어요',
      'ok' => '보통이라고 하셨어요',
      'good' => '좋다고 하셨어요',
      _ => null,
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 44,
            child: Text(
              '${item.date.month}/${item.date.day}',
              style: const TextStyle(fontSize: 13, color: eInkSoft, height: 1.5),
            ),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '“${item.quote}”',
                  style: const TextStyle(fontSize: 15, color: eInk, height: 1.5),
                ),
                if (feeling != null) ...[
                  const SizedBox(height: 2),
                  Text(feeling, style: const TextStyle(fontSize: 12, color: eInkSoft)),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}
