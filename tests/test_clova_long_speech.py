"""CLOVA Speech 장문 인식 어댑터.

전송 계층을 주입받으므로 키 없이 규약 전체가 검증된다 — 기존 어댑터 넷과
같은 자리다.
"""

import json
import wave

import pytest

from app.media.clova_long_speech import ClovaLongSpeech
from app.transcription import TranscriptionFailed, TranscriptionUnavailable

INVOKE_URL = "https://example.test/external/v1/1234/abcd"


def make_wav(tmp_path, seconds: float = 1.0):
    path = tmp_path / "call.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x01" * int(8000 * seconds))
    return path


class FakeTransport:
    def __init__(self, reply: bytes):
        self.reply = reply
        self.calls: list[tuple[str, dict, dict, float]] = []

    def __call__(self, url, *, headers, files, timeout):
        self.calls.append((url, headers, files, timeout))
        return self.reply


def reply_of(text="무릎이 아파요", result="COMPLETED"):
    return json.dumps({"result": result, "message": "Succeeded", "text": text}).encode()


def make(reply=None, **kwargs):
    transport = FakeTransport(reply if reply is not None else reply_of())
    stt = ClovaLongSpeech(
        invoke_url=INVOKE_URL, secret_key="SECRET", transport=transport, **kwargs
    )
    return stt, transport


def params_of(transport):
    """multipart의 params 부분을 JSON으로 되돌린다."""
    _, _, files, _ = transport.calls[0]
    raw = files["params"][1]
    return json.loads(raw.decode() if isinstance(raw, bytes) else raw)


# ------------------------------------------------------------ 요청 형식


def test_it_posts_to_the_upload_endpoint(tmp_path):
    stt, transport = make()

    stt.transcribe(make_wav(tmp_path))

    url, _, _, _ = transport.calls[0]
    assert url == f"{INVOKE_URL}/recognizer/upload"


def test_the_secret_key_goes_in_the_clovaspeech_header(tmp_path):
    """단문과 같은 헤더 이름이다. Voice의 X-NCP-APIGW-*나 Studio의 Bearer와
    섞으면 401이 나는데 원인이 안 보인다."""
    stt, transport = make()

    stt.transcribe(make_wav(tmp_path))

    _, headers, _, _ = transport.calls[0]
    assert headers["X-CLOVASPEECH-API-KEY"] == "SECRET"


def test_the_language_code_is_not_the_short_form_one(tmp_path):
    """같은 사업자의 같은 제품인데 값이 다르다 — 단문은 lang="Kor",
    장문은 params.language="ko-KR"이다. 단문 어댑터를 보고 짐작하면 틀린다.
    """
    stt, transport = make()

    stt.transcribe(make_wav(tmp_path))

    assert params_of(transport)["language"] == "ko-KR"


def test_it_asks_for_the_result_in_the_response(tmp_path):
    """completion의 기본값은 async인데, async는 콜백이나 Object Storage로만
    결과를 주고 토큰으로 가져오는 방법이 아예 없다. sync가 아니면 우리는
    결과를 받을 길이 없다(설계 10장).
    """
    stt, transport = make()

    stt.transcribe(make_wav(tmp_path))

    assert params_of(transport)["completion"] == "sync"


def test_speaker_separation_is_turned_off_explicitly(tmp_path):
    """diarization.enable의 기본값이 True다. 안 보내면 켜진 채로 돈다.

    화자 분리를 켜면 TV나 동거 가족을 걸러낼 여지가 생기지만 그건 점수 축을
    또 바꾸는 일이라 별도 판단으로 미뤘다(설계 10장).
    """
    stt, transport = make()

    stt.transcribe(make_wav(tmp_path))

    assert params_of(transport)["diarization"] == {"enable": False}


