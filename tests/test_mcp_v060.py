"""MCP server tests for v0.6.0 tools: A/R Aging, Revenue Analytics, and Estimates."""

import asyncio
import json
import pytest
from datetime import date, timedelta

from agent_invoice.mcp_server import call_tool, list_tools
from agent_invoice.service import InvoiceService
from agent_invoice.store import InvoiceStore
import shutil
import tempfile
from unittest.mock import patch


@pytest.fixture
def temp_svc():
    """Create a service with a temporary data directory."""
    tmpdir = tempfile.mkdtemp()
    service = InvoiceService(InvoiceStore(data_dir=tmpdir))
    yield service
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture(autouse=True)
def mock_service(temp_svc):
    """Patch _get_service to return our temp service."""
    with patch("agent_invoice.mcp_server._get_service", return_value=temp_svc):
        yield temp_svc


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _setup_data(svc):
    """Create clients, invoices, and payments for testing."""
    svc.create_client(name="Acme Corp", email="billing@acme.com", currency="USD")
    svc.create_client(name="Globex", email="pay@globex.com", currency="USD")

    # Acme invoice, issued 60 days ago, 30-day terms, partially paid
    inv1 = svc.create_invoice(
        client_identifier="Acme Corp",
        line_items=[{"description": "API calls", "quantity": 100, "unit_price": 2.00}],
        due_days=30,
    )
    inv1.issue_date = date.today() - timedelta(days=60)
    inv1.due_date = date.today() - timedelta(days=30)
    inv1 = svc.store.save_invoice(inv1)
    svc.record_payment(inv1.id, amount=50.0, method="bank_transfer")

    # Globex invoice, issued 100 days ago, 30-day terms, unpaid
    inv2 = svc.create_invoice(
        client_identifier="Globex",
        line_items=[{"description": "Consulting", "quantity": 10, "unit_price": 50.00}],
        due_days=30,
    )
    inv2.issue_date = date.today() - timedelta(days=100)
    inv2.due_date = date.today() - timedelta(days=70)
    svc.store.save_invoice(inv2)

    return inv1, inv2


# ============================================================================
# Tool Registration Tests
# ============================================================================

class TestMCPToolRegistration:
    def test_v060_tools_present(self):
        tools = _run(list_tools())
        names = {t.name for t in tools}
        expected = {
            "generate_ar_aging_report",
            "get_revenue_analytics",
            "create_estimate",
            "list_estimates",
            "get_estimate",
            "send_estimate",
            "accept_estimate",
            "decline_estimate",
            "convert_estimate_to_invoice",
            "remove_estimate",
        }
        missing = expected - names
        assert not missing, f"Missing MCP tools: {missing}"

    def test_all_tools_have_schemas(self):
        tools = _run(list_tools())
        for tool in tools:
            assert tool.inputSchema["type"] == "object"


# ============================================================================
# A/R Aging MCP Tests
# ============================================================================

class TestMCPARAging:
    def test_generate_ar_aging_report(self, mock_service):
        _setup_data(mock_service)
        result = _run(call_tool("generate_ar_aging_report", {}))
        data = json.loads(result[0].text)
        assert data["client_count"] >= 2
        assert data["total_outstanding"] > 0
        assert len(data["bucket_totals"]) == 4

    def test_ar_aging_with_currency_filter(self, mock_service):
        _setup_data(mock_service)
        result = _run(call_tool("generate_ar_aging_report", {"currency": "USD"}))
        data = json.loads(result[0].text)
        assert data["currency"] == "USD"
        assert data["client_count"] >= 2

    def test_ar_aging_empty(self, mock_service):
        mock_service.create_client(name="Empty", email="e@e.com")
        result = _run(call_tool("generate_ar_aging_report", {}))
        data = json.loads(result[0].text)
        assert data["client_count"] == 0
        assert data["total_outstanding"] == 0.0


# ============================================================================
# Revenue Analytics MCP Tests
# ============================================================================

