"""운영 서버 진입점 — `python -m app.serve`

systemd가 이걸 부른다. `uvicorn app.main:app`을 직접 부르지 않는 이유가 둘이다.

**1. 우리 로그가 안 보인다.** uvicorn은 자기 로거만 설정한다. 그래서
`스케줄러를 켠다`, `Postgres 저장소로 돈다` 같은 INFO가 전부 걸러지고
WARNING만 뚫고 나온다. 2026-09-29 EC2 배포에서 실제로 겪었다 — 저장소가
Postgres인지 메모리인지 로그로 확인할 수 없었다. 서비스로 돌면 사람이 화면을
안 보고 있으니 더 치명적이다. 로깅을 우리가 먼저 잡고 uvicorn에는 손대지
말라고(`log_config=None`) 한다.

**2. `.env`를 반드시 앱보다 먼저 읽어야 한다.** `app.main`은 import하는
순간 환경을 보고 저장소·스케줄러·TTS를 조립한다. 그래서 여기서 `.env`를
읽은 뒤에 uvicorn이 `app.main`을 import하게 한다(문자열로 넘기는 이유).
`override=True`인 이유는, 셸에 옛 값이 export돼 있으면 파일이 조용히 지는
일을 09-29에 겪었기 때문이다(`set -a && . ./.env`).

**127.0.0.1에만 붙는다.** 바깥에서 오는 건 전부 Caddy가 받아 넘긴다.
uvicorn을 0.0.0.0에 열면 TLS 없이 8000번이 인터넷에 노출된다.
"""

from __future__ import annotations

import logging
import os

DEFAULT_ENV_FILE = ".env"
DEFAULT_PORT = 8000


def main(env_file: str = DEFAULT_ENV_FILE) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    from dotenv import load_dotenv

    if not load_dotenv(env_file, override=True):
        # 파일이 없어도 서버는 뜬다(키가 하나도 없으면 고정 응답으로 돈다).
        # 다만 조용히 넘어가면, 경로를 잘못 잡은 서비스가 메모리 저장소로
        # 돌면서 멀쩡해 보인다.
        logging.getLogger(__name__).warning(
            "%s를 못 읽었다 — 환경 변수만으로 뜬다", env_file
        )

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=int(os.getenv("PORT", DEFAULT_PORT)),
        log_config=None,
        # Caddy 뒤에 있다. 이게 없으면 모든 요청의 출처가 127.0.0.1로 찍히고
        # https로 들어온 요청을 http로 안다.
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


if __name__ == "__main__":
    main()