def test_every_recognition_option_is_sent_explicitly(tmp_path):
    """사업자가 기본값을 바꾸면 우리 점수가 아무 신호 없이 바뀐다.

    fullText·wordAlignment·noiseFiltering·diarization은 모두 사업자 기본값이
    True다. 안 보내면 켜진 채로 돈다. "같은 입력이면 같은 숫자"를 내세우는
    이상, 입력의 생성 조건을 사업자 기본값에 맡겨 둘 수 없다(설계 10장).

    키가 있는지가 아니라 값이 무엇인지를 본다 — 값을 안 보면 noiseFiltering이
    False로 뒤집혀도 통과한다. 통째로 비교하므로 나중에 누가 옵션을 하나 더
    얹어도 여기서 걸린다. 인식 옵션이 바뀌면 전사가 바뀌고 따라서 점수가
    바뀌므로, 그 변경은 의도적이어야 한다.
    """
    stt, transport = make()

    stt.transcribe(make_wav(tmp_path))

    assert params_of(transport) == {
        "language": "ko-KR",
        "completion": "sync",
        "fullText": True,
        "wordAlignment": False,
        "noiseFiltering": True,
        "diarization": {"enable": False},
    }


def test_the_wav_is_sent_as_the_media_part(tmp_path):
    stt, transport = make()
    path = make_wav(tmp_path, seconds=0.5)

    stt.transcribe(path)

    _, _, files, _ = transport.calls[0]
    assert files["media"][0] == path.name
    assert files["media"][1] == path.read_bytes()


def test_the_timeout_is_the_whole_budget_for_one_call(tmp_path):
    """시도당이 아니라 통화당 예산이다. 줄이 직렬이라, 시도마다 10분을 주면
    한 통화가 최악 30분을 잡고 그날 아침 전체가 밀린다(설계 5장).
    """
    stt, transport = make(timeout=600.0)

    stt.transcribe(make_wav(tmp_path))

    assert transport.calls[0][3] == 600.0


# ------------------------------------------------------------ 응답


def test_the_recognised_text_comes_back(tmp_path):
    stt, _ = make(reply=reply_of("외롭고 힘들어요"))

    assert stt.transcribe(make_wav(tmp_path)) == "외롭고 힘들어요"


def test_a_business_failure_is_not_treated_as_silence(tmp_path):
    """HTTP는 200인데 본문 result가 실패인 경우가 있다.

    빈 문자열을 돌려주면 '부정어가 없었다'와 '전사가 실패했다'가 같은 값이
    되어, 점수 20점이 조용히 0으로 들어간다.
    """
    stt, _ = make(reply=json.dumps({"result": "FAILED", "message": "nope"}).encode())

    with pytest.raises(TranscriptionFailed):
        stt.transcribe(make_wav(tmp_path))


def test_a_reply_without_text_is_a_failure(tmp_path):
    """text 필드가 아예 없으면 인식이 어디까지 갔는지 알 수 없다 —
    빈 문자열(말을 안 했다)과 달리 이건 우리가 기대한 모양이 아니다.
    """
    stt, _ = make(reply=json.dumps({"result": "COMPLETED"}).encode())

    with pytest.raises(TranscriptionFailed):
        stt.transcribe(make_wav(tmp_path))


def test_a_successful_recognition_with_no_speech_is_not_a_failure(tmp_path):
    """어르신이 통화 내내 거의 말을 안 하면 인식은 성공하고 text는 빈다.
    실호출로 확인한 실제 응답이 그렇다 — result="COMPLETED", text="".

    이걸 실패로 처리하면 그 통화는 degraded가 되어 점수가 아예 안 나오고
    기준선 표본에서도 빠진다. 그런데 그 통화가 바로 가장 위험한 통화다 —
    발화 비율 35점과 침묵 25점이 동시에 치솟는 상황이라, 보호자가 가장
    알아야 할 때 아무 숫자도 못 보게 된다.

    말을 안 한 것과 못 알아들은 것은 다르다. 앞은 데이터고 뒤는 사고다.
    """
    stt, _ = make(reply=reply_of(text=""))

    assert stt.transcribe(make_wav(tmp_path)) == ""


