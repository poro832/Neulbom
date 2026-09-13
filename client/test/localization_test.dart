import 'package:eldercare/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 어르신이 쓰는 앱이라 Flutter가 기본 제공하는 문자열까지 한국어여야 한다.
/// 우리가 쓴 한글 텍스트는 하드코딩이라 늘 한국어지만, 날짜 선택기·텍스트 선택
/// 메뉴 같은 Material 기본 문자열은 `localizationsDelegates`가 빠지면 조용히
/// 영어로 나온다. 화면에서 눈으로 확인하기 어려운 자리라 여기서 못 박는다.
void main() {
  testWidgets('Material 기본 문자열이 한국어로 나온다', (tester) async {
    late MaterialLocalizations material;
    late Locale locale;

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('ko', 'KR'),
        supportedLocales: AnsimCareApp.supportedLocales,
        localizationsDelegates: AnsimCareApp.localizationsDelegates,
        home: Builder(
          builder: (context) {
            material = MaterialLocalizations.of(context);
            locale = Localizations.localeOf(context);
            return const SizedBox.shrink();
          },
        ),
      ),
    );

    expect(locale.languageCode, 'ko');
    expect(material.cancelButtonLabel, '취소');
    expect(material.okButtonLabel, '확인');
    expect(material.searchFieldLabel, '검색');
  });

  testWidgets('앱이 한국어 로케일만 지원하도록 선언한다', (tester) async {
    expect(AnsimCareApp.supportedLocales, const [Locale('ko', 'KR')]);

    // 영어 기기로 켜도 한국어로 떨어져야 한다. supportedLocales가 하나뿐이면
    // Flutter가 그것으로 되돌린다.
    late Locale resolved;
    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en', 'US'),
        supportedLocales: AnsimCareApp.supportedLocales,
        localizationsDelegates: AnsimCareApp.localizationsDelegates,
        home: Builder(
          builder: (context) {
            resolved = Localizations.localeOf(context);
            return const SizedBox.shrink();
          },
        ),
      ),
    );
    expect(resolved.languageCode, 'ko');
  });
}
