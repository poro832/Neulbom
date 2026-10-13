import 'package:flutter/material.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'firebase_options.dart';
import 'services/fcm_service.dart';
import 'services/auth_service.dart';
import 'services/nulbom_api.dart';
import 'screens/role_selection_screen.dart';
import 'screens/elderly_login_screen.dart';
import 'screens/elderly_gate.dart';
import 'screens/guardian_home_page.dart';
import 'screens/guardian_login_screen.dart';

// 어르신 앱 색상
const Color eBg = Color(0xFFEFF6FF);
const Color eBg2 = Color(0xFFE5F0FF);
const Color eCard = Color(0xFFFFFFFF);
const Color eInk = Color(0xFF0E2548);
const Color eInkSoft = Color(0xFF3C5C8C);
const Color eLine = Color(0xFFD6E4FF);
const Color eAccent = Color(0xFF1A6BFF);
const Color eAccentSoft = Color(0xFFE6F0FF);
const Color eBrass = Color(0xFFFFC21A);

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Firebase 설정이 이 프로젝트 것이 아니어도 앱은 떠야 한다. 알림만 빠진다.
  try {
    await Firebase.initializeApp(
      options: DefaultFirebaseOptions.currentPlatform,
    );

    // FCM 초기화
    await FcmService.init();
    FcmService.listenToTokenRefresh();
  } catch (error) {
    debugPrint('Firebase 초기화를 건너뜁니다: $error');
  }

  runApp(const ElderCareApp());
}

class ElderCareApp extends StatefulWidget {
  const ElderCareApp({super.key});

  @override
  State<ElderCareApp> createState() => _ElderCareAppState();
}

class _ElderCareAppState extends State<ElderCareApp> {
  late Future<Widget> _homeScreen;

  @override
  void initState() {
    super.initState();
    _homeScreen = _determineHomeScreen();
  }

  Future<Widget> _determineHomeScreen() async {
    final isLoggedIn = await AuthService.isLoggedIn();
    final userType = await AuthService.getUserType();

    if (isLoggedIn && userType != null) {
      if (userType == 'elderly') {
        return const ElderlyGate();
      } else if (userType == 'guardian') {
        // 이 폰 열쇠가 없으면(옛 가짜 로그인 등) 다시 로그인해야 한다.
        if ((await NulbomApi.loadGuardianKey()).isEmpty) {
          return const GuardianLoginScreen();
        }
        return const GuardianHomePage();
      }
    }

    // 로그인되지 않았으면 역할 선택 화면으로
    return const RoleSelectionScreen();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '늘봄',
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: eBg,
        colorScheme: ColorScheme.fromSeed(
          seedColor: eAccent,
          brightness: Brightness.light,
        ),
        textTheme: GoogleFonts.notoSansKrTextTheme(
          Theme.of(context).textTheme,
        ).copyWith(
          headlineSmall: GoogleFonts.notoSansKr(
            fontSize: 24,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
          titleLarge: GoogleFonts.notoSansKr(
            fontSize: 21,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
        ),
      ),
      home: FutureBuilder<Widget>(
        future: _homeScreen,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.done) {
            return snapshot.data ?? const ElderlyLoginScreen();
          }
          return Scaffold(
            backgroundColor: eBg,
            body: Center(
              child: CircularProgressIndicator(
                valueColor: const AlwaysStoppedAnimation<Color>(eAccent),
              ),
            ),
          );
        },
      ),
      debugShowCheckedModeBanner: false,
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: const [
        Locale('ko', 'KR'),
        Locale('en', 'US'),
      ],
      locale: const Locale('ko', 'KR'),
    );
  }
}
