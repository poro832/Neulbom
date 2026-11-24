# 앱 전체 글자 크기 설정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 앱 모든 화면의 글자를 4단계(작게·보통·크게·아주 크게)로 바꿀 수 있게 하고 이 기기에 저장한다.

**Architecture:** `MaterialApp.builder`에서 `MediaQuery.textScaler`를 한 번 바꾼다. 단계는 `ValueNotifier<int>`(`textSizeIndex`)가 들고 `SharedPreferences`에 저장한다. 고르는 아래 창 하나(`showTextSizeSheet`)를 어르신 메뉴·보호자 계정 화면·채팅 설정에서 같이 쓴다.

**Tech Stack:** Flutter(Dart), shared_preferences, flutter_test (`client/`)

**Spec:** `docs/superpowers/specs/2026-11-24-app-text-size-design.md`

## Global Constraints

- 단계: 작게 0.85 / 보통 1.0(기본) / 크게 1.2 / 아주 크게 1.45. 저장 키 `app_text_size_index`. 옛 채팅 키 `chat_font_size_index`는 새 값이 없을 때만 같은 번호로 옮긴다.
- 시스템 글자 배율을 곱하되 최종 배율 상한은 1.8.
- 채팅 말풍선·입력창 기본 글자 19(전체 배율이 곱해진다). 채팅이 두 번 커지면 안 된다.
- 저장소를 못 읽거나 쓰거나 값이 범위 밖이어도 기본(보통)으로 동작하고 예외를 던지지 않는다.
- 문구는 쉬운 한국어. 코드 주석은 한국어, 기존 파일의 스타일을 따른다.
- 커밋 메시지는 한국어, **Claude 공동저자 줄을 넣지 않는다**(사용자 규칙).

## Review Focus

- 저장된 값이 범위 밖(-1, 9)이거나 문자열 등 이상한 값 → 보통으로 시작 (Task 1)
- 폰 시스템 글자 2.0배 + 앱 "아주 크게" → 최종 1.8배로 제한 (Task 1, 2)
- 옛 채팅 설정만 있는 기기(크게=2)로 업데이트 → 새 설정도 "크게"로 보임 (Task 1)
- 채팅 말풍선이 전체 배율과 자체 크기로 두 번 커지지 않음 (Task 3)
- 폭 360dp·"아주 크게"에서 어르신 홈, 보호자 홈, 역할 선택, 로그인 화면이 넘치지 않음 (Task 4)

---

### Task 1: 글자 크기 상태 저장소

**Files:**
- Create: `client/lib/services/text_size.dart`
- Test: `client/test/text_size_test.dart`

**Interfaces:**
- Produces:
  ```dart
  class TextSizeOption { final String label; final double scale; const TextSizeOption(this.label, this.scale); }
  const List<TextSizeOption> textSizeOptions; // 위 4단계
  const int textSizeDefaultIndex = 1;
  final ValueNotifier<int> textSizeIndex;           // 현재 단계
  Future<void> loadTextSize();                      // 저장값(없으면 옛 채팅값, 없으면 기본)을 읽어 textSizeIndex에 넣는다
  Future<void> setTextSize(int index);              // 범위를 벗어나면 무시, 알리고 저장(실패는 조용히)
  double effectiveTextScale(int index, double systemScale); // (옵션 배율 × systemScale)을 0.5~1.8로 제한
  ```

- [ ] **Step 1: 실패하는 테스트** — `SharedPreferences.setMockInitialValues`로 다음을 확인한다: 값 없음→`textSizeIndex.value==1`; `{'app_text_size_index': 3}`→3; `{'app_text_size_index': 9}`와 `-1`→1; `{'app_text_size_index': 'x'}`(문자열)→1; `{'chat_font_size_index': 2}`만 있으면→2; 둘 다 있으면 새 값 우선; `setTextSize(2)` 뒤 값 2이고 저장된 값도 2, `setTextSize(7)`은 무시; `effectiveTextScale(3, 2.0)==1.8`, `effectiveTextScale(1, 1.0)==1.0`, `effectiveTextScale(0, 1.0)==0.85`.
- [ ] **Step 2: 실패 확인** — Run: `cd client && flutter test test/text_size_test.dart` → 파일 없음으로 FAIL.
- [ ] **Step 3: 구현** — `text_size.dart`에 위 인터페이스를 만든다. 읽기·쓰기는 `try/catch`로 감싸 실패 시 기본값. `loadTextSize`는 호출할 때마다 저장값 기준으로 `textSizeIndex.value`를 다시 정한다(테스트에서 반복 호출).
- [ ] **Step 4: 통과 확인** — 같은 명령 → PASS.
- [ ] **Step 5: 커밋** — `git add client/lib/services/text_size.dart client/test/text_size_test.dart` / `git commit -m "feat: 앱 전체 글자 크기 4단계를 이 기기에 저장하고 옛 채팅 글자 크기 설정을 옮겨 온다"`

