"""ADR 0017: the in-app agent. Claude is replaced by a scripted fake —
these tests cover the loop, the tools and the proposal/apply contract,
not the model."""

import json
from types import SimpleNamespace

import pytest

from app import agent_service
from app.models import AgentProposal, Txn


class FakeBlock:
    def __init__(self, **data):
        self.data = data
        self.type = data["type"]

    def model_dump(self, **_):
        return dict(self.data)


def text(t):
    return FakeBlock(type="text", text=t)


def tool(id_, name, input_):
    return FakeBlock(type="tool_use", id=id_, name=name, input=input_)


def response(*blocks, stop="tool_use"):
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop,
        usage=SimpleNamespace(
            input_tokens=100, output_tokens=20,
            cache_read_input_tokens=0, cache_creation_input_tokens=0,
        ),
    )


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs["messages"])))
        return self.script.pop(0)


@pytest.fixture
def fake_claude(monkeypatch):
    def install(*script):
        client = FakeClient(script)
        monkeypatch.setattr(agent_service, "_client", lambda: client)
        return client

    return install


def _cash_account(client, headers):
    return client.post(
        "/api/accounts",
        json={"name": "Giro", "type": "CASH", "currency": "EUR"},
        headers=headers,
    ).json()


def _conversation(client, headers):
    return client.post("/api/agent/conversations", headers=headers).json()


def _balance_create(account_id, amount="1000.00"):
    return {
        "date": "2025-03-31", "type": "BALANCE_STATEMENT", "account_id": account_id,
        "amount": amount, "currency": "EUR",
    }


def test_status_reports_unconfigured(client, auth_headers):
    body = client.get("/api/agent/status", headers=auth_headers).json()
    assert body["configured"] is False


