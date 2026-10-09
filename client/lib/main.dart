import 'package:flutter/material.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'firebase_options.dart';
import 'services/fcm_service.dart';
import 'services/auth_service.dart';
import 'screens/role_selection_screen.dart';
import 'screens/elderly_login_screen.dart';
import 'screens/elderly_gate.dart';
import 'screens/guardian_home_page.dart';

// 어르신 앱 색상
const Color eBg = Color(0xFFFBF6ED);
const Color eBg2 = Color(0xFFF3E7D3);
const Color eCard = Color(0xFFFFFDF8);
const Color eInk = Color(0xFF3B2F26);
const Color eInkSoft = Color(0xFF93816D);
const Color eLine = Color(0xFFEADFC9);
const Color eAccent = Color(0xFFD97B4F);
const Color eAccentSoft = Color(0xFFFBE4D3);
const Color eBrass = Color(0xFFB78A4A);

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
          headlineSmall: GoogleFonts.notoSerifKr(
            fontSize: 24,
            fontWeight: FontWeight.w700,
            color: eInk,
          ),
          titleLarge: GoogleFonts.notoSerifKr(
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
