"""운영 도구. 열쇠는 발급 때 한 번만 보이고, 목록에는 지문도 열쇠도 나오지 않는다."""

from __future__ import annotations

import pytest

from app.admin import run
from app.api.elder_directory import ElderAccess, InMemoryElderDirectory
from app.api.guardian_auth import InMemoryGuardianKeyStore, hash_key


class Output:
    def __init__(self):
        self.lines: list[str] = []

    def __call__(self, text=""):
        self.lines.append(str(text))

    @property
    def text(self):
        return "\n".join(self.lines)


def make():
    keys = InMemoryGuardianKeyStore()
    directory = InMemoryElderDirectory({12: ElderAccess(1, True)})
    return keys, directory, Output(), Output()


def go(argv, keys, directory, out, err):
    return run(argv, keys=keys, directory=directory, out=out, err=err)


def issue(keys, directory, out, err, guardian="1", label="시연 폰"):
    return go(["key", "issue", "--guardian-id", guardian, "--label", label], keys, directory, out, err)


def test_issue_shows_the_full_key_once_and_stores_only_its_hash():
    keys, directory, out, err = make()

    assert issue(keys, directory, out, err) == 0

    (info,) = keys.list_keys()
    full = [token for token in out.text.split() if token.startswith("nlb_") and len(token) == 47]
    assert len(full) == 1
    assert full[0].startswith(info.key_prefix)
    assert keys.find_guardian(hash_key(full[0])) == 1


def test_list_never_shows_the_key_or_its_hash():
    keys, directory, out, err = make()
    issue(keys, directory, out, err)
    full = [t for t in out.text.split() if t.startswith("nlb_") and len(t) == 47][0]
    listing, _ = Output(), Output()

    assert go(["key", "list"], keys, directory, listing, err) == 0

    assert full not in listing.text
    assert hash_key(full) not in listing.text
    assert full[:12] in listing.text
    assert "시연 폰" in listing.text


def test_issue_refuses_an_unknown_guardian():
    keys, directory, out, err = make()

    assert issue(keys, directory, out, err, guardian="99") == 1

    assert "보호자" in err.text
    assert keys.list_keys() == []


def test_revoke_blocks_the_key_and_reports_it():
    keys, directory, out, err = make()
    issue(keys, directory, out, err)
    full = [t for t in out.text.split() if t.startswith("nlb_") and len(t) == 47][0]
    result, _ = Output(), Output()

    assert go(["key", "revoke", "--prefix", full[:12]], keys, directory, result, err) == 0

    assert keys.find_guardian(hash_key(full)) is None
    assert "폐기" in result.text


def test_revoke_with_a_too_short_prefix_is_refused():
    keys, directory, out, err = make()
    issue(keys, directory, out, err)

    assert go(["key", "revoke", "--prefix", "nlb_"], keys, directory, Output(), err) == 1
    assert len(keys.list_keys()) == 1 and keys.list_keys()[0].revoked_at is None


def test_revoke_with_an_ambiguous_prefix_is_refused():
    keys, directory, out, err = make()
    keys.add(guardian_id=1, label="a", key_prefix="nlb_aaaaaaaa", key_hash="1" * 64)
    keys.add(guardian_id=1, label="b", key_prefix="nlb_aaaaaaab", key_hash="2" * 64)

    assert go(["key", "revoke", "--prefix", "nlb_aaaaaaa"], keys, directory, Output(), err) == 1

    assert "겹" in err.text


def test_revoke_of_an_unknown_prefix_says_so():
    keys, directory, out, err = make()

    assert go(["key", "revoke", "--prefix", "nlb_zzzzzzzz"], keys, directory, Output(), err) == 1
    assert "없" in err.text


def test_guardian_add_prints_the_new_id():
    keys, directory, out, err = make()

    assert go(["guardian", "add", "--name", "홍길동", "--phone", "010-1111-2222"], keys, directory, out, err) == 0

    assert "보호자 번호" in out.text
    assert directory.guardian_exists(2)


def test_elder_assign_moves_the_elder_and_never_touches_consent():
    keys, directory, out, err = make()
    go(["guardian", "add", "--name", "홍길동", "--phone", "010"], keys, directory, Output(), err)

    assert go(["elder", "assign", "--elder-id", "12", "--guardian-id", "2"], keys, directory, out, err) == 0

    assert directory.get(12) == ElderAccess(guardian_id=2, consenting=True)


def test_elder_assign_to_a_missing_guardian_fails():
    keys, directory, out, err = make()

    assert go(["elder", "assign", "--elder-id", "12", "--guardian-id", "99"], keys, directory, out, err) == 1
    assert directory.get(12).guardian_id == 1


def test_an_unknown_command_exits_with_usage():
    keys, directory, out, err = make()

    with pytest.raises(SystemExit):
        go(["nonsense"], keys, directory, out, err)


# ------------------------------------------------ guardian set-login


