import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../main.dart' show eAccent, eBg, eInk, eInkSoft;
import '../models/nulbom_models.dart';
import '../services/auth_service.dart';
import '../services/nulbom_api.dart';
import 'elderly_home_page.dart' show ElderlyHomePage;
import 'elderly_login_screen.dart' show ElderlyLoginScreen;

/// 어르신 홈으로 가는 문. 열 때마다 서버에 내 상태를 물어본다.
///
/// 가입만 한 어르신(승인 대기)은 보호자가 승인할 때까지 대기 화면에 머문다 — 이 상태에서는
/// 서버가 전화를 걸지 않고 통화 기록·연락처도 열어 주지 않는다. 승인됐으면 홈으로 들어간다.
class ElderlyGate extends StatefulWidget {
  const ElderlyGate({super.key, this.homeBuilder});

  /// 활성 어르신이 들어갈 홈. 기본은 어르신 홈이고, 테스트는 가벼운 화면을 넣는다.
  final WidgetBuilder? homeBuilder;

  @override
  State<ElderlyGate> createState() => _ElderlyGateState();
}

class _ElderlyGateState extends State<ElderlyGate> {
  late Future<MyStatus> _status;

  @override
  void initState() {
    super.initState();
    _status = NulbomApi.myStatus();
  }

  void _reload() {
    setState(() {
      _status = NulbomApi.myStatus();
    });
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
        if (me.status == 'active') {
          return widget.homeBuilder?.call(context) ?? const ElderlyHomePage();
        }
        return _screen(
          title: '보호자 승인을 기다리고 있어요',
          detail: '${me.name} 어르신, 보호자가 승인하면 안부 전화가 시작돼요.\n승인이 끝났다면 새로고침을 눌러 주세요.',
          retryLabel: '새로고침',
        );
      },
    );
  }

  Widget _screen({required String title, String? detail, required String retryLabel}) {
    return Scaffold(
      backgroundColor: eBg,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.hourglass_top_rounded, size: 64, color: eAccent),
                const SizedBox(height: 24),
                Text(
                  title,
                  textAlign: TextAlign.center,
                  style: GoogleFonts.notoSerifKr(
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
                const SizedBox(height: 32),
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
