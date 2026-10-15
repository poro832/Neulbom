import 'package:firebase_core/firebase_core.dart' show FirebaseOptions;

/// 이 파일은 견본이다. `firebase_options.dart`로 복사해 아래 값을 채운다.
///
/// 값은 Firebase 콘솔 → 프로젝트 설정 → 일반 → 내 앱(Android: com.myeongong.neulbom)에서 받은
/// `google-services.json`의 같은 이름 항목이다. 진짜 `firebase_options.dart`는 API 키가 들어 있어
/// git에 올리지 않는다(.gitignore). 앱은 Android만 지원한다.
class DefaultFirebaseOptions {
  static FirebaseOptions get currentPlatform {
    return android;
  }

  static const FirebaseOptions android = FirebaseOptions(
    apiKey: 'YOUR_ANDROID_API_KEY', // google-services.json: client[0].api_key[0].current_key
    appId: 'YOUR_MOBILESDK_APP_ID', // client[0].client_info.mobilesdk_app_id
    messagingSenderId: 'YOUR_PROJECT_NUMBER', // project_info.project_number
    projectId: 'YOUR_PROJECT_ID', // project_info.project_id
    storageBucket: 'YOUR_PROJECT_ID.firebasestorage.app', // project_info.storage_bucket
  );
}
