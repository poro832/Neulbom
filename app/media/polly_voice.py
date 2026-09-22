"""Amazon Polly TTS 어댑터 — 기본으로 쓰는 음성 합성.

ClovaVoice와 같은 VoiceSynthesizer 규약을 구현한다. boto3 클라이언트를
주입받으므로 자격 증명 없이 규약 전체가 테스트로 검증된다.

**왜 이쪽이 기본인가.** 셋이 같은 방향을 가리킨다.

비용 — CLOVA Voice는 100만 자까지 같은 값인 월 정액(₩99,000)이다. 우리
사용량은 월 1만 2천 자쯤이라 한도의 1.2%를 쓰면서 정액을 내게 된다. Polly는
기본료 없는 종량제라 같은 사용량이면 자릿수가 다르다.

단순함 — OutputFormat=pcm이 바로 signed 16-bit 모노 little-endian이라
Responder 규약과 그대로 맞는다. CLOVA Voice처럼 wav 헤더를 파싱해 벗길 일이
없고, 문장당 글자 수 제한도 없다.

**바꾸지 않는 것이 가장 싸다** — 목소리가 달라지면 AI 발화 길이가 달라지고,
그것이 지표의 분모(통화 전체 − AI 발화)를 바꾼다. 즉 **TTS를 바꾸는 순간
점수 시계열이 끊긴다.** 기준선 창이 14통이라 바꾸려면 최소 2주 전에 해야
하고, 그 전후 점수는 같은 추이로 볼 수 없다. 안 바꾸면 이 문제가 통째로
없다.

**CLOVA Voice는 기본이 아니라 비상구다.** 한때 "시연 달에는 CLOVA Voice로
바꾼다"고 적어 두었지만, 그건 **어느 쪽 목소리도 들어 보기 전에 세운
계획**이었다. 실제로 8kHz로 떨어뜨려 들어 보고 "어르신께 이건 못
들려드리겠다" 싶을 때만 바꾼다. 늦게 바꾸는 건 비싸고(2주 리드타임 + 점수
단절) 안 바꾸는 건 공짜이므로, 기본값은 이쪽이어야 한다.

**EC2에서는 자격 증명을 코드로 주지 않는다.** 인스턴스 프로파일
(SafeInstanceProfile-sgu-pj-03)이 붙어 있으면 boto3가 알아서 찾는다. 수업
계정은 액세스 키 발급이 아예 막혀 있어 이 경로 외에는 방법이 없다.
"""

from __future__ import annotations

import logging

from app.media.spoken_text import strip_unspoken

logger = logging.getLogger(__name__)

# pcm 출력이 지원하는 레이트는 이 둘뿐이다. 22050이나 24000은 mp3 쪽 값이라
# 그대로 보내면 InvalidSampleRateException이 돌아온다 — 호출 전에 막는다.
PCM_SAMPLE_RATES = frozenset({8000, 16000})

# SynthesizeSpeech는 전체 6,000자 중 과금 대상 3,000자까지 받는다. 넘기면
# TextLengthExceededException으로 요청이 통째로 실패한다. 우리 응답은 100자
# 안팎이라 실제로 닿을 일은 없지만, 모델이 폭주했을 때 그 턴을 통째로 잃는
# 것보다는 잘라서라도 말하는 편이 낫다.
POLLY_MAX_BILLED_CHARS = 3_000

# 한국어 여성 음성. Jihye도 한국어라 실제 통화를 들어 보고 고르면 된다.
DEFAULT_VOICE_ID = "Seoyeon"

# standard는 Seoyeon이 확실히 지원한다. neural이 더 자연스럽지만 이 목소리와
# 이 계정에서 실제로 되는지는 확인하지 않았다 — 안 되면 요청이
# EngineNotSupportedException으로 실패한다. 확실한 쪽을 기본으로 두었다.
#
# 권한이 나오면 제일 먼저 neural을 시험한다. 이 목소리로 계속 갈 작정이므로
# 품질이 중요하고, 이 사용량이면 비용 차이는 무의미하다.
DEFAULT_ENGINE = "standard"


class PollyVoice:
    """실제 합성. 자격 증명은 boto3가 환경에서 찾는다 — 코드에 박지 않는다."""

    def __init__(
        self,
        *,
        client=None,
        voice_id: str = DEFAULT_VOICE_ID,
        engine: str = DEFAULT_ENGINE,
        region_name: str | None = None,
    ) -> None:
        if client is None:
            # 여기서 import한다. 클라이언트를 주입하는 테스트는 boto3가 없어도
            # 돌아야 하고, 없을 때는 모듈을 못 불러오는 것보다 여기서 터지는
            # 편이 원인이 분명하다.
            import boto3

            client = boto3.client("polly", region_name=region_name)
        self._client = client
        # 조립부가 로그에 남긴다 — 어느 목소리가 어느 통화를 만들었는지
        # 알아야 나중에 점수를 비교할 수 있다.
        self.voice_id = voice_id
        self.engine = engine

    def synthesize(self, text: str, sample_rate: int) -> bytes:
        if sample_rate not in PCM_SAMPLE_RATES:
            raise ValueError(
                f"pcm이 지원하지 않는 샘플레이트다 — {sample_rate}. "
                f"가능한 값: {sorted(PCM_SAMPLE_RATES)}"
            )

        spoken = strip_unspoken(text)
        if not spoken:
            # 읽을 게 안 남았다. 호출해 봐야 빈 소리를 받고 요금만 쓴다.
            logger.info("읽을 내용이 없어 합성을 건너뛴다 원문=%r", text)
            return b""

        if len(spoken) > POLLY_MAX_BILLED_CHARS:
            logger.warning(
                "응답이 상한을 넘어 자른다 — %d자 → %d자",
                len(spoken),
                POLLY_MAX_BILLED_CHARS,
            )
            spoken = spoken[:POLLY_MAX_BILLED_CHARS]

        response = self._client.synthesize_speech(
            Text=spoken,
            TextType="text",
            VoiceId=self.voice_id,
            Engine=self.engine,
            OutputFormat="pcm",
            # 문자열이다. 정수를 주면 거절당한다.
            SampleRate=str(sample_rate),
        )

        # 글자 수가 곧 요금이다. 남기지 않으면 청구서를 보고 나서야 안다.
        characters = response.get("RequestCharacters")
        if characters is not None:
            logger.info("음성 합성 완료 — 과금 글자 %s자", characters)

        stream = response.get("AudioStream")
        if stream is None:
            logger.warning("응답에 오디오가 없다 — 이 턴은 침묵한다")
            return b""

        try:
            return stream.read()
        finally:
            # StreamingBody는 HTTP 연결을 물고 있다. 안 닫으면 통화마다
            # 하나씩 새고, 오래 도는 서버에서 연결 풀이 마른다.
            close = getattr(stream, "close", None)
            if close is not None:
                close()
