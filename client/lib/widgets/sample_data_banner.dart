import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// 서버에 아직 없는 화면의 맨 위에 다는 띠.
///
/// 대화 기록, 알림, 어르신 목록은 지금 화면 안에 박아 둔 예시 값이다. 보호자가
/// 이것을 실제 통화로 읽으면 안 되므로 숨기지 않고 알린다. 서버에 해당 주소가
/// 생기면 그 화면부터 이 띠를 뗀다.
class SampleDataBanner extends StatelessWidget {
  const SampleDataBanner({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: eAccentSoft,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Row(
            children: [
              const Icon(Icons.info_outline, size: 18, color: eInk),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '예시 화면이에요. 아직 실제 통화 기록과 연결되지 않았습니다.',
                  style: const TextStyle(fontSize: 13, color: eInk),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
