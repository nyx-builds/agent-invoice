"""REST API integration tests for v0.7.0 endpoints: Expenses, Profit Analysis,
Tax Summary, Bulk Operations, Estimate PDF Export."""

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


def _setup_data(client):
    """Helper: create clients, invoices, payments, and expenses for testing."""
    # Client A
    resp = client.post("/clients", json={"name": "Client A", "email": "a@test.com", "currency": "USD"})
    assert resp.status_code == 201
    client_a_id = resp.json()["id"]

    # Client B
    resp = client.post("/clients", json={"name": "Client B", "email": "b@test.com", "currency": "USD"})
    assert resp.status_code == 201
    client_b_id = resp.json()["id"]

    # Invoice 1 — Client A, $1000 + 10% tax = $1100, paid
    resp = client.post("/invoices", json={
        "client": "Client A",
        "items": [{"description": "Consulting", "quantity": 10, "unit_price": 100.0, "tax_rate": 10.0}],
        "tax_rate": 10.0,
        "due_days": 30,
    })
    assert resp.status_code == 201
    inv1_id = resp.json()["id"]

    # Mark sent + pay
    client.post(f"/invoices/{inv1_id}/send")
    client.post(f"/invoices/{inv1_id}/payments", json={"amount": 1100.0, "method": "bank_transfer"})

    # Invoice 2 — Client B, $1000, sent only (unpaid)
    resp = client.post("/invoices", json={
        "client": "Client B",
        "items": [{"description": "Development", "quantity": 5, "unit_price": 200.0}],
        "due_days": 30,
    })
    assert resp.status_code == 201
    inv2_id = resp.json()["id"]
    client.post(f"/invoices/{inv2_id}/send")

    # Expenses
    client.post("/expenses", json={
        "description": "OpenAI API credits", "amount": 500.0,
        "category": "api_costs", "vendor": "OpenAI",
    })
    client.post("/expenses", json={
        "description": "AWS hosting", "amount": 300.0,
        "category": "infrastructure", "vendor": "AWS",
    })
    client.post("/expenses", json={
        "description": "JetBrains license", "amount": 150.0,
        "category": "software", "vendor": "JetBrains",
    })

    return {
        "client_a_id": client_a_id,
        "client_b_id": client_b_id,
        "inv1_id": inv1_id,
        "inv2_id": inv2_id,
    }


# =========================================================================
# Expense CRUD API Tests
# =========================================================================

