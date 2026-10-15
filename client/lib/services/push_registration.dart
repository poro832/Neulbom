import 'dart:async';

import 'nulbom_api.dart';

/// 이 폰의 푸시 토큰을 주는 곳. 진짜(Firebase)는 단위 테스트에서 못 쓰므로 테스트에서 가짜로 바꾼다.
abstract class PushTokenSource {
  Future<String?> getToken();
  Stream<String> get onTokenRefresh;
}

/// 보호자 폰의 푸시 토큰을 서버에 등록·해제한다. 서버는 보호자 폰에만 알림을 보낸다.
/// 어떤 실패도 앱 흐름을 막지 않는다 — 조용히 넘어가고 다음 기회(앱 시작, 로그인, 토큰 갱신)에 다시 시도한다.
class PushRegistration {
  /// 시작 때 `FcmService`가 진짜로 바꿔 놓는다. 테스트에서는 가짜로 바꾼다.
  static PushTokenSource? source;

  /// 서버가 멈춰도 앱을 붙잡지 않는다.
  static const Duration _wait = Duration(seconds: 5);

  /// 마지막으로 서버에 등록한 토큰 — 로그아웃 때 해제할 대상.
  static String? _registeredToken;
  static StreamSubscription<String>? _refreshSub;

  /// 보호자 열쇠가 있을 때만(로그인한 보호자) 이 폰의 토큰을 등록한다.
  /// 어르신 폰에는 보호자 열쇠가 없으므로 아무것도 하지 않는다.
  static Future<void> registerIfGuardian() async {
    if (NulbomApi.guardianKey.isEmpty) return;
    try {
      final token = await source?.getToken().timeout(_wait);
      if (token == null || token.isEmpty) return;
      await _register(token);
    } catch (_) {
      // 토큰을 못 얻어도 괜찮다 — 다음 기회에 다시.
    }
  }

  static Future<void> _register(String token) async {
    if (NulbomApi.guardianKey.isEmpty) return;
    try {
      await NulbomApi.registerDevice(token).timeout(_wait);
      _registeredToken = token;
    } catch (_) {
      // 403(운영자 확인·이메일 인증 전)이나 네트워크 오류 — 조용히 넘기고 다음 기회에 다시 시도한다.
    }
  }

  /// 토큰이 바뀔 때마다 같은 등록을 부른다. 한 번만 걸린다.
  static void listenToRefresh() {
    if (_refreshSub != null) return;
    try {
      _refreshSub = source?.onTokenRefresh.listen(
        (token) => unawaited(_register(token)),
        onError: (_) {},
      );
    } catch (_) {}
  }

  /// 로그아웃 때 서버에서 이 폰의 토큰을 지운다(최선). 보호자 열쇠를 지우기 *전에* 불러야 한다.
  static Future<void> unregister() async {
    if (NulbomApi.guardianKey.isEmpty) return;
    try {
      final token = _registeredToken ?? await source?.getToken().timeout(_wait);
      if (token == null || token.isEmpty) return;
      await NulbomApi.unregisterDevice(token).timeout(_wait);
      _registeredToken = null;
    } catch (_) {
      // 실패해도 로그아웃은 진행한다.
    }
  }

  /// 테스트용: 기억한 상태를 비운다.
  static Future<void> resetForTest() async {
    await _refreshSub?.cancel();
    _refreshSub = null;
    _registeredToken = null;
    source = null;
  }
}
