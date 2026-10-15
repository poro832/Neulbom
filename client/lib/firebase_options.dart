import 'package:firebase_core/firebase_core.dart' show FirebaseOptions;

/// Firebase 프로젝트 neulbom-bc9d8 (Android 앱 com.myeongong.neulbom).
/// 값은 android/app/google-services.json과 같다. 앱은 Android만 지원하므로 다른 플랫폼 항목은 없다.
class DefaultFirebaseOptions {
  static FirebaseOptions get currentPlatform {
    return android;
  }

  static const FirebaseOptions android = FirebaseOptions(
    apiKey: 'AIzaSyBRiIPt5-jtkStnOMvyic1cjRcK3EfO0Go',
    appId: '1:425629736630:android:f53189f0e2325f39141017',
    messagingSenderId: '425629736630',
    projectId: 'neulbom-bc9d8',
    storageBucket: 'neulbom-bc9d8.firebasestorage.app',
  );
}
