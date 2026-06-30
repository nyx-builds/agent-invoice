"""Integration tests for the REST API — credit notes, statements, and search endpoints."""

import pytest
from fastapi.testclient import TestClient
from agent_invoice.api import create_app
from agent_invoice.store import InvoiceStore
from agent_invoice.service import InvoiceService
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def client():
    """Create a TestClient with a temporary data directory."""
    tmpdir = tempfile.mkdtemp()

    # Patch the _get_service to use our temp directory
    original_get_service = None

    def mock_get_service():
        return InvoiceService(InvoiceStore(data_dir=tmpdir))

    with patch("agent_invoice.api._get_service", mock_get_service):
        app = create_app()
        with TestClient(app) as c:
            yield c

    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def setup_data(client):
    """Create a client and invoice via API for testing."""
    # Create client
    resp = client.post("/clients", json={"name": "API Test Co", "email": "test@api.co", "currency": "USD"})
    assert resp.status_code == 201
    client_id = resp.json()["id"]

    # Create invoice
    resp = client.post("/invoices", json={
        "client": client_id,
        "items": [{"description": "Consulting", "quantity": 10, "unit_price": 100.0}],
    })
    assert resp.status_code == 201
    invoice_id = resp.json()["id"]

    return client_id, invoice_id


class TestCreditNoteAPI:
    def test_create_credit_note(self, client, setup_data):
        client_id, invoice_id = setup_data
        resp = client.post("/credit-notes", json={
            "client": client_id,
            "amount": 250.0,
            "reason": "overpayment",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["amount"] == 250.0
        assert data["status"] == "open"
        assert data["remaining"] == 250.0

    def test_create_credit_note_bad_client(self, client):
        resp = client.post("/credit-notes", json={
            "client": "nope",
            "amount": 100.0,
        })
        assert resp.status_code == 400

    def test_list_credit_notes(self, client, setup_data):
        client_id, _ = setup_data
        client.post("/credit-notes", json={"client": client_id, "amount": 100.0})
        client.post("/credit-notes", json={"client": client_id, "amount": 200.0})
        resp = client.get("/credit-notes")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_credit_note(self, client, setup_data):
        client_id, _ = setup_data
        resp = client.post("/credit-notes", json={"client": client_id, "amount": 100.0})
        credit_id = resp.json()["id"]
        resp = client.get(f"/credit-notes/{credit_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == credit_id

    def test_get_credit_note_not_found(self, client):
        resp = client.get("/credit-notes/CN-NOPE")
        assert resp.status_code == 404

    def test_apply_credit_note(self, client, setup_data):
        client_id, invoice_id = setup_data
        # Create credit note
        resp = client.post("/credit-notes", json={"client": client_id, "amount": 1000.0})
        credit_id = resp.json()["id"]
        # Apply to invoice
        resp = client.post(f"/credit-notes/{credit_id}/apply", json={"invoice_id": invoice_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["credit_note"]["applied_amount"] == 1000.0
        assert data["invoice"]["status"] == "paid"

    def test_void_credit_note(self, client, setup_data):
        client_id, _ = setup_data
        resp = client.post("/credit-notes", json={"client": client_id, "amount": 100.0})
        credit_id = resp.json()["id"]
        resp = client.post(f"/credit-notes/{credit_id}/void")
        assert resp.status_code == 200
        assert resp.json()["status"] == "void"

    def test_delete_credit_note(self, client, setup_data):
        client_id, _ = setup_data
        resp = client.post("/credit-notes", json={"client": client_id, "amount": 100.0})
        credit_id = resp.json()["id"]
        resp = client.delete(f"/credit-notes/{credit_id}")
        assert resp.status_code == 200
        # Verify it's gone
        resp = client.get(f"/credit-notes/{credit_id}")
        assert resp.status_code == 404


class TestClientStatementAPI:
    def test_get_statement(self, client, setup_data):
        client_id, _ = setup_data
        from datetime import date, timedelta
        today = date.today()
        resp = client.get(f"/clients/{client_id}/statement", params={
            "period_start": today.isoformat(),
            "period_end": (today + timedelta(days=365)).isoformat(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["client_id"] == client_id
        assert data["total_invoiced"] == 1000.0

    def test_statement_invalid_date(self, client, setup_data):
        client_id, _ = setup_data
        resp = client.get(f"/clients/{client_id}/statement", params={
            "period_start": "not-a-date",
            "period_end": "2026-01-01",
        })
        assert resp.status_code == 400


class TestInvoiceSearchAPI:
    def test_search_invoices_by_text(self, client, setup_data):
        resp = client.get("/invoices", params={"search": "Consulting"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

    def test_search_invoices_by_amount(self, client, setup_data):
        resp = client.get("/invoices", params={"min_amount": 500.0})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

    def test_search_invoices_by_date(self, client, setup_data):
        from datetime import date
        resp = client.get("/invoices", params={"date_from": date.today().isoformat()})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_search_no_results(self, client, setup_data):
        resp = client.get("/invoices", params={"search": "nonexistent"})
        assert resp.status_code == 200
        assert len(resp.json()) == 0
