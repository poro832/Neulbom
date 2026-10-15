import 'package:shared_preferences/shared_preferences.dart';

import '../models/nulbom_models.dart';
import 'email_proof.dart';
import 'nulbom_api.dart';

class AuthService {
  /// 로그아웃 때 이 폰의 Firebase(이메일 인증) 세션도 끝낸다. 테스트에서 가짜로 바꾼다.
  static EmailProof emailProof = FirebaseEmailProof();

  /// Firebase 세션 끝내기를 기다리는 최대 시간 — 멈춰도 로그아웃을 붙잡지 않는다.
  static const Duration _signOutWait = Duration(seconds: 2);

  static const String _userTypeKey = 'user_type';
  static const String _phoneKey = 'phone';
  static const String _nameKey = 'name';
  static const String _isLoggedInKey = 'is_logged_in';
  static const String _tokenKey = 'auth_token';

  /// 어르신 열쇠를 받은 뒤 이 폰을 어르신 폰으로 기억한다 — 앱을 다시 열면 어르신 문(ElderlyGate)으로 간다.
  static Future<void> rememberElder({required String name, required String phone}) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_userTypeKey, 'elderly');
    await prefs.setString(_phoneKey, phone);
    await prefs.setString(_nameKey, name);
    await prefs.setBool(_isLoggedInKey, true);
  }

  // 어르신 회원가입 — 구 흐름(보호자 개인 코드로 가입). 가입 화면은 이제 보호자 코드 없이
  // NulbomApi.elderSignup으로 먼저 가입한다. 서버가 아직 이 주소를 받아 함수는 남겨 둔다.
  static Future<Map<String, dynamic>> elderlySignup({
    required String name,
    required String phone,
    required String connectionCode,
    required bool agreed,
  }) async {
    try {
      if (phone.length < 10) {
        return {'success': false, 'message': '유효한 전화번호를 입력해주세요.'};
      }

      // 서버가 코드와 전화번호를 확인하고 이 폰 전용 열쇠를 준다(성공하면 폰에 저장된다).
      await NulbomApi.signup(
        code: connectionCode.trim(),
        name: name.trim(),
        phone: phone.trim(),
        agreed: agreed,
      );
      await rememberElder(name: name, phone: phone);

      return {
        'success': true,
        'message': '회원가입 성공',
        'data': {'name': name, 'phone': phone},
      };
    } on ApiException catch (e) {
      return {'success': false, 'message': e.message};
    } catch (e) {
      return {'success': false, 'message': '서버에 연결하지 못했어요. 잠시 뒤에 다시 해 주세요.'};
    }
  }

  // 어르신 로그인 (전화번호)
  static Future<Map<String, dynamic>> elderlyLogin({
    required String phone,
  }) async {
    try {
      if (phone.length < 10) {
        return {'success': false, 'message': '유효한 전화번호를 입력해주세요.'};
      }

      if (await NulbomApi.elderKey() == null) {
        return {
          'success': false,
          'message': '이 폰은 아직 가입하지 않았어요. 처음이시면 회원가입을 해 주세요.',
        };
      }

      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_userTypeKey, 'elderly');
      await prefs.setString(_phoneKey, phone);
      await prefs.setBool(_isLoggedInKey, true);

      return {
        'success': true,
        'message': '로그인 성공',
        'data': {'phone': phone},
      };
    } catch (e) {
      return {'success': false, 'message': '로그인 실패: $e'};
    }
  }

  static const String _networkFailure = '서버에 연결하지 못했어요. 잠시 뒤에 다시 해 주세요.';

  // 보호자 회원가입 — 서버가 계정을 만들고 이 폰 전용 열쇠를 준다(앱이 저장한다)
  static Future<Map<String, dynamic>> guardianSignup({
    required String name,
    required String email,
    required String phone,
    required String password,
  }) async {
    if (!email.contains('@')) {
      return {'success': false, 'message': '유효한 이메일을 입력해주세요.'};
    }
    if (password.length < 8) {
      return {'success': false, 'message': '비밀번호는 8자 이상이어야 합니다.'};
    }
    try {
      final profile = await NulbomApi.guardianSignup(
        name: name.trim(),
        email: email.trim(),
        phone: phone.trim(),
        password: password,
      );
      await _rememberGuardian(profile);
      return {
        'success': true,
        'message': '회원가입 성공',
        'data': {
          'name': profile.name,
          'email': profile.email,
          'activated': profile.activated,
          'emailVerified': profile.emailVerified, // false면 가입 화면이 이메일 인증 화면을 연다
        },
      };
    } on ApiException catch (e) {
      return {'success': false, 'message': e.message};
    } catch (e) {
      return {'success': false, 'message': _networkFailure};
    }
  }

  // 보호자 로그인 — 서버가 이메일·비밀번호를 확인하고 열쇠를 준다
  static Future<Map<String, dynamic>> guardianLogin({
    required String email,
    required String password,
  }) async {
    try {
      final profile = await NulbomApi.guardianLogin(
        email: email.trim(),
        password: password,
      );
      await _rememberGuardian(profile);
      return {'success': true, 'message': '로그인 성공'};
    } on ApiException catch (e) {
      return {'success': false, 'message': e.message};
    } catch (e) {
      return {'success': false, 'message': _networkFailure};
    }
  }

  static Future<void> _rememberGuardian(GuardianProfile profile) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_userTypeKey, 'guardian');
    await prefs.setString(_nameKey, profile.name);
    await prefs.setString(_phoneKey, profile.phone);
    await prefs.setString('email', profile.email);
    await prefs.setBool(_isLoggedInKey, true);
  }

  // 로그아웃
  static Future<bool> logout() async {
    // 같은 폰을 다른 보호자가 쓰면 앞 사람의 Firebase 세션이 남아 있으면 안 된다(서버가 남의 증명서로 401).
    // 할 수 있는 만큼만 한다 — 실패하거나 멈춰도 로그아웃은 계속한다.
    try {
      await emailProof.signOut().timeout(_signOutWait);
    } catch (_) {}
    try {
      // 보호자면 서버에서 이 폰의 열쇠도 폐기한다. 어르신 열쇠는 건드리지 않는다.
      if (NulbomApi.guardianKey.isNotEmpty) {
        await NulbomApi.guardianLogout();
      }
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_userTypeKey);
      await prefs.remove(_phoneKey);
      await prefs.remove(_nameKey);
      await prefs.remove(_isLoggedInKey);
      await prefs.remove(_tokenKey);
      await prefs.remove('email');
      return true;
    } catch (e) {
      return false;
    }
  }

  // 로그인 상태 확인
  static Future<bool> isLoggedIn() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_isLoggedInKey) ?? false;
  }

  // 사용자 타입 확인
  static Future<String?> getUserType() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_userTypeKey);
  }

  // 사용자 정보 조회
  static Future<Map<String, String?>> getUserInfo() async {
    final prefs = await SharedPreferences.getInstance();
    return {
      'userType': prefs.getString(_userTypeKey),
      'phone': prefs.getString(_phoneKey),
      'name': prefs.getString(_nameKey),
      'email': prefs.getString('email'),
    };
  }
}
