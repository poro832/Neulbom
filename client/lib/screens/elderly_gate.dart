import 'dart:async';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../main.dart' show eAccent, eBg, eCard, eInk, eInkSoft, eLine;
import '../models/nulbom_models.dart';
import '../services/auth_service.dart';
import '../services/nulbom_api.dart';
import 'elderly_home_page.dart' show ElderlyHomePage;
import 'elderly_login_screen.dart' show ElderlyLoginScreen;

/// 어르신 홈으로 가는 문. 열 때마다 서버에 내 상태를 물어본다.
///
/// 먼저 가입한 어르신(연결 대기, unlinked)은 보호자가 연결 코드를 입력할 때까지, 보호자 코드로
/// 가입한 어르신(승인 대기, pending)은 보호자가 승인할 때까지 대기 화면에 머문다 — 이 상태에서는
/// 서버가 전화를 걸지 않고 통화 기록·연락처도 열어 주지 않는다. 연결·승인됐으면 홈으로 들어간다.
class ElderlyGate extends StatefulWidget {
  const ElderlyGate({
    super.key,
    this.homeBuilder,
    this.linkCode,
    this.pollInterval = const Duration(seconds: 4),
  });

  /// 연결·승인을 기다리는 동안 서버에 상태를 다시 묻는 간격. 테스트는 짧게 줄인다.
  final Duration pollInterval;

  /// 활성 어르신이 들어갈 홈. 기본은 어르신 홈이고, 테스트는 가벼운 화면을 넣는다.
  final WidgetBuilder? homeBuilder;

  /// 가입 화면이 방금 받은 연결 코드. 있으면 연결 대기 화면에 그대로 보여 준다 —
  /// 새로 받으면 보호자에게 이미 알려 준 코드를 쓸 수 없게 되므로 저절로 새로 받지 않는다.
  final PairingCode? linkCode;

  @override
  State<ElderlyGate> createState() => _ElderlyGateState();
}

class _ElderlyGateState extends State<ElderlyGate> {
  late Future<MyStatus> _status;
  bool _agreeing = false;
  String? _agreeError;
  PairingCode? _linkCode;
  bool _issuing = false;
  String? _codeError;
  Timer? _poll;

  /// 이 화면에서 연결·승인을 기다리는 모습을 본 적이 있다 — 그다음 active가 되면 "연결됐어요"를 먼저 보여 준다.
  bool _sawWaiting = false;
  bool _showConnected = false;

