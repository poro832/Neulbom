import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import 'push_registration.dart';

/// 진짜 Firebase에서 이 폰의 푸시 토큰을 얻는다.
class FirebasePushTokenSource implements PushTokenSource {
  @override
  Future<String?> getToken() => FirebaseMessaging.instance.getToken();

  @override
  Stream<String> get onTokenRefresh => FirebaseMessaging.instance.onTokenRefresh;
}

class FcmService {
  static final FirebaseMessaging _firebaseMessaging =
      FirebaseMessaging.instance;

  /// 알림 권한을 묻고 수신 리스너를 건다. 토큰 등록은 여기서 하지 않는다 —
  /// 로그인한 보호자 폰만 등록하므로 `PushRegistration`이 앱 시작·로그인 때 맡는다.
  static Future<void> init() async {
    PushRegistration.source = FirebasePushTokenSource();
    try {
      NotificationSettings settings = await _firebaseMessaging.requestPermission(
        alert: true,
        badge: true,
        sound: true,
        provisional: false,
      );
      debugPrint('FCM 권한: ${settings.authorizationStatus}');

      FirebaseMessaging.onMessage.listen(_handleMessage);
      FirebaseMessaging.onMessageOpenedApp.listen(_handleMessage);

      final initialMessage = await _firebaseMessaging.getInitialMessage();
      if (initialMessage != null) {
        _handleMessage(initialMessage);
      }
    } catch (e) {
      debugPrint('FCM 초기화 실패: $e');
    }
  }

  // 의도적으로 처리하지 않는다: 알림 내용은 알림 목록에서 본다.
  // 화면이 켜져 있을 때 받은 알림이나 알림을 눌러 앱을 연 경우 모두 별도 동작 없이 앱만 연다.
  static void _handleMessage(RemoteMessage message) {}

  // 토큰이 바뀌면 서버에 다시 등록한다(로그인한 보호자 폰만).
  static void listenToTokenRefresh() {
    PushRegistration.listenToRefresh();
  }
}
