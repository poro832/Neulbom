"""열쇠 도구와 인증기. 열쇠는 DB에 지문으로만 남고, 로그에는 앞부분만 나온다."""

from __future__ import annotations

import hashlib

import pytest

from app.api.guardian_auth import (
    KEY_LENGTH,
    KEY_PREFIX,
    InMemoryGuardianKeyStore,
    KeyAuth,
    attempt_label,
    generate_key,
    hash_key,
    looks_like_key,
    parse_bearer,
)


def test_a_generated_key_has_the_documented_shape():
    new = generate_key()

    assert new.key.startswith(KEY_PREFIX)
    assert len(new.key) == KEY_LENGTH == 47
    assert new.key_prefix == new.key[:12]
    assert new.key_hash == hashlib.sha256(new.key.encode("utf-8")).hexdigest()
    assert new.key not in new.key_hash


def test_two_generated_keys_differ():
    assert generate_key().key != generate_key().key


@pytest.mark.parametrize(
    "header",
    ["Bearer abc", "bearer abc", "BEARER abc", "  Bearer   abc  ", "Bearer\tabc"],
)
def test_bearer_headers_are_parsed_leniently(header):
    assert parse_bearer(header) == "abc"


@pytest.mark.parametrize(
    "header",
    [None, "", "   ", "Bearer", "Bearer a b", "Basic abc", "abc", "Bearer " + "x" * 5000 + " y"],
)
def test_anything_that_is_not_one_bearer_token_is_rejected(header):
    assert parse_bearer(header) is None


def test_looks_like_key_checks_prefix_and_length():
    good = generate_key().key

    assert looks_like_key(good)
    assert not looks_like_key("xyz_" + good[4:])
    assert not looks_like_key(good[:-1])
    assert not looks_like_key(good + "a")
    assert not looks_like_key("")


class ExplodingStore:
    """형식이 틀린 열쇠로는 저장소를 부르면 안 된다."""

    def find_guardian(self, key_hash):
        raise AssertionError("저장소를 부르면 안 된다")


def test_a_malformed_key_never_reaches_the_store():
    auth = KeyAuth(ExplodingStore())

    for header in (None, "Bearer", "Bearer short", "Bearer nlb_tooshort", "Basic x"):
        assert auth.authenticate(header) is None


def make_auth():
    store = InMemoryGuardianKeyStore()
    new = generate_key()
    store.add(guardian_id=7, label="t", key_prefix=new.key_prefix, key_hash=new.key_hash)
    return KeyAuth(store), store, new


def test_a_known_key_identifies_its_guardian():
    auth, _, new = make_auth()

    assert auth.authenticate(f"Bearer {new.key}") == 7
    assert auth.authenticate(f"bearer   {new.key}  ") == 7


def test_an_unknown_but_well_formed_key_is_rejected():
    auth, _, _ = make_auth()

    assert auth.authenticate(f"Bearer {generate_key().key}") is None


def test_a_revoked_key_is_rejected_from_the_next_request():
    auth, store, new = make_auth()
    assert auth.authenticate(f"Bearer {new.key}") == 7

    assert store.revoke(new.key_prefix) == 1

    assert auth.authenticate(f"Bearer {new.key}") is None


def test_the_log_label_never_shows_more_than_the_prefix():
    new = generate_key()

    label = attempt_label(f"Bearer {new.key}")

    assert label == new.key[:12]
    assert new.key not in label
    assert attempt_label("Bearer nope") == "(형식 오류)"
    assert attempt_label(None) == "(형식 오류)"
    assert hash_key(new.key) not in label
