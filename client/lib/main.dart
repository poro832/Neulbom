import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:firebase_core/firebase_core.dart';

import 'auth/role.dart';
import 'auth/role_gate.dart';
import 'firebase_options.dart';
import 'screens/elder/emergency_screen.dart';
import 'screens/elder/history_screen.dart';
import 'screens/elder/main_screen.dart';
import 'screens/guardian/guardian_home_screen.dart';
import 'services/fcm_service.dart';
import 'theme/app_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Firebase 설정이 아직 이 프로젝트 것으로 바뀌지 않았어도 앱은 떠야 한다.
  // 알림만 빠지고 나머지 화면은 그대로 개발할 수 있다.
  try {
    await Firebase.initializeApp(
      options: DefaultFirebaseOptions.currentPlatform,
    );
    await FcmService.init();
    FcmService.listenToTokenRefresh();
  } catch (error) {
    debugPrint('Firebase 초기화를 건너뜁니다: $error');
  }

  runApp(const AnsimCareApp());
}

class AnsimCareApp extends StatelessWidget {
  const AnsimCareApp({super.key});

  /// 어르신이 쓰는 앱이라 날짜 선택기·텍스트 선택 메뉴 같은 Material 기본
  /// 문자열까지 한국어여야 한다. 기기 언어가 영어여도 한국어로 떨어지도록
  /// 지원 로케일을 하나만 둔다.
  static const List<Locale> supportedLocales = [Locale('ko', 'KR')];

  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates = [
    GlobalMaterialLocalizations.delegate,
    GlobalWidgetsLocalizations.delegate,
    GlobalCupertinoLocalizations.delegate,
  ];

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '늘봄',
      theme: buildAppTheme(context),
      locale: supportedLocales.first,
      supportedLocales: supportedLocales,
      localizationsDelegates: localizationsDelegates,
      home: const RoleRouter(),
      debugShowCheckedModeBanner: false,
    );
  }
}

/// 한 앱을 어르신과 보호자가 함께 쓴다.
///
/// 첫 실행에서 역할을 한 번 고르면 기기에 저장되고, 다음부터는 곧바로
/// 해당 화면으로 들어간다. 정식 계정 시스템은 범위 밖이므로(설계 2장)
/// 로그인 대신 이 한 단계만 둔다.
class RoleRouter extends StatefulWidget {
  const RoleRouter({super.key});

  @override
  State<RoleRouter> createState() => _RoleRouterState();
}

class _RoleRouterState extends State<RoleRouter> {
  AppRole? _role;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    final saved = await RoleStore.read();
    if (!mounted) return;
    setState(() {
      _role = saved;
      _loading = false;
    });
  }

  Future<void> _choose(AppRole role) async {
    await RoleStore.write(role);
    if (!mounted) return;
    setState(() => _role = role);
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator(color: eAccent)),
      );
    }
    return switch (_role) {
      null => RoleGate(onSelected: _choose),
      AppRole.elder => const ElderShell(),
      AppRole.guardian => const GuardianShell(),
    };
  }
}

/// 어르신용. 이전 프로젝트에서 가져온 화면들을 그대로 쓴다.
class ElderShell extends StatefulWidget {
  const ElderShell({super.key});

  @override
  State<ElderShell> createState() => _ElderShellState();
}

class _ElderShellState extends State<ElderShell> {
  int _index = 0;

  static const _screens = [
    MainScreen(),
    HistoryScreen(),
    EmergencyScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: _screens[_index],
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _index,
        onTap: (index) => setState(() => _index = index),
        backgroundColor: eCard,
        selectedItemColor: eAccent,
        unselectedItemColor: eInkSoft,
        type: BottomNavigationBarType.fixed,
        // 어르신 화면은 글자를 키운다.
        selectedFontSize: 15,
        unselectedFontSize: 15,
        iconSize: 28,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.home), label: '홈'),
          BottomNavigationBarItem(icon: Icon(Icons.history), label: '통화기록'),
          BottomNavigationBarItem(icon: Icon(Icons.emergency), label: '비상연락'),
        ],
      ),
    );
  }
}

/// 보호자용. 지금은 홈 하나지만 알림·설정이 붙을 자리를 남겨 둔다.
class GuardianShell extends StatelessWidget {
  const GuardianShell({super.key});

  @override
  Widget build(BuildContext context) {
    return const GuardianHomeScreen();
  }
}
