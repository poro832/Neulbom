"""ContactStore 규약 — 구현마다 같은 테스트를 돌린다."""

from __future__ import annotations

import pytest

from app.api.contacts import MAX_CONTACTS, InMemoryContactStore, TooManyContacts
from tests.pg_helpers import DATABASE_URL


def _memory():
    return InMemoryContactStore()


def _postgres():
    from app.api.postgres_contacts import PostgresContactStore
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)
    return PostgresContactStore(pool=pool)


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다"),
        ),
    ]
)
def store(request):
    return _memory() if request.param == "memory" else _postgres()


def test_an_added_contact_is_listed_with_its_fields(store):
    created = store.add(12, name="이웃 김씨", relation="이웃", phone="010-1234-5678")

    assert store.list(12) == [created]
    assert (created.name, created.relation, created.phone) == ("이웃 김씨", "이웃", "010-1234-5678")


def test_contacts_are_listed_in_the_order_they_were_added(store):
    a = store.add(12, name="가", relation="", phone="111-1111")
    b = store.add(12, name="나", relation="", phone="222-2222")

    assert [c.contact_id for c in store.list(12)] == [a.contact_id, b.contact_id]


def test_each_elder_sees_only_their_own_contacts(store):
    store.add(12, name="가", relation="", phone="111-1111")

    assert store.list(13) == []


def test_removing_deletes_only_that_contact(store):
    a = store.add(12, name="가", relation="", phone="111-1111")
    b = store.add(12, name="나", relation="", phone="222-2222")

    assert store.remove(12, a.contact_id) is True

    assert [c.contact_id for c in store.list(12)] == [b.contact_id]


def test_another_elders_contact_cannot_be_removed(store):
    mine = store.add(12, name="가", relation="", phone="111-1111")

    assert store.remove(13, mine.contact_id) is False
    assert store.list(12) == [mine]


def test_removing_a_missing_contact_is_false(store):
    assert store.remove(12, 424242) is False


def test_the_twenty_first_contact_is_refused(store):
    for i in range(MAX_CONTACTS):
        store.add(12, name=f"c{i}", relation="", phone="111-1111")

    with pytest.raises(TooManyContacts):
        store.add(12, name="넘침", relation="", phone="111-1111")

    assert len(store.list(12)) == MAX_CONTACTS
    store.add(13, name="다른 어르신은 괜찮다", relation="", phone="111-1111")
