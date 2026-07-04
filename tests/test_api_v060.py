"""REST API integration tests for v0.6.0 endpoints: A/R Aging, Revenue Analytics, Estimates."""

import pytest
from datetime import date, timedelta
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

    def mock_get_service():
        return InvoiceService(InvoiceStore(data_dir=tmpdir))

    with patch("agent_invoice.api._get_service", mock_get_service):
        app = create_app()
        with TestClient(app) as c:
            yield c

    shutil.rmtree(tmpdir, ignore_errors=True)


def _create_client_and_invoice(client, name="Acme Corp", amount=500.0):
    """Helper: create client + invoice via API."""
    resp = client.post("/clients", json={"name": name, "email": "test@test.com", "currency": "USD"})
    assert resp.status_code == 201
    client_id = resp.json()["id"]

    resp = client.post("/invoices", json={
        "client": client_id,
        "items": [{"description": "Consulting", "quantity": 5, "unit_price": amount / 5}],
    })
    assert resp.status_code == 201
    invoice_id = resp.json()["id"]
    return client_id, invoice_id


# ============================================================================
# A/R Aging Report API Tests
# ============================================================================

class TestARAgingAPI:
    def test_get_ar_aging_report(self, client):
        _create_client_and_invoice(client)
        resp = client.get("/reports/ar-aging")
        assert resp.status_code == 200
        data = resp.json()
        assert "as_of_date" in data
        assert "bucket_totals" in data
        assert "clients" in data
        assert isinstance(data["clients"], list)

    def test_ar_aging_with_currency_filter(self, client):
        _create_client_and_invoice(client)
        resp = client.get("/reports/ar-aging?currency=USD")
        assert resp.status_code == 200
        assert resp.json()["currency"] == "USD"

    def test_ar_aging_empty(self, client):
        resp = client.get("/reports/ar-aging")
        assert resp.status_code == 200
        data = resp.json()
        assert data["client_count"] == 0
        assert data["total_outstanding"] == 0.0

    def test_ar_aging_has_four_buckets(self, client):
        _create_client_and_invoice(client)
        resp = client.get("/reports/ar-aging")
        data = resp.json()
        assert len(data["bucket_totals"]) == 4
        labels = [b["label"] for b in data["bucket_totals"]]
        assert "0-30" in labels
        assert "91+" in labels


# ============================================================================
# Revenue Analytics API Tests
# ============================================================================

class TestRevenueAnalyticsAPI:
    def test_get_revenue_report(self, client):
        _create_client_and_invoice(client)
        start = str(date.today() - timedelta(days=90))
        end = str(date.today())
        resp = client.get(f"/reports/revenue?period_start={start}&period_end={end}")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_invoiced" in data
        assert "collection_rate" in data
        assert "months" in data
        assert "top_clients" in data

    def test_revenue_report_with_currency(self, client):
        _create_client_and_invoice(client)
        start = str(date.today() - timedelta(days=90))
        end = str(date.today())
        resp = client.get(f"/reports/revenue?period_start={start}&period_end={end}&currency=USD")
        assert resp.status_code == 200
        assert resp.json()["currency"] == "USD"

    def test_revenue_invalid_date(self, client):
        resp = client.get("/reports/revenue?period_start=bad&period_end=alsobad")
        assert resp.status_code == 400

    def test_revenue_invalid_range(self, client):
        today = str(date.today())
        past = str(date.today() - timedelta(days=30))
        resp = client.get(f"/reports/revenue?period_start={today}&period_end={past}")
        assert resp.status_code == 400

    def test_revenue_missing_params(self, client):
        resp = client.get("/reports/revenue")
        assert resp.status_code == 422  # FastAPI validation error


# ============================================================================
# Estimate API Tests
# ============================================================================