class TestMCPRevenueAnalytics:
    def test_get_revenue_analytics(self, mock_service):
        _setup_data(mock_service)
        start = str(date.today() - timedelta(days=120))
        end = str(date.today())
        result = _run(call_tool("get_revenue_analytics", {
            "period_start": start,
            "period_end": end,
        }))
        data = json.loads(result[0].text)
        assert data["total_invoiced"] > 0
        assert len(data["months"]) > 0
        assert "collection_rate" in data
        assert "avg_days_to_pay" in data
        assert isinstance(data["top_clients"], list)

    def test_revenue_invalid_date_format(self, mock_service):
        result = _run(call_tool("get_revenue_analytics", {
            "period_start": "not-a-date",
            "period_end": "also-bad",
        }))
        assert "Invalid date format" in result[0].text

    def test_revenue_invalid_range(self, mock_service):
        result = _run(call_tool("get_revenue_analytics", {
            "period_start": str(date.today()),
            "period_end": str(date.today() - timedelta(days=30)),
        }))
        assert "Error:" in result[0].text


# ============================================================================
# Estimate MCP Tests
# ============================================================================

class TestMCPEstimates:
    def test_create_estimate(self, mock_service):
        mock_service.create_client(name="TestCo", email="t@t.com")
        result = _run(call_tool("create_estimate", {
            "client": "TestCo",
            "line_items": [{"description": "Dev work", "quantity": 10, "unit_price": 100.0}],
        }))
        data = json.loads(result[0].text)
        assert data["id"].startswith("EST-")
        assert data["status"] == "draft"
        assert data["total"] == 1000.0

    def test_create_estimate_with_tax_and_discount(self, mock_service):
        mock_service.create_client(name="TaxCo", email="t@t.com")
        result = _run(call_tool("create_estimate", {
            "client": "TaxCo",
            "line_items": [{"description": "Service", "quantity": 1, "unit_price": 200.0, "tax_rate": 10.0}],
            "discount_amount": 50.0,
            "terms": "Net 30",
        }))
        data = json.loads(result[0].text)
        assert data["subtotal"] == 200.0
        assert data["tax"] == 20.0
        assert data["total"] == 170.0  # 200 + 20 - 50

    def test_create_estimate_invalid_client(self, mock_service):
        result = _run(call_tool("create_estimate", {
            "client": "Nonexistent",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 10}],
        }))
        assert "not found" in result[0].text

    def test_list_estimates(self, mock_service):
        mock_service.create_client(name="ListCo", email="l@l.com")
        _run(call_tool("create_estimate", {
            "client": "ListCo",
            "line_items": [{"description": "A", "quantity": 1, "unit_price": 10}],
        }))
        _run(call_tool("create_estimate", {
            "client": "ListCo",
            "line_items": [{"description": "B", "quantity": 1, "unit_price": 20}],
        }))
        result = _run(call_tool("list_estimates", {}))
        data = json.loads(result[0].text)
        assert len(data) >= 2

    def test_list_estimates_by_status(self, mock_service):
        mock_service.create_client(name="StatCo", email="s@s.com")
        # Create draft
        _run(call_tool("create_estimate", {
            "client": "StatCo",
            "line_items": [{"description": "A", "quantity": 1, "unit_price": 10}],
        }))
        # Create and send one
        create_result = _run(call_tool("create_estimate", {
            "client": "StatCo",
            "line_items": [{"description": "B", "quantity": 1, "unit_price": 20}],
        }))
        est_id = json.loads(create_result[0].text)["id"]
        _run(call_tool("send_estimate", {"estimate_id": est_id}))

        result = _run(call_tool("list_estimates", {"status": "sent"}))
        data = json.loads(result[0].text)
        assert all(e["status"] == "sent" for e in data)
        assert len(data) == 1

    def test_get_estimate(self, mock_service):
        mock_service.create_client(name="GetCo", email="g@g.com")
        create_result = _run(call_tool("create_estimate", {
            "client": "GetCo",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 50}],
            "notes": "Test note",
        }))
        est_id = json.loads(create_result[0].text)["id"]
        result = _run(call_tool("get_estimate", {"estimate_id": est_id}))
        data = json.loads(result[0].text)
        assert data["id"] == est_id
        assert data["notes"] == "Test note"

    def test_get_estimate_not_found(self, mock_service):
        result = _run(call_tool("get_estimate", {"estimate_id": "EST-XXXXXX"}))
        assert "not found" in result[0].text

    def test_send_estimate(self, mock_service):
        mock_service.create_client(name="SendCo", email="s@s.com")
        create_result = _run(call_tool("create_estimate", {
            "client": "SendCo",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 10}],
        }))
        est_id = json.loads(create_result[0].text)["id"]
        result = _run(call_tool("send_estimate", {"estimate_id": est_id}))
        data = json.loads(result[0].text)
        assert data["status"] == "sent"

    def test_accept_estimate(self, mock_service):
        mock_service.create_client(name="AccCo", email="a@a.com")
        create_result = _run(call_tool("create_estimate", {
            "client": "AccCo",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 10}],
        }))
        est_id = json.loads(create_result[0].text)["id"]
        _run(call_tool("send_estimate", {"estimate_id": est_id}))
        result = _run(call_tool("accept_estimate", {"estimate_id": est_id}))
        data = json.loads(result[0].text)
        assert data["status"] == "accepted"

    def test_decline_estimate(self, mock_service):
        mock_service.create_client(name="DecCo", email="d@d.com")
        create_result = _run(call_tool("create_estimate", {
            "client": "DecCo",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 10}],
        }))
        est_id = json.loads(create_result[0].text)["id"]
        result = _run(call_tool("decline_estimate", {"estimate_id": est_id}))
        data = json.loads(result[0].text)
        assert data["status"] == "declined"

    def test_accept_declined_fails(self, mock_service):
        mock_service.create_client(name="DecCo2", email="d2@d.com")
        create_result = _run(call_tool("create_estimate", {
            "client": "DecCo2",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 10}],
        }))
        est_id = json.loads(create_result[0].text)["id"]
        _run(call_tool("decline_estimate", {"estimate_id": est_id}))
        result = _run(call_tool("accept_estimate", {"estimate_id": est_id}))
        assert "Error:" in result[0].text

    def test_convert_estimate_to_invoice(self, mock_service):
        mock_service.create_client(name="ConvCo", email="c@c.com")
        create_result = _run(call_tool("create_estimate", {
            "client": "ConvCo",
            "line_items": [{"description": "Service", "quantity": 5, "unit_price": 100.0}],
        }))
        est_id = json.loads(create_result[0].text)["id"]
        result = _run(call_tool("convert_estimate_to_invoice", {
            "estimate_id": est_id,
            "due_days": 30,
        }))
        data = json.loads(result[0].text)
        assert data["estimate_status"] == "converted"
        assert data["invoice_id"].startswith("INV-") or data["invoice_id"][0].isdigit()
        assert data["invoice_total"] == 500.0

    def test_convert_already_converted_fails(self, mock_service):
        mock_service.create_client(name="TwiceCo", email="t@t.com")
        create_result = _run(call_tool("create_estimate", {
            "client": "TwiceCo",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 10}],
        }))
        est_id = json.loads(create_result[0].text)["id"]
        _run(call_tool("convert_estimate_to_invoice", {"estimate_id": est_id}))
        result = _run(call_tool("convert_estimate_to_invoice", {"estimate_id": est_id}))
        assert "already been converted" in result[0].text

    def test_remove_estimate(self, mock_service):
        mock_service.create_client(name="DelCo", email="d@d.com")
        create_result = _run(call_tool("create_estimate", {
            "client": "DelCo",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 10}],
        }))
        est_id = json.loads(create_result[0].text)["id"]
        result = _run(call_tool("remove_estimate", {"estimate_id": est_id}))
        assert "removed" in result[0].text
        # Verify it's gone
        get_result = _run(call_tool("get_estimate", {"estimate_id": est_id}))
        assert "not found" in get_result[0].text

    def test_remove_converted_fails(self, mock_service):
        mock_service.create_client(name="DelConvCo", email="dc@dc.com")
        create_result = _run(call_tool("create_estimate", {
            "client": "DelConvCo",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": 10}],
        }))
        est_id = json.loads(create_result[0].text)["id"]
        _run(call_tool("convert_estimate_to_invoice", {"estimate_id": est_id}))
        result = _run(call_tool("remove_estimate", {"estimate_id": est_id}))
        assert "Error:" in result[0].text

    def test_unknown_tool(self, mock_service):
        result = _run(call_tool("nonexistent_tool", {}))
        assert "Unknown tool" in result[0].text
