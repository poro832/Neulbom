import 'dart:convert';
import 'package:http/http.dart' as http;

class ApiService {
  // Android 에뮬레이터에서 PC 서버 접속: 10.0.2.2
  // 실기기에서: 172.20.10.2
  static const String baseUrl = 'http://10.0.2.2:8080';

  // 통화 내역 불러오기 (최근 10개)
  static Future<List<dynamic>> getCallHistory() async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/api/call-history/recent'),
        headers: {
          'Content-Type': 'application/json',
        },
      ).timeout(
        const Duration(seconds: 10),
        onTimeout: () => throw Exception('요청 시간 초과'),
      );

      if (response.statusCode == 200) {
        return jsonDecode(response.body);
      } else {
        throw Exception('통화 내역 불러오기 실패: ${response.statusCode}');
      }
    } catch (e) {
      print('API 에러: $e');
      rethrow;
    }
  }

  // 통화 기록 저장
  static Future<void> saveCallHistory({
    required String callerName,
    required String callerType,
    required int duration,
  }) async {
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/api/call-history'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'callerName': callerName,
          'callerType': callerType,
          'duration': duration,
          'status': 'COMPLETED',
          'timestamp': DateTime.now().toIso8601String(),
        }),
      ).timeout(
        const Duration(seconds: 10),
        onTimeout: () => throw Exception('요청 시간 초과'),
      );

      if (response.statusCode != 201 && response.statusCode != 200) {
        throw Exception('통화 기록 저장 실패: ${response.statusCode}');
      }
      print('통화 기록 저장 완료');
    } catch (e) {
      print('API 에러: $e');
      rethrow;
    }
  }

  // FCM 토큰 등록
  static Future<void> registerFcmToken(String token) async {
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/api/fcm/register'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'token': token}),
      ).timeout(
        const Duration(seconds: 10),
        onTimeout: () => throw Exception('요청 시간 초과'),
      );

      if (response.statusCode != 200 && response.statusCode != 201) {
        throw Exception('FCM 토큰 등록 실패: ${response.statusCode}');
      }
      print('FCM 토큰 등록 완료: $token');
    } catch (e) {
      print('API 에러: $e');
    }
  }

  // Mock AI 응답 데이터
  static const Map<String, String> _mockResponses = {
    '안녕': '안녕하세요! 저도 반갑습니다. 오늘은 어떤 하루를 보내셨나요?',
    '안녕하세요': '안녕하세요! 저도 반갑습니다. 오늘은 어떤 하루를 보내셨나요?',
    '하루': '네, 저도 궁금해요. 오늘 재미있었던 일이 있으신가요?',
    '건강': '건강하신 게 가장 중요합니다. 잠은 잘 주무셨나요?',
    '밥': '오늘 밥은 맛있게 드셨나요? 영양 있는 식사가 중요해요.',
    '산책': '산책은 건강에 정말 좋습니다. 날씨는 어떠신가요?',
    'family': '가족이 있어서 참 좋으시겠어요. 자주 연락하세요.',
    '손주': '손주분들이 있으면 얼마나 즐거우시겠어요!',
  };

  // AI 대화 (Mock + 실제 API 지원)
  static Future<String> chat(String message) async {
    // Mock 응답 확인
    for (var key in _mockResponses.keys) {
      if (message.contains(key)) {
        // 0.5~1초 딜레이로 자연스러움
        await Future.delayed(
          Duration(milliseconds: 500 + DateTime.now().millisecond % 500),
        );
        return _mockResponses[key]!;
      }
    }

    // 기본 Mock 응답
    final defaultResponses = [
      '그렇군요. 자세히 말씀해주실 수 있을까요?',
      '정말 그러시군요. 어떤 기분이 드세요?',
      '알겠습니다. 더 이야기해주시겠어요?',
      '그런 일도 있으셨군요. 대단하신데요?',
      '좋은 이야기네요. 앞으로도 잘 될 거예요.',
    ];

    await Future.delayed(
      Duration(milliseconds: 500 + DateTime.now().millisecond % 500),
    );
    return defaultResponses[message.length % defaultResponses.length];

    // 실제 API 연동 (백엔드 준비 후)
    /*
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/api/conversation'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'message': message}),
      ).timeout(
        const Duration(seconds: 15),
        onTimeout: () => throw Exception('요청 시간 초과'),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return data['response'] ?? '응답을 받을 수 없습니다.';
      }
      throw Exception('AI 대화 실패: ${response.statusCode}');
    } catch (e) {
      print('API 에러: $e');
      rethrow;
    }
    */
  }

  // TTS (텍스트 → 음성) - 향후 구현
  static Future<String> textToSpeech(String text) async {
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/api/tts'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'text': text}),
      ).timeout(
        const Duration(seconds: 10),
        onTimeout: () => throw Exception('요청 시간 초과'),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return data['audioUrl'] ?? '';
      }
      throw Exception('TTS 변환 실패: ${response.statusCode}');
    } catch (e) {
      print('API 에러: $e');
      rethrow;
    }
  }

  // 어르신 정보 조회
  static Future<Map<String, dynamic>> getElderInfo(String elderId) async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/api/elders/$elderId'),
        headers: {'Content-Type': 'application/json'},
      ).timeout(
        const Duration(seconds: 10),
        onTimeout: () => throw Exception('요청 시간 초과'),
      );

      if (response.statusCode == 200) {
        return jsonDecode(response.body);
      }
      throw Exception('어르신 정보 조회 실패: ${response.statusCode}');
    } catch (e) {
      print('API 에러: $e');
      rethrow;
    }
  }
}