class TestEstimatesAPI:
    def test_create_estimate(self, client):
        _create_client_and_invoice(client)
        resp = client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "Dev work", "quantity": 10, "unit_price": 100.0}],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"].startswith("EST-")
        assert data["status"] == "draft"
        assert data["subtotal"] == 1000.0

    def test_create_estimate_with_tax_discount(self, client):
        _create_client_and_invoice(client)
        resp = client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "Service", "quantity": 1, "unit_price": 200.0, "tax_rate": 10.0}],
            "discount_amount": 50.0,
            "terms": "Net 30",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["total"] == 170.0  # 200 + 20 tax - 50 discount

    def test_create_estimate_missing_client(self, client):
        resp = client.post("/estimates", json={
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 10}],
        })
        assert resp.status_code == 400
        assert "required" in resp.json()["detail"].lower()

    def test_create_estimate_invalid_client(self, client):
        resp = client.post("/estimates", json={
            "client": "Nonexistent Co",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 10}],
        })
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"]

    def test_list_estimates(self, client):
        _create_client_and_invoice(client)
        client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "A", "quantity": 1, "unit_price": 10}],
        })
        client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "B", "quantity": 1, "unit_price": 20}],
        })
        resp = client.get("/estimates")
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    def test_list_estimates_by_status(self, client):
        _create_client_and_invoice(client)
        # Create two estimates
        r1 = client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "A", "quantity": 1, "unit_price": 10}],
        })
        r2 = client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "B", "quantity": 1, "unit_price": 20}],
        })
        est2_id = r2.json()["id"]
        # Send the second one
        client.post(f"/estimates/{est2_id}/send")

        resp = client.get("/estimates?status=sent")
        assert resp.status_code == 200
        data = resp.json()
        assert all(e["status"] == "sent" for e in data)
        assert len(data) == 1

    def test_get_estimate(self, client):
        _create_client_and_invoice(client)
        create_resp = client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "Test item", "quantity": 2, "unit_price": 50.0}],
            "notes": "Test note",
        })
        est_id = create_resp.json()["id"]
        resp = client.get(f"/estimates/{est_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == est_id
        assert resp.json()["notes"] == "Test note"

    def test_get_estimate_not_found(self, client):
        resp = client.get("/estimates/EST-XXXXXX")
        assert resp.status_code == 404

    def test_send_estimate(self, client):
        _create_client_and_invoice(client)
        create_resp = client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 10}],
        })
        est_id = create_resp.json()["id"]
        resp = client.post(f"/estimates/{est_id}/send")
        assert resp.status_code == 200
        assert resp.json()["status"] == "sent"

    def test_accept_estimate(self, client):
        _create_client_and_invoice(client)
        create_resp = client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 10}],
        })
        est_id = create_resp.json()["id"]
        client.post(f"/estimates/{est_id}/send")
        resp = client.post(f"/estimates/{est_id}/accept")
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    def test_decline_estimate(self, client):
        _create_client_and_invoice(client)
        create_resp = client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 10}],
        })
        est_id = create_resp.json()["id"]
        resp = client.post(f"/estimates/{est_id}/decline")
        assert resp.status_code == 200
        assert resp.json()["status"] == "declined"

    def test_convert_estimate_to_invoice(self, client):
        _create_client_and_invoice(client)
        create_resp = client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "Service", "quantity": 5, "unit_price": 100.0}],
        })
        est_id = create_resp.json()["id"]
        client.post(f"/estimates/{est_id}/send")
        client.post(f"/estimates/{est_id}/accept")

        resp = client.post(f"/estimates/{est_id}/convert?due_days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert data["estimate"]["status"] == "converted"
        assert "invoice" in data
        assert data["invoice"]["subtotal"] == 500.0
        assert data["invoice"]["total"] == 500.0

    def test_delete_estimate(self, client):
        _create_client_and_invoice(client)
        create_resp = client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 10}],
        })
        est_id = create_resp.json()["id"]
        resp = client.delete(f"/estimates/{est_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        # Verify it's gone
        resp = client.get(f"/estimates/{est_id}")
        assert resp.status_code == 404

    def test_delete_estimate_not_found(self, client):
        resp = client.delete("/estimates/EST-XXXXXX")
        assert resp.status_code == 404

    def test_estimate_full_lifecycle(self, client):
        """Test full estimate lifecycle: create → send → accept → convert → verify invoice."""
        _create_client_and_invoice(client)
        # Create
        create_resp = client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "Big project", "quantity": 20, "unit_price": 250.0}],
            "terms": "Net 30",
        })
        assert create_resp.status_code == 201
        est_id = create_resp.json()["id"]
        assert create_resp.json()["total"] == 5000.0

        # Send
        resp = client.post(f"/estimates/{est_id}/send")
        assert resp.status_code == 200

        # Accept
        resp = client.post(f"/estimates/{est_id}/accept")
        assert resp.status_code == 200

        # Convert
        resp = client.post(f"/estimates/{est_id}/convert?due_days=45")
        assert resp.status_code == 200
        invoice_id = resp.json()["invoice"]["id"]

        # Verify invoice exists via invoice endpoint
        inv_resp = client.get(f"/invoices/{invoice_id}")
        assert inv_resp.status_code == 200
        # Invoice total is computed from line items
        line_items = inv_resp.json()["line_items"]
        computed_total = sum(li["quantity"] * li["unit_price"] for li in line_items)
        assert computed_total == 5000.0

        # Verify estimate is now converted
        est_resp = client.get(f"/estimates/{est_id}")
        assert est_resp.json()["status"] == "converted"
        assert est_resp.json()["converted_invoice_id"] == invoice_id
