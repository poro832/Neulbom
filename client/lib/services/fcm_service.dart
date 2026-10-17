import 'dart:async';

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/widgets.dart';

import 'push_navigation.dart';
import 'push_registration.dart';

/// 진짜 Firebase에서 이 폰의 푸시 토큰을 얻는다.
class FirebasePushTokenSource implements PushTokenSource {
  @override
  Future<String?> getToken() => FirebaseMessaging.instance.getToken();

  @override
  Stream<String> get onTokenRefresh => FirebaseMessaging.instance.onTokenRefresh;
}

/// 진짜 Firebase에서 푸시 메시지를 받아 단순 맵으로 바꿔 준다.
class FirebasePushMessageSource implements PushMessageSource {
  static Map<String, String> _simplify(RemoteMessage message) {
    final map = <String, String>{};
    message.data.forEach((k, v) => map[k] = '$v');
    final body = message.notification?.body;
    if (body != null) map['body'] = body;
    return map;
  }

  @override
  Stream<Map<String, String>> get onForeground =>
      FirebaseMessaging.onMessage.map(_simplify);

  @override
  Stream<Map<String, String>> get onOpened =>
      FirebaseMessaging.onMessageOpenedApp.map(_simplify);

  @override
  Future<Map<String, String>?> initialMessage() async {
    final m = await FirebaseMessaging.instance.getInitialMessage();
    return m == null ? null : _simplify(m);
  }
}

class FcmService {
  static final FirebaseMessaging _firebaseMessaging =
      FirebaseMessaging.instance;

  static PushNavigation? _navigation;

  /// 알림 권한을 묻고 수신 리스너를 건다. 토큰 등록은 여기서 하지 않는다 —
  /// 로그인한 보호자 폰만 등록하므로 `PushRegistration`이 앱 시작·로그인 때 맡는다.
  /// [navigatorKey]를 주면 알림을 눌렀을 때 해당 어르신 화면으로 이동한다.
  static Future<void> init({GlobalKey<NavigatorState>? navigatorKey}) async {
    PushRegistration.source = FirebasePushTokenSource();
    try {
      NotificationSettings settings = await _firebaseMessaging.requestPermission(
        alert: true,
        badge: true,
        sound: true,
        provisional: false,
      );
      debugPrint('FCM 권한: ${settings.authorizationStatus}');

      if (navigatorKey != null) {
        await _navigation?.dispose();
        _navigation = PushNavigation(
          source: FirebasePushMessageSource(),
          navigatorKey: navigatorKey,
        );
        // 기다리지 않는다: 앱이 꺼진 채 알림으로 열렸다면 화면이 뜰 때까지 기다리는 일이라
        // 여기서 막으면 runApp이 영영 시작하지 못한다.
        unawaited(_navigation!.start().catchError((Object e) {
          debugPrint('푸시 이동 시작 실패: $e');
        }));
      }
    } catch (e) {
      debugPrint('FCM 초기화 실패: $e');
    }
  }

  // 토큰이 바뀌면 서버에 다시 등록한다(로그인한 보호자 폰만).
  static void listenToTokenRefresh() {
    PushRegistration.listenToRefresh();
  }
}
