import 'package:firebase_messaging/firebase_messaging.dart';
import 'api_service.dart';

class FcmService {
  static final FirebaseMessaging _firebaseMessaging =
      FirebaseMessaging.instance;

  static Future<void> init() async {
    try {
      // 권한 요청
      NotificationSettings settings = await _firebaseMessaging.requestPermission(
        alert: true,
        badge: true,
        sound: true,
        provisional: false,
      );

      print('FCM 권한: ${settings.authorizationStatus}');

      // FCM 토큰 가져오기
      String? token = await _firebaseMessaging.getToken();
      if (token != null) {
        print('FCM Token: $token');
        // 백엔드에 토큰 등록
        await ApiService.registerFcmToken(token);
      }

      // 포그라운드 메시지 수신
      FirebaseMessaging.onMessage.listen(
        (RemoteMessage message) {
          print('포그라운드 메시지 수신: ${message.notification?.title}');
          _handleMessage(message);
        },
      );

      // 백그라운드에서 메시지 수신했을 때 앱 열기
      FirebaseMessaging.onMessageOpenedApp.listen(
        (RemoteMessage message) {
          print('알림으로 앱 열림: ${message.notification?.title}');
          _handleMessage(message);
        },
      );

      // 종료된 상태에서 메시지로 앱 시작
      RemoteMessage? initialMessage =
          await _firebaseMessaging.getInitialMessage();
      if (initialMessage != null) {
        print('초기 메시지: ${initialMessage.notification?.title}');
        _handleMessage(initialMessage);
      }

      print('FCM 초기화 완료');
    } catch (e) {
      print('FCM 초기화 실패: $e');
    }
  }

  static void _handleMessage(RemoteMessage message) {
    print('메시지 처리:');
    print('제목: ${message.notification?.title}');
    print('본문: ${message.notification?.body}');
    print('데이터: ${message.data}');

    // TODO: 여기에 알림 처리 로직 추가
    // - 화면 네비게이션
    // - 로컬 알림 표시
    // - 데이터 저장 등
  }

  // 토큰 갱신 리스너
  static void listenToTokenRefresh() {
    _firebaseMessaging.onTokenRefresh.listen((String newToken) {
      print('FCM 토큰 갱신: $newToken');
      ApiService.registerFcmToken(newToken);
    });
  }

  // FCM 구독 (토픽별)
  static Future<void> subscribeToTopic(String topic) async {
    try {
      await _firebaseMessaging.subscribeToTopic(topic);
      print('토픽 구독: $topic');
    } catch (e) {
      print('토픽 구독 실패: $e');
    }
  }

  // FCM 구독 해제
  static Future<void> unsubscribeFromTopic(String topic) async {
    try {
      await _firebaseMessaging.unsubscribeFromTopic(topic);
      print('토픽 구독 해제: $topic');
    } catch (e) {
      print('토픽 구독 해제 실패: $e');
    }
  }
}
