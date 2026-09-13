import 'package:firebase_core/firebase_core.dart' show FirebaseOptions;

class DefaultFirebaseOptions {
  static FirebaseOptions get currentPlatform {
    return android;
  }

  static const FirebaseOptions android = FirebaseOptions(
    apiKey: 'AIzaSyC_lGoFyCqvBYpQ4moFh4UPNd_mJpct89A',
    appId: '1:949008118383:android:594d76b8a9cdfc75ce939a',
    messagingSenderId: '949008118383',
    projectId: 'elder-care-app-4d011',
    storageBucket: 'elder-care-app-4d011.firebasestorage.app',
  );

  static const FirebaseOptions ios = FirebaseOptions(
    apiKey: 'AIzaSyC_lGoFyCqvBYpQ4moFh4UPNd_mJpct89A',
    appId: '1:949008118383:ios:',
    messagingSenderId: '949008118383',
    projectId: 'elder-care-app-4d011',
    storageBucket: 'elder-care-app-4d011.firebasestorage.app',
  );

  static const FirebaseOptions web = FirebaseOptions(
    apiKey: 'AIzaSyC_lGoFyCqvBYpQ4moFh4UPNd_mJpct89A',
    appId: '1:949008118383:web:',
    messagingSenderId: '949008118383',
    projectId: 'elder-care-app-4d011',
    storageBucket: 'elder-care-app-4d011.firebasestorage.app',
  );
}
