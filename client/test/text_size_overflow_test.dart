import 'dart:convert';

import 'package:eldercare/screens/elderly_home_page.dart';
import 'package:eldercare/screens/elderly_login_screen.dart';
import 'package:eldercare/screens/elderly_signup_screen.dart';
import 'package:eldercare/screens/emergency_screen.dart';
import 'package:eldercare/screens/guardian_account_screen.dart';
import 'package:eldercare/screens/guardian_login_screen.dart';
import 'package:eldercare/screens/guardian_screen.dart';
import 'package:eldercare/screens/guardian_signup_screen.dart';
import 'package:eldercare/screens/role_selection_screen.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:eldercare/services/text_size.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 폰 폭 360dp에서 글자를 "아주 크게"(1.45배)로 두어도 글자가 넘치거나 잘리지 않는지 본다.
/// 넘치면 Flutter가 RenderFlex overflow 예외를 낸다.
final Map<String, Widget Function()> _screens = {
  '역할 선택': () => const RoleSelectionScreen(),
  '어르신 로그인': () => const ElderlyLoginScreen(),
  '어르신 가입': () => const ElderlySignupScreen(),
  '보호자 로그인': () => const GuardianLoginScreen(),
  '보호자 가입': () => const GuardianSignupScreen(),
  '어르신 홈': () => const ElderlyHomePage(name: '배주호'),
  '비상 연락': () => const EmergencyScreen(),
  '보호자 홈(어르신 있음)': () => const GuardianScreen(),
  '보호자 계정': () => const GuardianAccountScreen(),
};

http.Response _empty(http.Request request) {
  final path = request.url.path;
  if (path == '/v1/me/calls') return _json({'calls': []});
  if (path == '/v1/me/contacts') return _json({'guardians': [], 'contacts': []});
  // 보호자 홈이 어르신·주간 통계·알림을 채워 보여 주는 상태(자료가 없는 상태만 보면 넘침을 놓친다)
  if (path == '/v1/guardian/elders') {
    return _json({
      'week_start': '2026-10-04',
      'elders': [
        {
          'elder_id': 12,
          'name': '어르신 12',
          'last_call_at': null,
          'last_status': null,
          'week_calls': 2,
          'week_avg_score': 20.0,
          'week_alerts': 1,
        }
      ],
    });
  }
  if (path == '/v1/elders/12/weekly') {
    return _json({
      'week_start': '2026-10-04',
      'days': [
        for (var i = 4; i <= 10; i++)
          {'date': '2026-10-${i.toString().padLeft(2, '0')}', 'calls': i == 5 ? 1 : 0, 'avg_score': i == 5 ? 20.0 : null},
      ],
      'total_calls': 3,
      'avg_score': 20.0,
    });
  }
  if (path == '/v1/guardian/alerts') {
    return _json({
      'alerts': [
        {
          'alert_id': 1,
          'elder_id': 12,
          'elder_name': '어르신 12',
          'type': 'risk_rise',
          'severity': 'warning',
          'message': '문구',
          'created_at': '2026-10-08T10:00:00+09:00',
        }
      ],
    });
  }
  if (path == '/v1/guardian/me') {
    return _json({'name': '김보호', 'email': 'kim@example.com', 'phone': '010-1111-2222'});
  }
  return http.Response('{"detail":"x"}', 404, headers: {'content-type': 'application/json'});
}

http.Response _json(Object body) =>
    http.Response(jsonEncode(body), 200, headers: {'content-type': 'application/json; charset=utf-8'});

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({'elder_key': 'nle_saved', 'ai_friend_name': '봄이'});
    NulbomApi.guardianKey = 'nlb_test';
    NulbomApi.client = MockClient((request) async => _empty(request));
    textSizeIndex.value = 3; // 아주 크게
  });
  tearDown(() {
    textSizeIndex.value = textSizeDefaultIndex;
    NulbomApi.guardianKey = '';
  });

  testWidgets('아주 크게 + 낮은 화면(360x640, 상태바 포함): 첫 화면인 역할 선택도 넘치지 않고 보호자 카드까지 스크롤로 닿는다', (tester) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(MaterialApp(builder: textSizeBuilder, home: const RoleSelectionScreen()));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    await tester.ensureVisible(find.text('보호자'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('보호자'), findsOneWidget);
  });

  for (final entry in _screens.entries) {
    testWidgets('아주 크게 + 폭 360dp: ${entry.key} 화면이 넘치지 않는다', (tester) async {
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);

      await tester.pumpWidget(MaterialApp(builder: textSizeBuilder, home: entry.value()));
      await tester.pumpAndSettle();

      final problems = <String>[];
      Object? error;
      while ((error = tester.takeException()) != null) {
        problems.add(error.toString().split('\n').first);
      }
      expect(problems, isEmpty);
    });
  }
}