def _set_login(passwords, email="Real@Example.com", guardian="1", accounts=None):
    from app.api.guardian_accounts import InMemoryGuardianAccounts

    keys, directory, out, err = make()
    accounts = accounts or InMemoryGuardianAccounts()
    answers = iter(passwords)
    code = run(
        ["guardian", "set-login", guardian, "--email", email],
        keys=keys, directory=directory, out=out, err=err,
        accounts=accounts, read_password=lambda prompt: next(answers),
    )
    return code, accounts, out, err


def test_set_login_gives_the_guardian_an_email_and_a_hashed_password():
    from app.api.guardian_accounts import InMemoryGuardianAccounts
    from app.api.passwords import NO_LOGIN, verify_password

    accounts = InMemoryGuardianAccounts()
    gid = accounts.create("보호자", "key-ab@no-login.invalid", "010-0", NO_LOGIN)

    code, _, out, err = _set_login(["long-enough-1", "long-enough-1"], guardian=str(gid), accounts=accounts)

    assert code == 0 and not err.lines
    account = accounts.find_by_email("real@example.com")
    assert account.guardian_id == gid and verify_password("long-enough-1", account.password_hash)
    assert "long-enough-1" not in out.text and account.password_hash not in out.text


def test_set_login_refuses_short_or_mismatched_passwords():
    assert _set_login(["short"])[0] == 1
    assert _set_login(["long-enough-1", "long-enough-2"])[0] == 1


def test_set_login_refuses_a_missing_guardian_and_a_taken_email():
    from app.api.guardian_accounts import InMemoryGuardianAccounts

    assert _set_login(["long-enough-1", "long-enough-1"], guardian="99")[0] == 1
    accounts = InMemoryGuardianAccounts()
    accounts.create("가", "real@example.com", "010-1", "H")
    gid = accounts.create("나", "b@example.com", "010-2", "H2")
    code, _, _, err = _set_login(["long-enough-1", "long-enough-1"], guardian=str(gid), accounts=accounts)
    assert code == 1 and "이미" in err.text


def test_pending_lists_waiting_signups_and_activate_opens_one():
    from app.api.guardian_accounts import InMemoryGuardianAccounts

    keys, directory, out, err = make()
    accounts = InMemoryGuardianAccounts()
    gid = accounts.create("김보호", "kim@example.com", "010-1111-2222", "H")

    assert run(["guardian", "pending"], keys=keys, directory=directory, out=out, err=err, accounts=accounts) == 0
    assert "kim@example.com" in out.text and "010-1111-2222" in out.text

    assert run(["guardian", "activate", str(gid)], keys=keys, directory=directory, out=out, err=err, accounts=accounts) == 0
    assert accounts.profile(gid).activated is True
    out2 = Output()
    run(["guardian", "pending"], keys=keys, directory=directory, out=out2, err=err, accounts=accounts)
    assert "kim@example.com" not in out2.text


def test_verify_records_the_email_as_verified_and_pending_shows_the_state():
    from app.api.guardian_accounts import InMemoryGuardianAccounts

    keys, directory, out, err = make()
    accounts = InMemoryGuardianAccounts()
    gid = accounts.create("가", "a@example.com", "010-1", "H")
    out0 = Output()
    run(["guardian", "pending"], keys=keys, directory=directory, out=out0, err=err, accounts=accounts)
    assert "이메일 인증 대기" in out0.text

    assert run(["guardian", "verify", str(gid)], keys=keys, directory=directory, out=out, err=err, accounts=accounts) == 0
    assert accounts.profile(gid).email_verified is True
    assert str(gid) in out.text
    out2 = Output()
    run(["guardian", "pending"], keys=keys, directory=directory, out=out2, err=err, accounts=accounts)
    assert "이메일 인증됨" in out2.text and "이메일 인증 대기" not in out2.text


def test_verify_a_missing_guardian_fails():
    from app.api.guardian_accounts import InMemoryGuardianAccounts

    keys, directory, out, err = make()
    code = run(["guardian", "verify", "99"], keys=keys, directory=directory, out=out, err=err,
               accounts=InMemoryGuardianAccounts())
    assert code == 1 and err.text


# ------------------------------------------------ elder delete · guardian delete


class FakeDeleter:
    def __init__(self, failed=0):
        self.failed = failed
        self.calls = []

    def delete_many(self, keys):
        self.calls.append(list(keys))
        return self.failed


def _deletion_world():
    """보호자 1(계정·열쇠·폰·개인 코드, 어르신 12·13)과 보호자 2(어르신 14). 어르신 12에게 녹음 둘."""
    from app.api.devices import InMemoryDeviceStore
    from app.api.guardian_accounts import InMemoryGuardianAccounts
    from app.api.invites import InMemoryInviteStore, hash_invite_code

    keys = InMemoryGuardianKeyStore()
    keys.add(guardian_id=1, label="a", key_prefix="nlb_aaaaaaaa", key_hash="1" * 64)
    keys.add(guardian_id=2, label="b", key_prefix="nlb_bbbbbbbb", key_hash="2" * 64)
    directory = InMemoryElderDirectory(
        {12: ElderAccess(1, True, "김순자"), 13: ElderAccess(1, True, "이영희"), 14: ElderAccess(2, True, "박말순")},
        phones={12: "070-1111-2222", 13: "070-3333-4444", 14: "070-5555-6666"},
    )
    directory.add_audio_key(12, "12-a.wav")
    directory.add_audio_key(12, "12-b.wav")
    accounts = InMemoryGuardianAccounts()
    accounts.create("가", "a@example.com", "010-1", "H", activated=True)
    accounts.create("나", "b@example.com", "010-2", "H2", activated=True)
    devices = InMemoryDeviceStore()
    devices.register(1, "1" * 64, "token-aaaaaaaaaaaaaaaaaaaa")
    invites = InMemoryInviteStore()
    invites.issue(1, hash_invite_code("11111111"))
    return {
        "keys": keys, "directory": directory, "accounts": accounts, "devices": devices, "invites": invites,
        "deleter": FakeDeleter(), "code": hash_invite_code("11111111"),
    }


