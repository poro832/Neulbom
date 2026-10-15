/// 한국 시간(UTC+9)의 지금.
///
/// 서버는 하루와 주(일~토)의 경계를 한국 시간으로 정한다. 폰의 시간대가 한국이 아니어도 앱의 "오늘"과
/// "이번 주"가 서버와 같게 이 값을 쓴다.
///
/// 돌려주는 값은 UTC 시각에 9시간을 더한 것이다. `year`·`month`·`day`·`weekday`·`hour` 같은 필드를 읽으면
/// 한국의 날짜와 시각이 나온다. 필드만 읽는다 — 순간으로 다른 시각과 비교하면 9시간 어긋난다.
///
/// [nowUtc]는 테스트에서 바꾼다(어느 시간대의 값이든 UTC로 바꿔 쓴다). 기본은 [DateTime.now].
DateTime kstNow([DateTime Function()? nowUtc]) =>
    (nowUtc ?? DateTime.now)().toUtc().add(const Duration(hours: 9));
