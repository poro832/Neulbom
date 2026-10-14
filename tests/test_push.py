import json
import logging

import pytest

from app.push import FAILED, INVALID_TOKEN, SENT, FcmSender, sender_from_env

TOKEN = "fcm-token-aaaaaaaaaaaaaaaaaaaaaaaa"


class FakeTransport:
    def __init__(self, status=200, body=b"{}", error=None):
        self.status, self.body, self.error, self.calls = status, body, error, []

    def __call__(self, url, *, headers, payload, timeout):
        self.calls.append((url, headers, payload, timeout))
        if self.error:
            raise self.error
        return self.status, self.body


def sender(transport, token="oauth-token"):
    return FcmSender("my-project", lambda: token, transport=transport)


def test_a_successful_send_posts_the_v1_message():
    t = FakeTransport()
    assert sender(t).send(TOKEN, "늘봄", "김할머니 어르신 확인이 필요해요", {"elder_id": "12"}) == SENT
    url, headers, payload, _ = t.calls[0]
    assert url == "https://fcm.googleapis.com/v1/projects/my-project/messages:send"
    assert headers["Authorization"] == "Bearer oauth-token"
    assert payload == {
        "message": {
            "token": TOKEN,
            "notification": {"title": "늘봄", "body": "김할머니 어르신 확인이 필요해요"},
            "data": {"elder_id": "12"},
            "android": {"priority": "HIGH"},
        }
    }


def test_404_means_the_token_is_gone():
    body = json.dumps({"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}).encode()
    assert sender(FakeTransport(404, body)).send(TOKEN, "t", "b", {}) == INVALID_TOKEN


def test_400_about_the_token_means_invalid_token():
    body = json.dumps({"error": {"status": "INVALID_ARGUMENT", "message": "The registration token is not a valid FCM registration token"}}).encode()
    assert sender(FakeTransport(400, body)).send(TOKEN, "t", "b", {}) == INVALID_TOKEN


def test_400_about_something_else_is_a_plain_failure():
    body = json.dumps({"error": {"status": "INVALID_ARGUMENT", "message": "Invalid value at message.data"}}).encode()
    assert sender(FakeTransport(400, body)).send(TOKEN, "t", "b", {}) == FAILED


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_other_errors_never_delete_the_token(status):
    assert sender(FakeTransport(status, b"{}")).send(TOKEN, "t", "b", {}) == FAILED


def test_transport_and_token_provider_errors_are_failures_not_exceptions(caplog):
    assert sender(FakeTransport(error=RuntimeError("down"))).send(TOKEN, "t", "b", {}) == FAILED

    def broken_provider():
        raise RuntimeError("no credentials")

    s = FcmSender("p", broken_provider, transport=FakeTransport())
    with caplog.at_level(logging.INFO):
        assert s.send(TOKEN, "t", "b", {}) == FAILED
    assert TOKEN not in caplog.text


def test_sender_from_env_is_off_without_a_file_path():
    assert sender_from_env({}) is None
    assert sender_from_env({"FCM_SERVICE_ACCOUNT_FILE": ""}) is None


def test_sender_from_env_is_off_when_the_file_is_missing_or_broken(tmp_path, caplog):
    with caplog.at_level(logging.INFO):
        assert sender_from_env({"FCM_SERVICE_ACCOUNT_FILE": str(tmp_path / "nope.json")}) is None
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        assert sender_from_env({"FCM_SERVICE_ACCOUNT_FILE": str(broken)}) is None
    assert "private_key" not in caplog.text  # 경로는 비밀이 아니지만 열쇠 내용은 로그에 새면 안 된다
