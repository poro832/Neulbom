import 'dart:convert';

import 'package:eldercare/models/nulbom_models.dart' show ChatAnswer;
import 'package:eldercare/screens/ai_chat_screen.dart';
import 'package:eldercare/screens/elder_calls_screen.dart';
import 'package:eldercare/screens/elderly_detail_screen.dart';
import 'package:eldercare/screens/elderly_home_page.dart';
import 'package:eldercare/screens/elderly_login_screen.dart';
import 'package:eldercare/screens/elderly_management_screen.dart';
import 'package:eldercare/screens/elderly_signup_screen.dart';
import 'package:eldercare/screens/email_verification_screen.dart';
import 'package:eldercare/screens/emergency_screen.dart';
import 'package:eldercare/screens/guardian_account_screen.dart';
import 'package:eldercare/screens/guardian_login_screen.dart';
import 'package:eldercare/screens/guardian_screen.dart';
import 'package:eldercare/screens/guardian_signup_screen.dart';
import 'package:eldercare/screens/health_alerts_screen.dart';
import 'package:eldercare/screens/history_screen.dart';
import 'package:eldercare/screens/password_reset_screen.dart';
import 'package:eldercare/screens/role_selection_screen.dart';
import 'package:eldercare/screens/splash_screen.dart';
import 'package:eldercare/screens/text_size_sheet.dart';
import 'package:eldercare/screens/chat_widgets.dart';
import 'package:eldercare/services/nulbom_api.dart';
import 'package:eldercare/services/text_size.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Response _json(Object body, [int s = 200]) => http.Response(
  jsonEncode(body),
  s,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

String dk(DateTime d) =>
    '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

http.Response _server(http.Request r) {
  final p = r.url.path;
  if (p == '/v1/me/calls') {
    return _json({
      'calls': [
        {
          'call_id': 2,
          'started_at': '2026-10-06T09:00:00+09:00',
          'duration_s': null,
          'status': 'no_answer',
        },
        {
          'call_id': 1,
          'started_at': '2026-10-05T09:00:00+09:00',
          'duration_s': 125,
          'status': 'completed',
        },
      ],
    });
  }
  if (p == '/v1/me/contacts') {
    return _json({
      'guardians': [
        {'name': '김보호자이름길게', 'relation': '아들', 'phone': '010-1234-5678'},
      ],
      'contacts': [
        {
          'contact_id': 3,
          'name': '이웃집 할머니',
          'relation': '이웃',
          'phone': '010-9999-8888',
        },
      ],
    });
  }
  if (p == '/v1/guardian/me') {
    return _json({
      'name': '김보호',
      'email': 'kimguardian.long@example.com',
      'phone': '010-1111-2222',
    });
  }
  if (p == '/v1/guardian/elders') {
    return _json({
      'week_start': '2026-10-04',
      'elders': [
        {
          'elder_id': 12,
          'name': '어르신 홍길동',
          'last_call_at': '2026-10-08T09:00:00+09:00',
          'last_status': 'completed',
          'week_calls': 2,
          'week_avg_score': 45.0,
          'week_alerts': 1,
          'status': 'active',
          'phone': '010-1111-2222',
          'guardian_count': 2,
        },
        {
          'elder_id': 13,
          'name': '대기중',
          'last_call_at': null,
          'last_status': null,
          'week_calls': 0,
          'week_avg_score': null,
          'week_alerts': 0,
          'status': 'pending',
          'phone': '010-1111-3333',
          'guardian_count': 1,
        },
      ],
    });
  }
  if (p == '/v1/guardian/alerts') {
    return _json({
      'alerts': [
        {
          'alert_id': 1,
          'elder_id': 12,
          'elder_name': '어르신 홍길동',
          'type': 'risk_rise',
          'severity': 'critical',
          'message': '최근 통화에서 평소와 많이 달랐어요.',
          'created_at': DateTime.now().toIso8601String(),
        },
      ],
    });
  }
  final m = RegExp(r'^/v1/elders/(\d+)/(\w[\w-]*)$').firstMatch(p);
  if (m != null) {
    final kind = m.group(2);
    if (kind == 'call-time') return _json({'call_time': '18:30'});
    if (kind == 'calls') {
      return _json({
        'share_agreed': true,
        'calls': [
          {
            'call_id': 5,
            'started_at': '2026-10-09T09:00:00+09:00',
            'duration_s': 95,
            'status': 'completed',
            'summary': '오늘은 기분이 좋으시다고 하셨어요. 점심은 드셨다고 하셨어요.',
            'has_turns': true,
          },
        ],
      });
    }
    if (kind == 'mentions') {
      return _json({
        'share_agreed': false,
        'week_start': '2026-10-04',
        'categories': [],
      });
    }
    if (kind == 'weekly') {
      final asked = DateTime.parse(
        r.url.queryParameters['week_start'] ?? '2026-10-04',
      );
      final sunday = DateTime(
        asked.year,
        asked.month,
        asked.day - asked.weekday % 7,
      );
      return _json({
        'week_start': dk(sunday),
        'days': [
          for (var i = 0; i < 7; i++)
            {
              'date': dk(DateTime(sunday.year, sunday.month, sunday.day + i)),
              'calls': 1,
              'avg_score': 40.0,
            },
        ],
        'total_calls': 7,
        'avg_score': 40.0,
      });
    }
    if (kind == 'monthly') {
      final month = r.url.queryParameters['month'] ?? '2026-10';
      final y = int.parse(month.substring(0, 4));
      final mo = int.parse(month.substring(5, 7));
      final len = DateTime(y, mo + 1, 0).day;
      return _json({
        'month': month,
        'days': [
          for (var d = 1; d <= len; d++)
            {
              'date': '$month-${d.toString().padLeft(2, '0')}',
              'calls': 1,
              'avg_score': 40.0,
            },
        ],
        'total_calls': len,
        'avg_score': 40.0,
      });
    }
  }
  return _json({'detail': 'x'}, 404);
}

