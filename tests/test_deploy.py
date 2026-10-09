"""deploy/ — 서버에만 있던 설정을 저장소로 옮긴 것.

이 파일들은 파이썬이 아니라서 테스트가 안 닿는 자리다. 그런데 틀리면
조용히 틀린다. 전화가 그냥 안 붙거나, 막아야 할 경로가 인터넷에 열린다.
그래서 **앱과 어긋날 수 있는 지점**만 골라 고정한다.
"""

from __future__ import annotations

import re
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


def caddy_allowlist() -> set[str]:
    text = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    match = re.search(r"@clawops\s+path\s+([^\n]+)", text)
    assert match, "Caddyfile에서 @clawops 경로 목록을 못 찾았다"
    return set(match.group(1).split())


def app_routes(tmp_path) -> set[str]:
    import re

    from fastapi.testclient import TestClient

    from app.api.alerts import InMemoryAlertStore
    from app.main import app_data_for, build_server
    from app.api.elder_directory import InMemoryElderDirectory
    from app.api.guardian_auth import InMemoryGuardianKeyStore, KeyAuth
    from app.api.store import InMemoryCallStore
    from app.telephony.client import FakeTelephony
    from tests.test_server_wiring import _Beep

    directory = InMemoryElderDirectory()
    auth = KeyAuth(InMemoryGuardianKeyStore())
    data, rules = app_data_for(None, guardian_auth=auth, elders=directory)
    server = build_server(
        store=InMemoryCallStore(phones={12: "070-1111-2222"}),
        telephony=FakeTelephony(),
        public_base_url="https://api.example.com",
        stream_base_url="wss://api.example.com",
        responder_factory=_Beep,
        recordings_dir=tmp_path,
        guardian_auth=auth,
        elders=directory,
        app_data=data,
        alert_rules=rules,
    )
    paths = {getattr(route, "path", "") for route in TestClient(server).app.routes}
    return {re.sub(r"\{[^}]+\}", "*", path) for path in paths}


def test_every_path_caddy_opens_exists_in_the_app(tmp_path):
    """앱에서 경로 이름을 바꾸고 Caddyfile을 안 고치면, 사업자 웹훅이
    Caddy의 404에 막혀 전화가 조용히 안 붙는다. 로그엔 앱까지 온 흔적조차
    없어서 원인을 찾기 어렵다."""
    missing = caddy_allowlist() - app_routes(tmp_path)

    assert not missing, f"Caddy는 여는데 앱에 없는 경로: {sorted(missing)}"


def test_the_trigger_api_is_open_only_because_it_demands_a_key():
    """/v1/calls/request는 열쇠 없이는 401이다. 열린 문에 자물쇠가 실제로 있는지
    검사한다 — 이 검사가 빠지면 누구나 어르신께 전화를 걸게 할 수 있다."""
    from fastapi.testclient import TestClient

    import app.main as main

    assert "/v1/calls/request" in caddy_allowlist()

    client = TestClient(main.app)
    assert client.post("/v1/calls/request", json={"elder_id": 1}).status_code == 401
    assert (
        client.post(
            "/v1/calls/request", json={"elder_id": 1}, headers={"Authorization": "Bearer nlb_x"}
        ).status_code
        == 401
    )


def test_nothing_else_is_proxied():
    """허용 목록 밖은 전부 Caddy가 404로 끊는다. 뒤에 catch-all
    reverse_proxy가 생기면 허용 목록이 의미를 잃는다."""
    text = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")

    assert text.count("reverse_proxy") == 1
    assert 'respond "not found" 404' in text


def test_the_service_runs_the_serve_entrypoint():
    """uvicorn을 직접 부르면 .env가 늦게 읽히고 우리 INFO 로그가 사라진다."""
    unit = (DEPLOY / "systemd" / "nulbom.service").read_text(encoding="utf-8")

    assert "-m app.serve" in unit
    assert "uvicorn" not in unit.split("[Service]")[1]


def test_no_carriage_returns_in_server_files():
    """\r 하나로 셸 스크립트와 systemd 파일이 조용히 깨진다. 2026-09-30에
    DuckDNS 설정에서 실제로 한 시간을 썼다."""
    offenders = [
        str(path.relative_to(DEPLOY))
        for path in DEPLOY.rglob("*")
        if path.is_file() and b"\r" in path.read_bytes()
    ]

    assert not offenders, f"\r이 섞인 파일: {offenders}"


def test_the_duckdns_example_carries_no_token():
    """토큰을 가진 사람은 도메인이 가리키는 서버를 바꿔 통화 음성을
    가로챌 수 있다. 예시 파일에 실수로라도 남으면 안 된다."""
    for line in (DEPLOY / "duckdns.env.example").read_text(encoding="utf-8").splitlines():
        if line.startswith("DDNS_TOKEN="):
            assert line == "DDNS_TOKEN="
            return
    raise AssertionError("DDNS_TOKEN 줄이 없다")


APP_PATHS = {
    "/v1/pair",
    "/v1/elders/*/pairing-code",
    "/v1/elders/*/weekly",
    "/v1/guardian/elders",
    "/v1/guardian/alerts",
    "/v1/me/calls",
    "/v1/me/contacts",
    "/v1/me/contacts/*",
    "/v1/signup",
    "/v1/guardian/invite",
    "/v1/elders/*/approve",
    "/v1/elders/*/reject",
    "/v1/me/status",
}


def test_the_app_data_paths_are_open_and_each_one_demands_a_key_or_a_code():
    """열린 문마다 자물쇠가 실제로 있는지 검사한다. 이 검사가 빠지면 누구나 어르신 데이터를
    읽거나 연락처를 바꿀 수 있다."""
    from fastapi.testclient import TestClient

    import app.main as main

    assert APP_PATHS <= caddy_allowlist()

    client = TestClient(main.app)
    for path in ("/v1/guardian/elders", "/v1/guardian/alerts", "/v1/elders/1/weekly",
                 "/v1/me/calls", "/v1/me/contacts"):
        assert client.get(path).status_code == 401, path
    assert client.post("/v1/elders/1/pairing-code").status_code == 401
    assert client.post("/v1/me/contacts", json={"name": "가", "phone": "111-1111"}).status_code == 401
    assert client.delete("/v1/me/contacts/1").status_code == 401
    # 열쇠가 필요 없는 /v1/pair는 코드와 번호가 맞아야 한다
    assert client.post("/v1/pair", json={"code": "123456", "phone": "070-1111-2222"}).status_code == 401
    assert client.post("/v1/guardian/invite").status_code == 401
    assert client.post("/v1/elders/1/approve").status_code == 401
    assert client.post("/v1/elders/1/reject").status_code == 401
    assert client.get("/v1/me/status").status_code == 401
    # 열쇠가 없는 /v1/signup은 가입 코드가 맞아야 한다 — 메모리 모드에는 코드가 없다
    assert client.post(
        "/v1/signup",
        json={"code": "12345678", "name": "가", "phone": "010-1234-5678", "agreed": True},
    ).status_code == 401
