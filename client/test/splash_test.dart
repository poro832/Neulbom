import 'dart:async';

import 'package:eldercare/screens/splash_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

const Key _next = Key('next-screen');
const Key _fallback = Key('fallback-screen');

Widget _screen(Key key) => Scaffold(key: key, body: const Text('다음 화면'));

void main() {
  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  testWidgets('소개 화면은 가운데 로고, 아래쪽 앱 이름과 짧은 문구, 그 아래 불러오는 중 표시를 보여 준다', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: SplashScreen()));
    await tester.pump(const Duration(milliseconds: 1000));

    expect(find.byKey(const Key('splash-screen')), findsOneWidget);
    expect(find.byType(NulbomMark), findsOneWidget);
    expect(find.text(kSplashName), findsOneWidget);
    expect(find.text(kSplashTagline), findsOneWidget);

    // 위에서 아래로: 로고 → 앱 이름 → 문구 → 불러오는 중 표시
    final logo = tester.getBottomLeft(find.byType(NulbomMark)).dy;
    final name = tester.getTopLeft(find.byKey(const Key('splash-name'))).dy;
    final tagline = tester.getTopLeft(find.byKey(const Key('splash-tagline'))).dy;
    final loading = tester.getTopLeft(find.byKey(const Key('splash-loading'))).dy;
    expect(name, greaterThan(logo));
    expect(tagline, greaterThan(name));
    expect(loading, greaterThan(tagline));

    // 로고는 화면 정중앙에 있고 크기도 안드로이드 시작 화면의 로고(132dp)와 같다 — 두 화면이 겹쳐 보이게.
    final screen = tester.view.physicalSize / tester.view.devicePixelRatio;
    final center = tester.getCenter(find.byType(NulbomMark));
    expect(center.dx, closeTo(screen.width / 2, 0.5));
    expect(center.dy, closeTo(screen.height / 2, 0.5));
    expect(tester.getSize(find.byType(NulbomMark)), const Size(kSplashLogoSize, kSplashLogoSize));
    expect(find.byKey(const Key('splash-loading')), findsOneWidget);
    expect(find.text('불러오는 중이에요'), findsOneWidget);
  });

  group('SplashGate', () {
    Future<void> open(WidgetTester tester, Future<Widget> destination, {Duration minimum = const Duration(milliseconds: 1600)}) {
      return tester.pumpWidget(MaterialApp(
        home: SplashGate(destination: destination, fallback: _screen(_fallback), minimum: minimum),
      ));
    }

    testWidgets('다음 화면이 일찍 정해져도 최소 시간까지는 소개 화면을 보여 준다', (tester) async {
      await open(tester, Future.value(_screen(_next)));

      await tester.pump(const Duration(milliseconds: 1000));
      expect(find.byKey(const Key('splash-screen')), findsOneWidget);
      expect(find.byKey(_next), findsNothing);

      await tester.pump(const Duration(milliseconds: 700)); // 1.7초
      await tester.pump(const Duration(milliseconds: 500)); // 바뀌는 효과
      expect(find.byKey(_next), findsOneWidget);
      expect(find.byKey(const Key('splash-screen')), findsNothing);
    });

    testWidgets('다음 화면 확인이 오래 걸리면 끝날 때까지 소개 화면에서 기다린다', (tester) async {
      final slow = Completer<Widget>();
      await open(tester, slow.future);

      await tester.pump(const Duration(seconds: 5)); // 최소 시간이 한참 지났다
      expect(find.byKey(const Key('splash-screen')), findsOneWidget);
      expect(find.byKey(_next), findsNothing);

      slow.complete(_screen(_next));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.byKey(_next), findsOneWidget);
    });

    testWidgets('다음 화면을 정하다 실패하면 대체 화면으로 간다', (tester) async {
      // 실제 앱처럼 화면이 지켜보기 시작한 뒤에 실패한다(미리 실패해 있으면 지켜보기 전에 처리되지 않은 오류가 된다).
      await open(tester, Future<Widget>.delayed(const Duration(milliseconds: 50), () => throw StateError('끊김')));

      await tester.pump(const Duration(milliseconds: 1700));
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.byKey(_fallback), findsOneWidget);
    });

    testWidgets('최소 시간을 0으로 두면 바로 다음 화면이 뜬다', (tester) async {
      await open(tester, Future.value(_screen(_next)), minimum: Duration.zero);

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.byKey(_next), findsOneWidget);
    });

    testWidgets('소개 화면을 보는 도중 화면이 닫혀도 오류 없이 끝난다', (tester) async {
      final slow = Completer<Widget>();
      await open(tester, slow.future);
      await tester.pump(const Duration(milliseconds: 300));

      await tester.pumpWidget(const SizedBox());
      slow.complete(_screen(_next)); // 닫힌 뒤에 답이 와도 안전하다
      await tester.pump(const Duration(seconds: 3));

      expect(tester.takeException(), isNull);
    });
  });
}