### Task 2: 앱 맨 위에서 배율 적용

**Files:**
- Modify: `client/lib/main.dart` (시작 시 `loadTextSize()`, `MaterialApp.builder`)
- Test: `client/test/text_size_app_test.dart`

**Interfaces:**
- Consumes: `textSizeIndex`, `loadTextSize`, `effectiveTextScale` (Task 1)
- Produces: 앱 어느 화면에서든 `MediaQuery.textScalerOf(context).scale(10)`이 `10 × 배율`이다.

- [ ] **Step 1: 실패하는 테스트** — 앱 위젯(`main.dart`의 앱 클래스 이름을 확인해 그대로 사용, 소개 화면 대기 때문에 `SplashGate`가 있는 경우 `pumpAndSettle`/충분한 `pump`)을 펼치고 `textSizeIndex.value = 3`으로 바꾸면 화면의 `MediaQuery.textScalerOf`가 `scale(10) == 14.5`; 1이면 `10`; 시스템 배율 2.0(`tester.platformDispatcher.textScaleFactorTestValue = 2.0`)에 "아주 크게"면 `scale(10) == 18`(1.8 상한).
- [ ] **Step 2: 실패 확인** — `flutter test test/text_size_app_test.dart` → FAIL.
- [ ] **Step 3: 구현** — `main()`에서 `WidgetsFlutterBinding.ensureInitialized()` 뒤 `await loadTextSize()`(기존 초기화 순서를 해치지 않게 한 곳에). `MaterialApp(builder: (context, child) => ValueListenableBuilder<int>(valueListenable: textSizeIndex, builder: (_, i, __) => MediaQuery(data: mq.copyWith(textScaler: TextScaler.linear(effectiveTextScale(i, systemScale))), child: child!)))`. `systemScale`은 `MediaQuery.of(context).textScaler.scale(1)`.
- [ ] **Step 4: 통과 확인** — 같은 명령 → PASS.
- [ ] **Step 5: 커밋** — `git commit -m "feat: 앱 맨 위에서 글자 배율을 적용해 모든 화면의 글자가 설정에 따라 커지고 줄어든다"`

### Task 3: 고르는 창과 진입점, 채팅 합치기

**Files:**
- Create: `client/lib/screens/text_size_sheet.dart` (`Future<void> showTextSizeSheet(BuildContext context)`, 키 `Key('text-size-sheet')`, 단계 항목 `Key('text-size-$i')`, 완료 `Key('text-size-done')`)
- Modify: `client/lib/screens/elderly_home_page.dart` (`...` 메뉴에 "글자 크기" 항목 value `'text_size'`), `client/lib/screens/guardian_account_screen.dart` ("글자 크기" 카드), `client/lib/screens/chat_widgets.dart`, `ai_chat_screen.dart`, `chat_history.dart` (채팅 자체 글자 크기 제거, 설정 창의 글자 크기는 `showTextSizeSheet` 진입 항목으로 대체하거나 같은 선택 위젯 재사용, 말풍선·입력창 글자 19 고정)
- Test: `client/test/text_size_sheet_test.dart`, 기존 `client/test/ai_chat_test.dart`·`read_aloud_test.dart` 중 `chat-font-`·`chatFontOptions`·`loadChatFontIndex`를 쓰는 곳을 새 동작에 맞게 고침

**Interfaces:**
- Consumes: `textSizeOptions`, `textSizeIndex`, `setTextSize` (Task 1)
- Produces: `showTextSizeSheet(context)` — 항목을 누르면 즉시 `setTextSize`를 부르고 창은 열어 둔다(뒤 화면이 바뀌는 것을 보며 고른다).

