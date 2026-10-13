from app.api.passwords import NO_LOGIN, hash_password, verify_password


def test_a_hash_verifies_only_the_right_password():
    stored = hash_password("correct horse")
    assert verify_password("correct horse", stored) is True
    assert verify_password("wrong horse", stored) is False


def test_the_same_password_hashes_differently_each_time():
    assert hash_password("same-password") != hash_password("same-password")


def test_the_hash_never_contains_the_password():
    assert "correct horse" not in hash_password("correct horse")


def test_the_no_login_marker_never_verifies():
    assert verify_password("not-a-login", NO_LOGIN) is False
    assert verify_password("", NO_LOGIN) is False


def test_garbage_hashes_never_verify_and_never_raise():
    for stored in ("", "x", "scrypt$1$2", "scrypt$a$b$c$d$e", "bcrypt$whatever"):
        assert verify_password("anything", stored) is False


def test_unicode_passwords_work():
    stored = hash_password("비밀번호가 길어요 ✓")
    assert verify_password("비밀번호가 길어요 ✓", stored) is True
