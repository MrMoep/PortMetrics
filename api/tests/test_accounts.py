from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
from sqlalchemy import select

from portmetrics.db.models import Account, SyncState
from portmetrics.ghostfolio.client import GhostfolioAccount, GhostfolioClient
from portmetrics.sync.accounts import (
    GHOSTFOLIO_ACCOUNTS_SOURCE,
    list_accounts,
    prune_orphan_accounts,
    sync_ghostfolio_accounts,
    upsert_accounts,
)


def sample_account_payload(**overrides) -> dict:
    base = {
        "id": "acc-comdirect",
        "name": "Comdirect Depot",
        "currency": "EUR",
        "balance": 0,
        "comment": None,
        "platformId": None,
        "platform": None,
    }
    base.update(overrides)
    return base


def test_ghostfolio_account_from_api() -> None:
    account = GhostfolioAccount.from_api(
        sample_account_payload(
            platform={"id": "plat-1", "name": "comdirect"},
            platformId="plat-1",
        )
    )
    assert account.id == "acc-comdirect"
    assert account.name == "Comdirect Depot"
    assert account.platform_id == "plat-1"
    assert account.platform_name == "comdirect"


def test_list_accounts_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/anonymous"):
            return httpx.Response(200, json={"authToken": "jwt-test"})
        if request.url.path.endswith("/account"):
            return httpx.Response(
                200,
                json={
                    "accounts": [
                        sample_account_payload(),
                        sample_account_payload(id="acc-2", name="Nürnberger"),
                    ]
                },
            )
        raise AssertionError(request.url.path)

    transport = httpx.MockTransport(handler)
    client = GhostfolioClient("http://ghostfolio.test", "secret", transport=transport)
    accounts = client.list_accounts()
    assert len(accounts) == 2
    assert accounts[0].name == "Comdirect Depot"


def test_upsert_and_list_accounts(db_session) -> None:
    items = [
        GhostfolioAccount.from_api(sample_account_payload()),
        GhostfolioAccount.from_api(sample_account_payload(id="acc-2", name="B")),
    ]
    assert upsert_accounts(db_session, items) == 2
    db_session.flush()

    listed = list_accounts(db_session)
    assert [row["id"] for row in listed] == ["acc-2", "acc-comdirect"]
    assert listed[1]["name"] == "Comdirect Depot"


def test_upsert_accounts_updates_name(db_session) -> None:
    first = GhostfolioAccount.from_api(sample_account_payload())
    upsert_accounts(db_session, [first])
    db_session.flush()

    updated = GhostfolioAccount.from_api(sample_account_payload(name="Comdirect Neu"))
    upsert_accounts(db_session, [updated])
    db_session.flush()

    row = db_session.scalars(select(Account)).one()
    assert row.name == "Comdirect Neu"


def test_prune_orphan_accounts(db_session) -> None:
    upsert_accounts(
        db_session,
        [
            GhostfolioAccount.from_api(sample_account_payload()),
            GhostfolioAccount.from_api(sample_account_payload(id="gone", name="Gone")),
        ],
    )
    db_session.flush()
    deleted = prune_orphan_accounts(db_session, remote_ids={"acc-comdirect"})
    assert deleted == 1
    assert db_session.scalars(select(Account.id)).all() == ["acc-comdirect"]


def test_prune_skips_wipe_on_empty_remote(db_session) -> None:
    upsert_accounts(db_session, [GhostfolioAccount.from_api(sample_account_payload())])
    db_session.flush()
    deleted = prune_orphan_accounts(db_session, remote_ids=set())
    assert deleted == 0
    assert db_session.scalars(select(Account)).one().id == "acc-comdirect"


def test_sync_ghostfolio_accounts(db_session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/anonymous"):
            return httpx.Response(200, json={"authToken": "jwt"})
        if request.url.path.endswith("/account"):
            return httpx.Response(200, json={"accounts": [sample_account_payload()]})
        raise AssertionError(request.url.path)

    client = GhostfolioClient(
        "http://ghostfolio.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    result = sync_ghostfolio_accounts(db_session, client)
    db_session.flush()

    assert result.fetched == 1
    assert result.upserted == 1
    assert result.deleted == 0
    state = db_session.scalar(
        select(SyncState).where(SyncState.source == GHOSTFOLIO_ACCOUNTS_SOURCE)
    )
    assert state is not None
    assert state.meta == {"fetched": 1, "upserted": 1, "deleted": 0}


def test_get_accounts_api(api_db) -> None:
    client, SessionLocal = api_db
    with SessionLocal() as session:
        session.add(
            Account(
                id="acc-1",
                name="Comdirect Depot",
                currency="EUR",
                balance=Decimal("0"),
                synced_at=datetime.now(UTC),
            )
        )
        session.commit()

    response = client.get("/api/accounts")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["accounts"][0]["name"] == "Comdirect Depot"
    assert body["accounts"][0]["id"] == "acc-1"