def test_message_without_api_key_is_503(client, auth_headers):
    conv = _conversation(client, auth_headers)
    resp = client.post(
        f"/api/agent/conversations/{conv['id']}/messages", json={"text": "hi"}, headers=auth_headers
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "agent_not_configured"


def test_proposal_is_not_written_until_applied(client, auth_headers, fake_claude, db_session):
    account = _cash_account(client, auth_headers)
    fake = fake_claude(
        response(tool("t1", "list_accounts", {})),
        response(
            text("Booking the balance."),
            tool("t2", "propose_changes",
                 {"summary": "Giro balance", "creates": [_balance_create(account["id"])]}),
        ),
        response(text("Proposed, waiting for you."), stop="end_turn"),
    )
    conv = _conversation(client, auth_headers)

    resp = client.post(
        f"/api/agent/conversations/{conv['id']}/messages",
        json={"text": "Balance is 1.000,00", "images": [{"media_type": "image/png", "data": "aGk="}]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()

    # list_accounts really ran and its result went back to the model
    tool_result = fake.requests[1][-1]["content"][0]
    assert tool_result["tool_use_id"] == "t1"
    assert "Giro" in tool_result["content"]

    roles = [(i["role"], i["text"], i["image_count"]) for i in body["items"]]
    assert roles[0] == ("user", "Balance is 1.000,00", 1)
    [proposal_item] = [i for i in body["items"] if i["proposal"]]
    proposal = proposal_item["proposal"]
    assert proposal["status"] == "pending"
    assert proposal["preview"][0]["action"] == "create"
    assert proposal["preview"][0]["after"]["amount_eur"] == "1000.00"
    assert proposal["preview"][0]["account_name"] == "Giro"
    assert body["items"][-1]["text"] == "Proposed, waiting for you."

    assert db_session.query(Txn).count() == 0  # the dry run was rolled back

    resp = client.post(f"/api/agent/proposals/{proposal['id']}/apply", headers=auth_headers)
    assert resp.status_code == 200, resp.json()
    assert resp.json()["status"] == "applied"
    [txn] = db_session.query(Txn).all()
    assert txn.source.value == "agent"
    assert txn.external_id.startswith("agent-")

    resp = client.post(f"/api/agent/proposals/{proposal['id']}/apply", headers=auth_headers)
    assert resp.status_code == 409


def test_invalid_proposal_goes_back_to_the_model(client, auth_headers, fake_claude, db_session):
    fake = fake_claude(
        response(tool("t1", "propose_changes",
                      {"summary": "x", "creates": [_balance_create(account_id=999)]})),
        response(text("That account does not exist."), stop="end_turn"),
    )
    conv = _conversation(client, auth_headers)
    client.post(
        f"/api/agent/conversations/{conv['id']}/messages", json={"text": "go"}, headers=auth_headers
    )

    result = fake.requests[1][-1]["content"][0]
    assert result["is_error"] is True
    assert json.loads(result["content"])["error"]["code"] == "unknown_account"
    assert db_session.query(AgentProposal).count() == 0


def test_update_confirms_a_provisional_row(client, auth_headers, fake_claude, db_session):
    account = _cash_account(client, auth_headers)
    created = client.post(
        "/api/transactions",
        json={**_balance_create(account["id"], "500.00"), "external_id": "x-1", "provisional": True},
        headers=auth_headers,
    ).json()
    fake_claude(
        response(tool("t1", "propose_changes", {
            "summary": "Confirm",
            "updates": [{"transaction_id": created["id"], "provisional": False, "note": "confirmed"}],
        })),
        response(text("ok"), stop="end_turn"),
    )
    conv = _conversation(client, auth_headers)
    body = client.post(
        f"/api/agent/conversations/{conv['id']}/messages", json={"text": "go"}, headers=auth_headers
    ).json()
    proposal = next(i["proposal"] for i in body["items"] if i["proposal"])
    assert proposal["preview"][0]["before"]["provisional"] is True
    assert proposal["preview"][0]["after"]["provisional"] is False
    assert db_session.get(Txn, created["id"]).provisional is True  # untouched until applied

    client.post(f"/api/agent/proposals/{proposal['id']}/apply", headers=auth_headers)
    db_session.expire_all()
    assert db_session.get(Txn, created["id"]).provisional is False


def test_apply_revalidates_against_the_current_ledger(client, auth_headers, fake_claude):
    account = _cash_account(client, auth_headers)
    created = client.post(
        "/api/transactions",
        json={**_balance_create(account["id"]), "external_id": "x-1"},
        headers=auth_headers,
    ).json()
    fake_claude(
        response(tool("t1", "propose_changes", {
            "summary": "Delete it",
            "deletes": [{"transaction_id": created["id"], "reason": "duplicate"}],
        })),
        response(text("ok"), stop="end_turn"),
    )
    conv = _conversation(client, auth_headers)
    body = client.post(
        f"/api/agent/conversations/{conv['id']}/messages", json={"text": "go"}, headers=auth_headers
    ).json()
    proposal = next(i["proposal"] for i in body["items"] if i["proposal"])

    # deleted by hand in the meantime
    client.delete(f"/api/transactions/{created['id']}", headers=auth_headers)

    resp = client.post(f"/api/agent/proposals/{proposal['id']}/apply", headers=auth_headers)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "transaction_not_found"
    conv_after = client.get(f"/api/agent/conversations/{conv['id']}", headers=auth_headers).json()
    after = next(i["proposal"] for i in conv_after["items"] if i["proposal"])
    assert after["status"] == "pending"
    assert after["error"]["code"] == "transaction_not_found"


def test_decisions_are_reported_on_the_next_turn(client, auth_headers, fake_claude):
    account = _cash_account(client, auth_headers)
    fake = fake_claude(
        response(tool("t1", "propose_changes",
                      {"summary": "b", "creates": [_balance_create(account["id"])]})),
        response(text("waiting"), stop="end_turn"),
        response(text("thanks"), stop="end_turn"),
    )
    conv = _conversation(client, auth_headers)
    body = client.post(
        f"/api/agent/conversations/{conv['id']}/messages", json={"text": "go"}, headers=auth_headers
    ).json()
    proposal = next(i["proposal"] for i in body["items"] if i["proposal"])
    client.post(f"/api/agent/proposals/{proposal['id']}/reject", headers=auth_headers)

    body = client.post(
        f"/api/agent/conversations/{conv['id']}/messages", json={"text": "next"}, headers=auth_headers
    ).json()
    last_user = fake.requests[-1][-1]
    assert last_user["content"][0]["text"] == f"[App notice — proposal {proposal['id']}: rejected]"
    # the notice is for the model, not shown in the chat
    assert [i["text"] for i in body["items"] if i["role"] == "user"] == ["go", "next"]


def test_readonly_token_cannot_talk_or_apply(client, readonly_headers):
    assert client.post("/api/agent/conversations", headers=readonly_headers).status_code == 403
    assert client.post("/api/agent/proposals/1/apply", headers=readonly_headers).status_code == 403


def test_tools_cannot_reach_beyond_the_ledger():
    from app.agent_tools import TOOLS

    names = {t["name"] for t in TOOLS}
    assert names == {
        "list_accounts", "list_instruments", "get_positions", "list_transactions",
        "list_recurring_bookings", "propose_changes",
    }