  @override
  void initState() {
    super.initState();
    _status = NulbomApi.myStatus();
    _linkCode = widget.linkCode;
    _poll = Timer.periodic(widget.pollInterval, (_) => _checkWaiting());
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  /// 새로고침 버튼 대신, 기다리는 동안 저절로 상태를 확인한다. 연결되면 "연결됐어요" 화면으로 바뀐다.
  Future<void> _checkWaiting() async {
    if (!_sawWaiting) return;
    try {
      final me = await NulbomApi.myStatus();
      if (!mounted || me.status != 'active') return;
      _poll?.cancel();
      setState(() {
        _showConnected = true;
        _status = Future.value(me);
      });
    } catch (_) {
      // 잠깐 끊겨도 다음 확인 때 다시 본다.
    }
  }

  /// 새 연결 코드(8자리, 24시간)를 받는다. 이전 코드는 서버에서 바로 못 쓰게 된다.
  Future<void> _issueCode() async {
    setState(() {
      _issuing = true;
      _codeError = null;
    });
    try {
      final code = await NulbomApi.issueLinkCode();
      if (!mounted) return;
      setState(() {
        _issuing = false;
        _linkCode = code;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _issuing = false;
        _codeError = _errorText(error);
      });
    }
  }

  void _reload() {
    setState(() {
      _status = NulbomApi.myStatus();
    });
  }

  Future<void> _agreeShare() async {
    setState(() {
      _agreeing = true;
      _agreeError = null;
    });
    try {
      await NulbomApi.agreeShare();
      if (!mounted) return;
      setState(() => _agreeing = false);
      _reload();
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _agreeing = false;
        _agreeError = _errorText(error);
      });
    }
  }

  Future<void> _logout() async {
    await AuthService.logout();
    if (!mounted) return;
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(builder: (context) => const ElderlyLoginScreen()),
    );
  }

  static String _errorText(Object error) =>
      error is ApiException ? error.message : '상태를 불러오지 못했어요. 잠시 뒤에 다시 해 주세요.';

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<MyStatus>(
      future: _status,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Scaffold(
            backgroundColor: eBg,
            body: Center(child: CircularProgressIndicator()),
          );
        }
        if (snapshot.hasError) {
          return _screen(
            title: _errorText(snapshot.error!),
            detail: null,
            retryLabel: '다시 시도',
          );
        }
        final me = snapshot.data!;
        if (me.status == 'active' && _showConnected) return _connectedScreen(me);
        _sawWaiting = me.status != 'active';
        if (me.status == 'active') {
          if (!me.shareAgreed) return _shareConsentScreen();
          return widget.homeBuilder?.call(context) ?? const ElderlyHomePage();
        }
        if (me.status == 'unlinked') {
          return _screen(
            title: '보호자 연결을 기다리고 있어요',
            detail: '${me.name} 어르신, 보호자에게 연결 코드를 알려 주세요.\n'
                '보호자가 코드를 입력해 연결하면 안부 전화가 시작돼요.\n연결되면 이 화면이 저절로 바뀌어요.',
            waiting: true,
            extra: _linkCodeBox(),
          );
        }
        return _screen(
          title: '보호자 승인을 기다리고 있어요',
          detail: '${me.name} 어르신, 보호자가 승인하면 안부 전화가 시작돼요.\n승인되면 이 화면이 저절로 바뀌어요.',
          waiting: true,
        );
      },
    );
  }

  /// 통화 내용 공유 안내가 생기기 전에 가입한 어르신은 한 번 더 동의해야 보호자에게 공유된다.
  /// 동의하지 않아도 안부 전화는 계속 오고, 요약·원문만 보호자에게 열리지 않는다.
  Widget _shareConsentScreen() {
    return Scaffold(
      backgroundColor: eBg,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.forum_outlined, size: 64, color: eAccent),
                const SizedBox(height: 24),
                Text(
                  '통화 내용 공유에 동의해 주세요',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.notoSansKr(
                    fontSize: 24,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  '안부 전화에서 나눈 이야기가 보호자에게 요약과 원문으로 공유돼요.\n동의하지 않으셔도 안부 전화는 계속 와요.',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.notoSansKr(fontSize: 16, height: 1.6, color: eInkSoft),
                ),
                if (_agreeError != null) ...[
                  const SizedBox(height: 12),
                  Text(
                    _agreeError!,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 14, color: Color(0xFFD92D20)),
                  ),
                ],
                const SizedBox(height: 32),
                SizedBox(
                  width: double.infinity,
                  height: 52,
                  child: ElevatedButton(
                    onPressed: _agreeing ? null : _agreeShare,
                    style: ElevatedButton.styleFrom(backgroundColor: eAccent),
                    child: const Text(
                      '동의합니다',
                      style: TextStyle(fontSize: 18, color: Colors.white),
                    ),
                  ),
                ),
                TextButton(
                  onPressed: _logout,
                  child: const Text('처음 화면으로', style: TextStyle(color: eInkSoft)),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  static String _until(DateTime time) =>
      '${time.month}월 ${time.day}일 ${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';

  /// 연결 대기 화면의 코드 칸. 코드를 보여 주고, 새 코드를 받을 수 있다.
  Widget _linkCodeBox() {
    final code = _linkCode;
    final expired = code != null && code.expiresAt.isBefore(DateTime.now());
    return Column(
      children: [
        const SizedBox(height: 24),
        if (code != null)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(vertical: 18),
            decoration: BoxDecoration(
              color: eCard,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: eLine, width: 1.5),
            ),
            child: Column(
              children: [
                SelectableText(
                  code.code,
                  textAlign: TextAlign.center,
                  style: GoogleFonts.notoSansKr(
                    fontSize: 32,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 4,
                    color: expired ? eInkSoft : eAccent,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  expired
                      ? '이 코드는 만료됐어요. 새 코드를 받아 주세요.'
                      : '${_until(code.expiresAt)}까지 쓸 수 있어요',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.notoSansKr(fontSize: 14, color: eInkSoft),
                ),
              ],
            ),
          ),
        if (_codeError != null) ...[
          const SizedBox(height: 8),
          Text(
            _codeError!,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 14, color: Color(0xFFD92D20)),
          ),
        ],
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          height: 52,
          child: OutlinedButton(
            onPressed: _issuing ? null : _issueCode,
            style: OutlinedButton.styleFrom(
              foregroundColor: eAccent,
              side: const BorderSide(color: eAccent, width: 1.5),
            ),
            child: Text(
              code == null ? '연결 코드 보기' : '새 코드 받기',
              style: const TextStyle(fontSize: 18),
            ),
          ),
        ),
        if (code != null) ...[
          const SizedBox(height: 6),
          Text(
            '새 코드를 받으면 이전 코드는 쓸 수 없어요.',
            textAlign: TextAlign.center,
            style: GoogleFonts.notoSansKr(fontSize: 13, color: eInkSoft),
          ),
        ],
      ],
    );
  }

  /// 보호자가 연결(또는 승인)한 순간. 시작하기를 누르면 어르신 홈으로 들어간다.
  Widget _connectedScreen(MyStatus me) {
    return Scaffold(
      backgroundColor: eBg,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.check_circle_rounded, size: 72, color: eAccent),
                const SizedBox(height: 24),
                Text(
                  '연결되었습니다',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.notoSansKr(
                    fontSize: 26,
                    fontWeight: FontWeight.w800,
                    color: eInk,
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  '${me.name} 어르신, 보호자와 연결됐어요.\n이제 안부 전화가 시작돼요.',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.notoSansKr(fontSize: 17, height: 1.6, color: eInkSoft),
                ),
                const SizedBox(height: 32),
                SizedBox(
                  width: double.infinity,
                  height: 56,
                  child: ElevatedButton(
                    onPressed: () => setState(() => _showConnected = false),
                    style: ElevatedButton.styleFrom(backgroundColor: eAccent),
                    child: const Text(
                      '시작하기',
                      style: TextStyle(fontSize: 19, color: Colors.white),
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

  Widget _screen({
    required String title,
    String? detail,
    String? retryLabel,
    bool waiting = false,
    Widget? extra,
  }) {
    return Scaffold(
      backgroundColor: eBg,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.hourglass_top_rounded, size: 64, color: eAccent),
                const SizedBox(height: 24),
                Text(
                  title,
                  textAlign: TextAlign.center,
                  style: GoogleFonts.notoSansKr(
                    fontSize: 24,
                    fontWeight: FontWeight.w700,
                    color: eInk,
                  ),
                ),
                if (detail != null) ...[
                  const SizedBox(height: 12),
                  Text(
                    detail,
                    textAlign: TextAlign.center,
                    style: GoogleFonts.notoSansKr(fontSize: 16, height: 1.6, color: eInkSoft),
                  ),
                ],
                ?extra,
                const SizedBox(height: 32),
                if (waiting)
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.sync_rounded, size: 18, color: eInkSoft),
                      const SizedBox(width: 8),
                      Text(
                        '연결을 기다리는 중이에요',
                        style: GoogleFonts.notoSansKr(fontSize: 15, color: eInkSoft),
                      ),
                    ],
                  ),
                if (retryLabel != null)
                  SizedBox(
                    width: double.infinity,
                    height: 52,
                    child: ElevatedButton(
                      onPressed: _reload,
                      style: ElevatedButton.styleFrom(backgroundColor: eAccent),
                      child: Text(
                        retryLabel,
                        style: const TextStyle(fontSize: 18, color: Colors.white),
                      ),
                    ),
                  ),
                TextButton(
                  onPressed: _logout,
                  child: const Text('처음 화면으로', style: TextStyle(color: eInkSoft)),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
