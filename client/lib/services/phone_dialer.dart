import 'package:url_launcher/url_launcher.dart';

/// 폰의 전화 앱을 열고 번호를 채워 준다. 통화 버튼은 사용자가 한 번 더 눌러야 걸린다.
///
/// 앱이 바로 전화를 걸지 않는 이유: 권한(CALL_PHONE)이 필요 없고, 잘못 눌러도 119가 바로 걸리지 않는다.
/// 시험에서는 [launcher]를 바꿔 끼운다.
class PhoneDialer {
  PhoneDialer._();

  static Future<bool> Function(Uri uri) launcher = (uri) => launchUrl(uri);

  /// 번호에서 숫자와 앞의 +만 남긴다. 숫자가 없으면 null.
  static String? clean(String number) {
    final cleaned = number.replaceAll(RegExp(r'[^0-9+]'), '');
    return RegExp(r'[0-9]').hasMatch(cleaned) ? cleaned : null;
  }

  /// 전화 앱을 열었으면 true. 열지 못했거나 번호가 이상하면 false.
  static Future<bool> open(String number) async {
    final cleaned = clean(number);
    if (cleaned == null) return false;
    try {
      return await launcher(Uri(scheme: 'tel', path: cleaned));
    } catch (_) {
      return false;
    }
  }
}
