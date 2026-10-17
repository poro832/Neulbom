import 'dart:async';

import 'package:flutter/material.dart';

import '../screens/elderly_detail_screen.dart';
import '../models/nulbom_models.dart' show ElderSummary;
import 'nulbom_api.dart';

/// 푸시 메시지 수신을 단순 맵으로 감싼 입구. 각 항목은 `{'elder_id': ..., 'body': ...}`처럼
/// 필요한 필드만 담는다. 진짜 구현은 Firebase를 쓰고, 테스트는 가짜를 쓴다.
abstract class PushMessageSource {
  /// 앱이 켜져 있을 때 받은 알림.
  Stream<Map<String, String>> get onForeground;

  /// 백그라운드에서 알림을 눌러 앱이 열린 경우.
  Stream<Map<String, String>> get onOpened;

  /// 앱이 꺼진 상태에서 알림을 눌러 앱이 시작된 경우(없으면 null).
  Future<Map<String, String>?> initialMessage();
}

/// 알림을 누르면 해당 어르신 상세 화면으로 이동하고, 앱이 켜져 있을 때는 SnackBar만 보인다.
/// 보호자로 로그인한 폰에서만 동작한다.
class PushNavigation {
  PushNavigation({
    required this.source,
    required this.navigatorKey,
    Future<List<ElderSummary>> Function()? loadElders,
    FutureOr<bool> Function()? isGuardianLoggedIn,
    this.scaffoldMessengerKey,
  })  : loadElders = loadElders ?? NulbomApi.guardianElders,
        isGuardianLoggedIn = isGuardianLoggedIn ?? _defaultLoggedIn;

  final PushMessageSource source;
  final GlobalKey<NavigatorState> navigatorKey;
  final GlobalKey<ScaffoldMessengerState>? scaffoldMessengerKey;
  final Future<List<ElderSummary>> Function() loadElders;
  final FutureOr<bool> Function() isGuardianLoggedIn;

  /// 앱이 막 시작됐으면 저장된 열쇠가 아직 메모리에 없을 수 있어 한 번 불러온다.
  static Future<bool> _defaultLoggedIn() async {
    if (NulbomApi.guardianKey.isNotEmpty) return true;
    return (await NulbomApi.loadGuardianKey()).isNotEmpty;
  }

  /// 앱이 막 시작됐으면 화면(Navigator)이 아직 없을 수 있어 잠시 기다린다.
  Future<NavigatorState?> _navigator() async {
    for (var i = 0; i < 100; i++) {
      final n = navigatorKey.currentState;
      if (n != null) return n;
      await Future<void>.delayed(const Duration(milliseconds: 100));
    }
    return null;
  }

  final List<StreamSubscription<Map<String, String>>> _subs = [];

  static String routeName(int elderId) => 'elder-detail-$elderId';

  Future<void> start() async {
    _subs.add(source.onOpened.listen((m) => unawaited(_open(m))));
    _subs.add(source.onForeground.listen((m) => unawaited(_showSnack(m))));
    final initial = await source.initialMessage();
    if (initial != null) {
      await _open(initial);
    }
  }

  Future<void> dispose() async {
    for (final s in _subs) {
      await s.cancel();
    }
    _subs.clear();
  }

  static int? _parseId(Map<String, String> message) {
    final id = int.tryParse(message['elder_id'] ?? '');
    if (id == null || id < 1) return null;
    return id;
  }

  Future<void> _open(Map<String, String> message) async {
    try {
      final id = _parseId(message);
      if (id == null || !await isGuardianLoggedIn()) return;

      final elders = await loadElders();
      ElderSummary? found;
      for (final e in elders) {
        if (e.elderId == id) {
          found = e;
          break;
        }
      }
      if (found == null) return;

      final navigator = await _navigator();
      if (navigator == null) return;

      // 같은 어르신 화면이 이미 맨 위면 쌓지 않는다.
      String? topName;
      navigator.popUntil((route) {
        topName = route.settings.name;
        return true;
      });
      if (topName == routeName(id)) return;

      unawaited(navigator.push(MaterialPageRoute<void>(
        settings: RouteSettings(name: routeName(id)),
        builder: (_) =>
            ElderlyDetailScreen(elderlyId: id, elderlyName: found!.name),
      )));
    } catch (e) {
      debugPrint('푸시 이동 실패: $e');
    }
  }

  Future<void> _showSnack(Map<String, String> message) async {
    try {
      if (!await isGuardianLoggedIn()) return;
      final messenger = scaffoldMessengerKey?.currentState ??
          (navigatorKey.currentContext == null
              ? null
              : ScaffoldMessenger.maybeOf(navigatorKey.currentContext!));
      if (messenger == null) return;
      final body = message['body'];
      messenger.showSnackBar(SnackBar(
        content: Text(body == null || body.isEmpty ? '새 알림이 있어요' : body),
        action: SnackBarAction(
          label: '보기',
          onPressed: () => unawaited(_open(message)),
        ),
      ));
    } catch (e) {
      debugPrint('푸시 알림 표시 실패: $e');
    }
  }
}