final Map<String, Widget Function()> screens = {
  '역할 선택': () => const RoleSelectionScreen(),
  '어르신 로그인': () => const ElderlyLoginScreen(),
  '어르신 가입': () => const ElderlySignupScreen(),
  '보호자 로그인': () => const GuardianLoginScreen(),
  '보호자 가입': () => const GuardianSignupScreen(),
  '어르신 홈': () => const ElderlyHomePage(name: '배주호'),
  '비상 연락(데이터)': () => const EmergencyScreen(),
  '보호자 홈(데이터)': () => const GuardianScreen(),
  '보호자 계정(데이터)': () => const GuardianAccountScreen(),
  '통화기록(어르신)': () => const HistoryScreen(),
  '어르신 상세': () => ElderlyDetailScreen(
    elderlyId: 20,
    elderlyName: '홍길동',
    now: () => DateTime(2026, 10, 10, 12),
  ),
  '어르신 관리': () => const ElderlyManagementScreen(),
  '건강 알림 0': () =>
      const HealthAlertsScreen(initialTabIndex: 0, elderName: '어르신 홍길동'),
  '건강 알림 1': () => const HealthAlertsScreen(initialTabIndex: 1),
  '건강 알림 2': () => const HealthAlertsScreen(initialTabIndex: 2),
  '통화 목록': () => const ElderCallsScreen(elderId: 12, elderName: '어르신 홍길동'),
  '비번 재설정': () => const PasswordResetScreen(),
  '이메일 인증': () =>
      const EmailVerificationScreen(email: 'kimguardian.long@example.com'),
  '소개': () => const SplashScreen(),
  'AI 채팅': () => AiChatScreen(
    friendName: '늘봄이',
    send: (_) async => const ChatAnswer(reply: '네', urgent: false),
    loadSessions: () async => [],
  ),
  '글자 창': () => Builder(
    builder: (context) => Scaffold(
      body: Center(
        child: ElevatedButton(
          onPressed: () => showTextSizeSheet(context),
          child: const Text('open'),
        ),
      ),
    ),
  ),
  '채팅 설정 창': () => Builder(
    builder: (context) => Scaffold(
      body: Center(
        child: ElevatedButton(
          onPressed: () => showChatSettingsSheet(
            context,
            language: 'en',
            onLanguage: (_) {},
          ),
          child: const Text('open'),
        ),
      ),
    ),
  ),
};

void main() {
  for (final cfg in [
    (idx: 1, sys: 1.0, h: 800.0, label: '1.0x 360x800'),
    (idx: 3, sys: 1.0, h: 800.0, label: '1.45x 360x800'),
    (idx: 3, sys: 1.3, h: 800.0, label: '1.8x 360x800'),
    (idx: 3, sys: 1.0, h: 640.0, label: '1.45x 360x640'),
  ]) {
    group(cfg.label, () {
      setUp(() {
        GoogleFonts.config.allowRuntimeFetching = false;
        SharedPreferences.setMockInitialValues({
          'elder_key': 'nle_saved',
          'ai_friend_name': '봄이',
        });
        NulbomApi.guardianKey = 'nlb_test';
        NulbomApi.client = MockClient((request) async => _server(request));
        textSizeIndex.value = cfg.idx;
      });
      tearDown(() {
        textSizeIndex.value = textSizeDefaultIndex;
        NulbomApi.guardianKey = '';
      });
      for (final e in screens.entries) {
        testWidgets(e.key, (tester) async {
          tester.view.physicalSize = Size(360, cfg.h);
          tester.view.devicePixelRatio = 1.0;
          tester.platformDispatcher.textScaleFactorTestValue = cfg.sys;
          addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
          addTearDown(tester.view.resetPhysicalSize);
          await tester.pumpWidget(
            MaterialApp(builder: textSizeBuilder, home: e.value()),
          );
          await tester.pump(const Duration(milliseconds: 500));
          await tester.pump(const Duration(seconds: 3));
          if (find.text('open').evaluate().isNotEmpty) {
            await tester.tap(find.text('open'));
            await tester.pump(const Duration(seconds: 1));
          }
          final problems = <String>[];
          Object? error;
          void collect(String where) {
            while ((error = tester.takeException()) != null) {
              problems.add('$where: ${error.toString().split('\n').first}');
            }
          }

          collect('열자마자');
          // 어르신 홈은 아래 탭과 ... 메뉴도 열어 본다
          if (e.key == '어르신 홈') {
            for (final tab in ['통화기록', '비상연락']) {
              await tester.tap(find.text(tab).last);
              await tester.pump(const Duration(seconds: 1));
              collect(tab);
            }
            await tester.tap(find.text('홈').last);
            await tester.pump(const Duration(seconds: 1));
            await tester.tap(find.byIcon(Icons.more_horiz_rounded));
            await tester.pump(const Duration(seconds: 1));
            collect('... 메뉴');
          }
          expect(problems, isEmpty, reason: '${cfg.label} ${e.key}');
        });
      }
    });
  }
}