class TestExpenseAPI:
    def test_create_expense(self, client):
        resp = client.post("/expenses", json={
            "description": "Test expense",
            "amount": 100.0,
            "category": "software",
            "vendor": "TestVendor",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"].startswith("EXP-")
        assert data["amount"] == 100.0
        assert data["category"] == "software"
        assert data["vendor"] == "TestVendor"

    def test_create_expense_invalid_currency(self, client):
        resp = client.post("/expenses", json={
            "description": "Test",
            "amount": 100.0,
            "currency": "XYZ",
        })
        assert resp.status_code == 400

    def test_create_expense_negative_amount(self, client):
        resp = client.post("/expenses", json={
            "description": "Test",
            "amount": -50.0,
        })
        assert resp.status_code == 400

    def test_list_expenses(self, client):
        client.post("/expenses", json={"description": "E1", "amount": 10.0})
        client.post("/expenses", json={"description": "E2", "amount": 20.0, "category": "software"})
        client.post("/expenses", json={"description": "E3", "amount": 30.0, "category": "api_costs"})

        resp = client.get("/expenses")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_list_expenses_filter_category(self, client):
        client.post("/expenses", json={"description": "E1", "amount": 10.0, "category": "software"})
        client.post("/expenses", json={"description": "E2", "amount": 20.0, "category": "api_costs"})

        resp = client.get("/expenses", params={"category": "software"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["category"] == "software"

    def test_get_expense(self, client):
        create_resp = client.post("/expenses", json={"description": "Test", "amount": 50.0})
        exp_id = create_resp.json()["id"]

        resp = client.get(f"/expenses/{exp_id}")
        assert resp.status_code == 200
        assert resp.json()["description"] == "Test"

    def test_get_expense_not_found(self, client):
        resp = client.get("/expenses/EXP-NOPE")
        assert resp.status_code == 404

    def test_update_expense(self, client):
        create_resp = client.post("/expenses", json={"description": "Original", "amount": 100.0})
        exp_id = create_resp.json()["id"]

        resp = client.put(f"/expenses/{exp_id}", json={"description": "Updated", "amount": 200.0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "Updated"
        assert data["amount"] == 200.0

    def test_update_expense_not_found(self, client):
        resp = client.put("/expenses/EXP-NOPE", json={"amount": 200.0})
        assert resp.status_code == 400

    def test_delete_expense(self, client):
        create_resp = client.post("/expenses", json={"description": "Test", "amount": 50.0})
        exp_id = create_resp.json()["id"]

        resp = client.delete(f"/expenses/{exp_id}")
        assert resp.status_code == 200

        # Verify gone
        resp = client.get(f"/expenses/{exp_id}")
        assert resp.status_code == 404

    def test_delete_expense_not_found(self, client):
        resp = client.delete("/expenses/EXP-NOPE")
        assert resp.status_code == 404

    def test_expense_summary(self, client):
        _setup_data(client)
        resp = client.get("/expenses/summary", params={"currency": "USD"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 950.0  # 500 + 300 + 150
        assert data["expense_count"] == 3
        assert len(data["breakdown"]) == 3

    def test_expense_summary_empty(self, client):
        resp = client.get("/expenses/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0.0
        assert data["expense_count"] == 0


# =========================================================================
# Profit Analysis API Tests
# =========================================================================

class TestProfitAnalysisAPI:
    def test_profit_report(self, client):
        _setup_data(client)
        resp = client.get("/reports/profit", params={"currency": "USD"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_revenue"] == 1100.0  # From paid invoice
        assert data["total_expenses"] == 950.0  # 500 + 300 + 150
        assert data["gross_profit"] == 150.0
        assert len(data["client_profitability"]) == 2

    def test_profit_report_empty(self, client):
        resp = client.get("/reports/profit", params={"currency": "USD"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_revenue"] == 0.0
        assert data["total_expenses"] == 0.0

    def test_profit_report_with_period(self, client):
        _setup_data(client)
        resp = client.get("/reports/profit", params={
            "currency": "USD",
            "period_start": "2026-01-01",
            "period_end": str(date.today()),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_expenses"] > 0


# =========================================================================
# Tax Summary API Tests
# =========================================================================

class TestTaxSummaryAPI:
    def test_tax_summary(self, client):
        _setup_data(client)
        resp = client.get("/reports/tax-summary", params={
            "period_start": "2026-01-01",
            "period_end": str(date.today() + timedelta(days=365)),
            "currency": "USD",
        })
        assert resp.status_code == 200
        data = resp.json()
        # 2 invoices: inv1 ($1000 + $100 tax), inv2 ($1000 no tax)
        assert data["total_invoiced"] == 2000.0
        assert data["total_tax_collected"] == 100.0
        assert data["total_tax_from_paid"] == 100.0
        assert len(data["tax_by_rate"]) > 0

    def test_tax_summary_deductible_expenses(self, client):
        _setup_data(client)
        resp = client.get("/reports/tax-summary", params={
            "period_start": "2026-01-01",
            "period_end": str(date.today() + timedelta(days=365)),
            "currency": "USD",
        })
        data = resp.json()
        assert data["tax_deductible_expenses"] == 950.0  # 500+300+150
        assert data["net_taxable_income"] == 1050.0  # 2000 - 950

    def test_tax_summary_empty(self, client):
        resp = client.get("/reports/tax-summary", params={
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_invoiced"] == 0.0


# =========================================================================
# Bulk Operations API Tests
# =========================================================================

class TestBulkOperationsAPI:
    def test_bulk_mark_sent(self, client):
        # Create invoices
        client.post("/clients", json={"name": "Client A", "currency": "USD"})
        client.post("/clients", json={"name": "Client B", "currency": "USD"})

        resp1 = client.post("/invoices", json={
            "client": "Client A",
            "items": [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        })
        resp2 = client.post("/invoices", json={
            "client": "Client B",
            "items": [{"description": "Work", "quantity": 1, "unit_price": 200.0}],
        })
        inv1_id = resp1.json()["id"]
        inv2_id = resp2.json()["id"]

        resp = client.post("/invoices/bulk/send", json={"invoice_ids": [inv1_id, inv2_id]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["success"]) == 2
        assert len(data["errors"]) == 0

    def test_bulk_mark_sent_partial_failure(self, client):
        client.post("/clients", json={"name": "Client A", "currency": "USD"})
        resp1 = client.post("/invoices", json={
            "client": "Client A",
            "items": [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        })
        inv1_id = resp1.json()["id"]

        resp = client.post("/invoices/bulk/send", json={"invoice_ids": [inv1_id, "INV-NOPE"]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["success"]) == 1
        assert len(data["errors"]) == 1

    def test_bulk_mark_paid(self, client):
        client.post("/clients", json={"name": "Client A", "currency": "USD"})
        client.post("/clients", json={"name": "Client B", "currency": "USD"})

        resp1 = client.post("/invoices", json={
            "client": "Client A",
            "items": [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        })
        resp2 = client.post("/invoices", json={
            "client": "Client B",
            "items": [{"description": "Work", "quantity": 1, "unit_price": 200.0}],
        })
        inv1_id = resp1.json()["id"]
        inv2_id = resp2.json()["id"]

        # Send first
        client.post("/invoices/bulk/send", json={"invoice_ids": [inv1_id, inv2_id]})

        resp = client.post("/invoices/bulk/pay", json={"invoice_ids": [inv1_id, inv2_id]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["success"]) == 2

    def test_bulk_cancel(self, client):
        client.post("/clients", json={"name": "Client A", "currency": "USD"})
        client.post("/clients", json={"name": "Client B", "currency": "USD"})

        resp1 = client.post("/invoices", json={
            "client": "Client A",
            "items": [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        })
        resp2 = client.post("/invoices", json={
            "client": "Client B",
            "items": [{"description": "Work", "quantity": 1, "unit_price": 200.0}],
        })

        resp = client.post("/invoices/bulk/cancel", json={
            "invoice_ids": [resp1.json()["id"], resp2.json()["id"]]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["success"]) == 2

    def test_bulk_export_markdown(self, client):
        client.post("/clients", json={"name": "Client A", "currency": "USD"})
        resp1 = client.post("/invoices", json={
            "client": "Client A",
            "items": [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        })
        inv1_id = resp1.json()["id"]

        resp = client.post("/invoices/bulk/export", json={
            "invoice_ids": [inv1_id],
            "format": "markdown",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["exports"]) == 1
        assert data["exports"][0]["format"] == "markdown"
        assert "Invoice" in data["exports"][0]["content"]

    def test_bulk_export_json(self, client):
        client.post("/clients", json={"name": "Client A", "currency": "USD"})
        resp1 = client.post("/invoices", json={
            "client": "Client A",
            "items": [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        })
        inv1_id = resp1.json()["id"]

        resp = client.post("/invoices/bulk/export", json={
            "invoice_ids": [inv1_id],
            "format": "json",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["exports"][0]["format"] == "json"

    def test_bulk_export_partial_failure(self, client):
        client.post("/clients", json={"name": "Client A", "currency": "USD"})
        resp1 = client.post("/invoices", json={
            "client": "Client A",
            "items": [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        })
        inv1_id = resp1.json()["id"]

        resp = client.post("/invoices/bulk/export", json={
            "invoice_ids": [inv1_id, "INV-NOPE"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["exports"]) == 1
        assert len(data["errors"]) == 1


# =========================================================================
# Estimate PDF Export API Tests
# =========================================================================

class TestEstimatePDFAPI:
    def test_export_estimate_pdf(self, client):
        # Create client + estimate
        client.post("/clients", json={"name": "Acme Corp", "currency": "USD"})
        est_resp = client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "Design work", "quantity": 10, "unit_price": 150.0}],
            "currency": "USD",
        })
        assert est_resp.status_code == 201
        est_id = est_resp.json()["id"]

        resp = client.post(f"/estimates/{est_id}/pdf", json={
            "company_name": "Test Co",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["estimate_id"] == est_id
        assert "pdf_path" in data
        assert data["pdf_path"].endswith(".pdf")

    def test_export_estimate_pdf_not_found(self, client):
        resp = client.post("/estimates/EST-NOPE/pdf", json={})
        assert resp.status_code == 404

    def test_export_estimate_pdf_with_output_path(self, client):
        client.post("/clients", json={"name": "Acme Corp", "currency": "USD"})
        est_resp = client.post("/estimates", json={
            "client": "Acme Corp",
            "line_items": [{"description": "Design", "quantity": 1, "unit_price": 500.0}],
        })
        est_id = est_resp.json()["id"]

        output_path = str(Path(tempfile.mkdtemp()) / "custom_estimate.pdf")
        resp = client.post(f"/estimates/{est_id}/pdf", json={"output_path": output_path})
        assert resp.status_code == 200
        assert resp.json()["pdf_path"] == output_path
        assert Path(output_path).exists()
