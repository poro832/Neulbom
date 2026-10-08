import 'package:shared_preferences/shared_preferences.dart';

class AuthService {
  static const String _userTypeKey = 'user_type';
  static const String _phoneKey = 'phone';
  static const String _nameKey = 'name';
  static const String _isLoggedInKey = 'is_logged_in';
  static const String _tokenKey = 'auth_token';
  static const String _connectionCodeKey = 'connection_code';

  // Mock 연결코드 (실제로는 백엔드에서 검증)
  static const String _validConnectionCode = '123456';

  // 어르신 회원가입
  static Future<Map<String, dynamic>> elderlySignup({
    required String name,
    required String phone,
    required String connectionCode,
  }) async {
    try {
      // 연결코드 검증
      if (connectionCode != _validConnectionCode) {
        return {'success': false, 'message': '유효하지 않은 연결 코드입니다.'};
      }

      // 전화번호 중복 확인 (Mock)
      if (phone.length < 10) {
        return {'success': false, 'message': '유효한 전화번호를 입력해주세요.'};
      }

      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_userTypeKey, 'elderly');
      await prefs.setString(_phoneKey, phone);
      await prefs.setString(_nameKey, name);
      await prefs.setBool(_isLoggedInKey, true);
      await prefs.setString(_tokenKey, 'mock_token_$phone');

      return {
        'success': true,
        'message': '회원가입 성공',
        'data': {'name': name, 'phone': phone},
      };
    } catch (e) {
      return {'success': false, 'message': '회원가입 실패: $e'};
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

      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_userTypeKey, 'elderly');
      await prefs.setString(_phoneKey, phone);
      await prefs.setBool(_isLoggedInKey, true);
      await prefs.setString(_tokenKey, 'mock_token_$phone');

      return {
        'success': true,
        'message': '로그인 성공',
        'data': {'phone': phone},
      };
    } catch (e) {
      return {'success': false, 'message': '로그인 실패: $e'};
    }
  }

  // 보호자 회원가입
  static Future<Map<String, dynamic>> guardianSignup({
    required String name,
    required String email,
    required String password,
  }) async {
    try {
      if (!email.contains('@')) {
        return {'success': false, 'message': '유효한 이메일을 입력해주세요.'};
      }

      if (password.length < 6) {
        return {'success': false, 'message': '비밀번호는 6자 이상이어야 합니다.'};
      }

      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_userTypeKey, 'guardian');
      await prefs.setString(_nameKey, name);
      await prefs.setString('email', email);
      await prefs.setBool(_isLoggedInKey, true);
      await prefs.setString(_tokenKey, 'mock_token_$email');
      await prefs.setString(_connectionCodeKey, _validConnectionCode);

      return {
        'success': true,
        'message': '회원가입 성공',
        'data': {
          'connectionCode': _validConnectionCode, // 어르신에게 공유할 코드
          'name': name,
          'email': email,
        },
      };
    } catch (e) {
      return {'success': false, 'message': '회원가입 실패: $e'};
    }
  }

  // 보호자 로그인
  static Future<Map<String, dynamic>> guardianLogin({
    required String email,
    required String password,
  }) async {
    try {
      if (!email.contains('@')) {
        return {'success': false, 'message': '유효한 이메일을 입력해주세요.'};
      }

      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_userTypeKey, 'guardian');
      await prefs.setString('email', email);
      await prefs.setBool(_isLoggedInKey, true);
      await prefs.setString(_tokenKey, 'mock_token_$email');

      return {'success': true, 'message': '로그인 성공'};
    } catch (e) {
      return {'success': false, 'message': '로그인 실패: $e'};
    }
  }

  // 로그아웃
  static Future<bool> logout() async {
    try {
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
      'connectionCode':
          prefs.getString(_connectionCodeKey) ?? _validConnectionCode,
    };
  }
}
