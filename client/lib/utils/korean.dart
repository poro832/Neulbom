/// 이름 뒤에 붙는 조사 "와/과"를 받침에 맞게 고른다.
///
/// 마지막 글자가 받침이 있는 한글이면 "과", 받침이 없거나 한글이 아니면 "와"다.
String withWaGwa(String name) {
  final trimmed = name.trim();
  if (trimmed.isEmpty) return trimmed;
  final code = trimmed.runes.last - 0xAC00;
  final hasFinal = code >= 0 && code <= 11171 && code % 28 != 0;
  return '$trimmed${hasFinal ? '과' : '와'}';
}

/// 이름 뒤에 붙는 "이에요/예요"를 받침에 맞게 고른다. 받침이 있으면 "이에요", 없거나 한글이 아니면 "예요".
String withIEyo(String name) {
  final trimmed = name.trim();
  if (trimmed.isEmpty) return trimmed;
  final code = trimmed.runes.last - 0xAC00;
  final hasFinal = code >= 0 && code <= 11171 && code % 28 != 0;
  return '$trimmed${hasFinal ? '이에요' : '예요'}';
}