def _delete(world, argv):
    out, err = Output(), Output()
    code = run(
        argv, keys=world["keys"], directory=world["directory"], out=out, err=err, accounts=world["accounts"],
        devices=world["devices"], invites=world["invites"], recording_deleter=world["deleter"],
    )
    return code, out, err


def test_elder_delete_without_yes_deletes_nothing_and_explains():
    world = _deletion_world()

    code, out, err = _delete(world, ["elder", "delete", "12"])

    assert code == 1
    assert "--yes" in (out.text + err.text)
    assert world["directory"].get(12) is not None and world["deleter"].calls == []


def test_elder_delete_with_yes_removes_the_elder_and_its_recordings():
    world = _deletion_world()

    code, out, err = _delete(world, ["elder", "delete", "12", "--yes"])

    assert code == 0 and not err.lines
    assert world["directory"].get(12) is None and world["directory"].find_by_phone("070-1111-2222") is None
    assert world["deleter"].calls == [["12-a.wav", "12-b.wav"]]
    assert len(out.lines) == 1 and "어르신 12번" in out.text and "녹음 2개" in out.text and "실패 0개" in out.text
    assert world["directory"].get(13) is not None and world["directory"].get(14) is not None
    assert "김순자" not in out.text and "070-1111-2222" not in out.text and "12-a.wav" not in out.text


def test_elder_delete_reports_recordings_it_could_not_delete():
    world = _deletion_world()
    world["deleter"] = FakeDeleter(failed=1)

    code, out, _ = _delete(world, ["elder", "delete", "12", "--yes"])

    assert code == 0 and "실패 1" in out.text
    assert world["directory"].get(12) is None


def test_elder_delete_of_an_unknown_elder_fails():
    world = _deletion_world()

    code, _, err = _delete(world, ["elder", "delete", "99", "--yes"])

    assert code == 1 and "99" in err.text
    assert world["deleter"].calls == []


def test_guardian_delete_without_yes_deletes_nothing_and_explains():
    world = _deletion_world()

    code, out, err = _delete(world, ["guardian", "delete", "1"])

    assert code == 1
    assert "--yes" in (out.text + err.text)
    assert world["accounts"].profile(1) is not None
    assert world["directory"].get(12).guardian_id == 1
    assert world["keys"].find_guardian("1" * 64) == 1


def test_guardian_delete_with_yes_unlinks_the_elders_and_removes_the_account():
    world = _deletion_world()

    code, out, err = _delete(world, ["guardian", "delete", "1", "--yes"])

    assert code == 0 and not err.lines
    assert world["accounts"].profile(1) is None
    for elder_id in (12, 13):
        access = world["directory"].get(elder_id)
        assert access is not None and access.status == "unlinked"  # 어르신은 지우지 않는다
    assert world["keys"].find_guardian("1" * 64) is None
    assert world["devices"].tokens_for(1) == []
    assert world["invites"].find_guardian(world["code"]) is None
    assert world["deleter"].calls == []  # 녹음은 어르신 것이라 그대로다
    # 다른 보호자는 그대로다
    assert world["accounts"].profile(2) is not None and world["keys"].find_guardian("2" * 64) == 2
    assert world["directory"].get(14) == ElderAccess(2, True, "박말순")
    assert len(out.lines) == 1 and "보호자 1번" in out.text and "어르신 2명" in out.text  # 연결을 푼 어르신 수
    assert "a@example.com" not in out.text


def test_guardian_delete_of_an_unknown_guardian_fails():
    world = _deletion_world()

    code, _, err = _delete(world, ["guardian", "delete", "99", "--yes"])

    assert code == 1 and "99" in err.text
    assert world["accounts"].profile(1) is not None


def test_guardian_delete_needs_the_account_store():
    keys, directory, out, err = make()

    assert run(["guardian", "delete", "1", "--yes"], keys=keys, directory=directory, out=out, err=err) == 1
    assert directory.get(12).guardian_id == 1


def test_activate_a_missing_guardian_fails():
    from app.api.guardian_accounts import InMemoryGuardianAccounts

    keys, directory, out, err = make()
    code = run(["guardian", "activate", "99"], keys=keys, directory=directory, out=out, err=err,
               accounts=InMemoryGuardianAccounts())
    assert code == 1
