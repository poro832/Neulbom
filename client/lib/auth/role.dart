import 'package:shared_preferences/shared_preferences.dart';

/// 이 기기를 누가 쓰는가.
///
/// 정식 회원 시스템은 범위 밖이므로(설계 2장) 기기에 역할만 저장한다.
/// 계정이 생기면 `user_id`에 붙는 속성으로 승격된다.
enum AppRole {
  elder('elder'),
  guardian('guardian');

  const AppRole(this.key);
  final String key;

  static AppRole? fromKey(String? key) {
    if (key == null) return null;
    for (final role in AppRole.values) {
      if (role.key == key) return role;
    }
    return null;
  }
}

class RoleStore {
  static const _prefsKey = 'app_role';

  /// 아직 고르지 않았으면 null — 그때 역할 선택 화면을 띄운다.
  static Future<AppRole?> read() async {
    final prefs = await SharedPreferences.getInstance();
    return AppRole.fromKey(prefs.getString(_prefsKey));
  }

  static Future<void> write(AppRole role) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefsKey, role.key);
  }

  static Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_prefsKey);
  }
}
