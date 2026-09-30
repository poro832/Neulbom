"""운영 진입점 — systemd가 부르는 app/serve.py.

서버를 실제로 띄우지 않는다. uvicorn.run을 가로채 **무엇을 어떤 순서로
넘기는지**만 본다.
"""

from __future__ import annotations

import os

import pytest

import app.serve as serve


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    def fake_run(target, **kwargs):
        seen["target"] = target
        seen["kwargs"] = kwargs
        # uvicorn이 app.main을 import하는 시점의 환경 — 이때 .env 값이 이미
        # 있어야 조립부가 제대로 고른다.
        seen["env_at_run"] = os.environ.get("SERVE_TEST_MARKER")

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setattr(serve.logging, "basicConfig", lambda **_: None)
    monkeypatch.delenv("SERVE_TEST_MARKER", raising=False)
    return seen


def test_the_env_file_is_loaded_before_the_app_is_imported(tmp_path, captured):
    """app.main은 import하는 순간 환경을 보고 저장소를 고른다. .env가
    늦게 읽히면 DATABASE_URL이 있어도 메모리 저장소로 돌고, 겉으론 멀쩡하다."""
    env = tmp_path / ".env"
    env.write_text("SERVE_TEST_MARKER=from-file\n", encoding="utf-8")

    serve.main(env_file=str(env))

    assert captured["target"] == "app.main:app"  # 객체가 아니라 문자열이라 늦게 import된다
    assert captured["env_at_run"] == "from-file"


def test_the_file_wins_over_a_stale_shell_value(tmp_path, captured, monkeypatch):
    """09-29에 겪었다 — 셸에 옛 값이 export돼 있으면 파일을 고쳐도 옛 값으로 돌았다."""
    monkeypatch.setenv("SERVE_TEST_MARKER", "stale")
    env = tmp_path / ".env"
    env.write_text("SERVE_TEST_MARKER=fresh\n", encoding="utf-8")

    serve.main(env_file=str(env))

    assert captured["env_at_run"] == "fresh"


def test_it_binds_to_localhost_only(tmp_path, captured):
    """바깥은 Caddy가 받는다. 0.0.0.0에 열면 TLS 없이 8000번이 인터넷에 나간다."""
    serve.main(env_file=str(tmp_path / "없음.env"))

    assert captured["kwargs"]["host"] == "127.0.0.1"


def test_uvicorn_does_not_take_over_logging(tmp_path, captured):
    """uvicorn이 로깅을 잡으면 우리 INFO가 전부 사라진다 — 스케줄러가
    켜졌는지, 어느 저장소로 도는지 로그로 알 수 없게 된다."""
    serve.main(env_file=str(tmp_path / "없음.env"))

    assert captured["kwargs"]["log_config"] is None


def test_it_trusts_proxy_headers_only_from_caddy(tmp_path, captured):
    serve.main(env_file=str(tmp_path / "없음.env"))

    assert captured["kwargs"]["proxy_headers"] is True
    assert captured["kwargs"]["forwarded_allow_ips"] == "127.0.0.1"


def test_a_missing_env_file_is_said_out_loud(tmp_path, captured, caplog):
    with caplog.at_level("WARNING", logger="app.serve"):
        serve.main(env_file=str(tmp_path / "없음.env"))

    assert "못 읽었다" in caplog.text