def test_a_failed_result_is_a_failure_even_when_text_came_along(tmp_path):
    """판단 기준은 result다. 글자가 딸려 왔다고 성공으로 보면, 사업자가
    실패라고 말한 결과를 점수에 넣게 된다.
    """
    stt, _ = make(reply=reply_of(text="무릎이 아파요", result="FAILED"))

    with pytest.raises(TranscriptionFailed):
        stt.transcribe(make_wav(tmp_path))


def test_a_non_string_text_is_a_failure_not_a_crash(tmp_path):
    """HTTP 200에 text가 숫자로 오면(사업자 쪽 이례적 응답), 검사 없이
    넘기면 바로 다음 줄의 len(text) 로깅에서 TypeError가 난다. 그건 우리가
    선언한 두 예외 중 어느 쪽도 아니라서 워커의 except Exception이 삼키고
    sink가 아예 안 불린다 — 그 통화는 CallOutcome을 하나도 못 받는다.
    """
    stt, _ = make(reply=json.dumps({"result": "COMPLETED", "text": 12345}).encode())

    with pytest.raises(TranscriptionFailed):
        stt.transcribe(make_wav(tmp_path))


def test_a_broken_reply_is_a_failure_not_a_crash(tmp_path):
    stt, _ = make(reply=b"<html>oops</html>")

    with pytest.raises(TranscriptionFailed):
        stt.transcribe(make_wav(tmp_path))


def test_a_connection_error_is_reported_as_retryable(tmp_path):
    """연결 실패는 빠르게 돌아오고 잠깐 끊긴 네트워크가 원인일 수 있다.
    워커가 이 구분을 보고 재시도 여부를 정한다(설계 5장).
    """

    def exploding(url, *, headers, files, timeout):
        raise OSError("연결 실패")

    stt = ClovaLongSpeech(
        invoke_url=INVOKE_URL, secret_key="SECRET", transport=exploding
    )

    with pytest.raises(TranscriptionUnavailable):
        stt.transcribe(make_wav(tmp_path))


def test_a_missing_recording_does_not_reach_the_network(tmp_path):
    """녹음이 없는데 요청을 보내면 돈만 쓰고 실패한다."""
    stt, transport = make()

    with pytest.raises(TranscriptionFailed):
        stt.transcribe(tmp_path / "없는파일.wav")

    assert transport.calls == []


def test_a_missing_dependency_is_not_reported_as_retryable(tmp_path):
    """httpx가 없는 것 같은 환경 문제는 다시 보낸다고 낫지 않는다.

    재시도 가능으로 분류하면 워커가 세 번 시도하고 통화를 접는데, 로그에는
    "연결 실패"만 남아 진짜 원인(설치가 안 됐다)이 묻힌다.
    """

    def missing_dependency(url, *, headers, files, timeout):
        raise ImportError("No module named 'httpx'")

    stt = ClovaLongSpeech(
        invoke_url=INVOKE_URL, secret_key="SECRET", transport=missing_dependency
    )

    with pytest.raises(TranscriptionFailed):
        stt.transcribe(make_wav(tmp_path))


def test_a_miswired_transport_is_not_reported_as_retryable(tmp_path):
    """우리 쪽 배선 실수는 네트워크 문제가 아니다. 재시도해도 영원히 같다."""

    def wrong_signature(url, **kwargs):
        raise TypeError("unexpected keyword argument 'files'")

    stt = ClovaLongSpeech(
        invoke_url=INVOKE_URL, secret_key="SECRET", transport=wrong_signature
    )

    with pytest.raises(TranscriptionFailed):
        stt.transcribe(make_wav(tmp_path))


def test_a_reply_that_is_json_but_not_an_object_is_a_failure(tmp_path):
    """`null`도 `[]`도 유효한 JSON이다. 그대로 .get을 부르면 AttributeError가
    나는데, 그건 우리가 약속한 두 예외 중 어느 것도 아니라 워커를 뚫고 나간다.
    """
    stt, _ = make(reply=b"null")

    with pytest.raises(TranscriptionFailed):
        stt.transcribe(make_wav(tmp_path))
