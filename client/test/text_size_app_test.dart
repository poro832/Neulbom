import 'package:eldercare/services/text_size.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 앱 맨 위 배율이 화면 안에서 어떻게 보이는지 — 화면 안의 글자 배율로 확인한다.
Future<double> _scaleSeenBy(WidgetTester tester, {required int index, double system = 1.0}) async {
  tester.platformDispatcher.textScaleFactorTestValue = system;
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
  textSizeIndex.value = index;
  late double seen;
  await tester.pumpWidget(MaterialApp(
    builder: textSizeBuilder,
    home: Builder(builder: (context) {
      seen = MediaQuery.textScalerOf(context).scale(10) / 10;
      return const Center(child: Text('안녕하세요'));
    }),
  ));
  return seen;
}

void main() {
  tearDown(() => textSizeIndex.value = textSizeDefaultIndex);

  testWidgets('보통이면 글자가 그대로다', (tester) async {
    expect(await _scaleSeenBy(tester, index: 1), 1.0);
  });

  testWidgets('아주 크게면 1.45배다', (tester) async {
    expect(await _scaleSeenBy(tester, index: 3), closeTo(1.45, 1e-9));
  });

  testWidgets('폰 설정의 글자 크기가 커도 곱해서 1.8배를 넘지 않는다', (tester) async {
    expect(await _scaleSeenBy(tester, index: 3, system: 2.0), 1.8);
  });

  testWidgets('폰 설정이 크면 보통에서도 그만큼 커진다', (tester) async {
    expect(await _scaleSeenBy(tester, index: 1, system: 1.3), closeTo(1.3, 1e-9));
  });

  testWidgets('단계를 바꾸면 이미 떠 있는 화면의 글자가 바로 바뀐다', (tester) async {
    await _scaleSeenBy(tester, index: 1);
    final before = tester.getSize(find.text('안녕하세요')).width;

    textSizeIndex.value = 3;
    await tester.pump();
    final after = tester.getSize(find.text('안녕하세요')).width;

    expect(after, greaterThan(before * 1.3));
  });
}