- [ ] **Step 1: 실패하는 테스트** — (a) `showTextSizeSheet`를 연 뒤 `text-size-3`을 누르면 `textSizeIndex.value == 3`이고 저장소 값도 3; 완료로 닫힘. (b) 어르신 홈 `...` 메뉴를 열면 "글자 크기"가 보이고 누르면 시트가 열림. (c) 보호자 계정 화면에 "글자 크기" 카드가 있고 누르면 시트가 열림. (d) 채팅 말풍선 글자는 `textSizeIndex`가 1일 때와 3일 때 기본 `fontSize`가 같고(19) 화면상 배율만 다르다 — `ChatBubble`의 `fontSize` 기본값이 19이고 `ai_chat_screen`이 `chatFontOptions`를 더는 쓰지 않는다.
- [ ] **Step 2: 실패 확인** — 해당 테스트 파일 실행 → FAIL.
- [ ] **Step 3: 구현** — 위 파일들을 수정한다. 옛 `chatFontOptions`·`loadChatFontIndex`·`saveChatFontIndex`는 Task 1의 옛 키 이전(`app_text_size_index` 없을 때 `chat_font_size_index` 읽기)이 대신하므로 채팅 쪽 정의를 삭제한다. 채팅 설정 창에는 번역 언어와 "글자 크기 바꾸기" 줄만 남긴다.
- [ ] **Step 4: 통과 확인** — `flutter test` 전체 → PASS(기존 채팅 테스트 포함).
- [ ] **Step 5: 커밋** — `git commit -m "feat: 어르신 메뉴·보호자 계정·채팅 설정에서 같은 글자 크기 창으로 앱 전체 글자 크기를 고르고 채팅의 따로 있던 크기 설정은 합친다"`

### Task 4: 큰 글씨에서 넘치는 화면 찾아 고치기

**Files:**
- Test: `client/test/text_size_overflow_test.dart`
- Modify: 넘치는 것으로 드러난 화면들(`elderly_home_page.dart`, `guardian_home_page.dart`, `role_selection_screen.dart`, `elderly_login_screen.dart`, `guardian_login_screen.dart`, `emergency_screen.dart` 등)

**Interfaces:** Consumes: `textSizeIndex` (Task 1).

- [ ] **Step 1: 실패하는 테스트** — 화면 크기 360×800(`tester.view.physicalSize`, `devicePixelRatio = 1`), `textSizeIndex.value = 3`일 때 위 화면들을 각각 펼쳐 `tester.takeException()`이 null(RenderFlex overflow 없음)이고 주요 버튼이 화면 안에 있다. 화면 생성에 필요한 가짜 서비스는 기존 테스트의 방식을 따른다.
- [ ] **Step 2: 실패 확인** — 어떤 화면이 넘치는지 목록으로 확인한다(FAIL).
- [ ] **Step 3: 구현** — 넘치는 곳마다 `Expanded/Flexible`, `SingleChildScrollView`, `FittedBox`, 줄 수 허용 등 가장 작은 수정으로 고친다(아이콘·여백 크기를 바꾸지 않는다).
- [ ] **Step 4: 통과 확인** — `flutter test` 전체 → PASS.
- [ ] **Step 5: 커밋** — `git commit -m "fix: 큰 글씨(아주 크게)에서 글자가 넘치던 화면들을 스크롤·줄바꿈이 되도록 고친다"`

### Task 5: 전체 확인과 설치

- [ ] **Step 1:** `cd client && flutter analyze` → 오류·경고 0(정보 안내는 기존 수준 이하). `flutter test` → 전부 PASS.
- [ ] **Step 2:** `flutter build apk --release` 뒤 `release/nuelbom.apk`로 복사하고 폴드7에 `adb install -r --user 0`(화면이 잠겨 있으면 사용자에게 알린다). 어르신 홈에서 "글자 크기"를 바꿔 화면이 바뀌고 앱을 껐다 켜도 유지되는지 캡처로 확인한다.
- [ ] **Step 3:** 푸시는 사용자 확인 뒤에 한다.
