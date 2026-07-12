"""Tests for the MCP server — credit notes, client statements, invoice search, dunning, and remove_credit_note."""

import asyncio
import json
import pytest
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


def setup_client_and_invoice(svc, name="Test Corp", currency="USD"):
    """Helper to create a client and invoice."""
    client = svc.add_client(name=name, currency=currency)
    inv = svc.create_invoice(
        client_identifier=client.id,
        line_items=[{"description": "Work", "quantity": 10, "unit_price": 100.0}],
    )
    return client, inv


class TestMCPToolCount:
    def test_has_expected_tools(self):
        tools = _run(list_tools())
        # v0.7.0 adds: expense_create, expense_list, expense_show, expense_update,
        # expense_remove, expense_summary, profit_analysis, tax_report,
        # bulk_mark_sent, bulk_mark_paid, bulk_cancel, bulk_export,
        # export_estimate_pdf = 13 new tools
        assert len(tools) == 79  # v0.9.0: +5 analytics tools

    def test_all_tools_have_required_fields(self):
        tools = _run(list_tools())
        for tool in tools:
            assert tool.name, f"Tool missing name"
            assert tool.description, f"Tool {tool.name} missing description"
            assert tool.inputSchema, f"Tool {tool.name} missing inputSchema"
            assert "type" in tool.inputSchema
            assert tool.inputSchema["type"] == "object"

    def test_credit_note_tools_present(self):
        tools = _run(list_tools())
        names = {t.name for t in tools}
        assert "create_credit_note" in names
        assert "list_credit_notes" in names
        assert "get_credit_note" in names
        assert "apply_credit_note" in names
        assert "void_credit_note" in names
        assert "remove_credit_note" in names

    def test_statement_and_search_tools_present(self):
        tools = _run(list_tools())
        names = {t.name for t in tools}
        assert "client_statement" in names
        assert "search_invoices" in names


class TestMCPCreditNotes:
    def test_create_credit_note(self, mock_service):
        client, inv = setup_client_and_invoice(mock_service)
        result = _run(call_tool("create_credit_note", {
            "client": client.id,
            "amount": 250.0,
            "reason": "overpayment",
        }))
        data = json.loads(result[0].text)
        assert data["amount"] == 250.0
        assert data["status"] == "open"
        assert data["remaining"] == 250.0

    def test_create_credit_note_error(self, mock_service):
        result = _run(call_tool("create_credit_note", {
            "client": "nonexistent",
            "amount": 100.0,
        }))
        assert "Error" in result[0].text

    def test_list_credit_notes(self, mock_service):
        client, _ = setup_client_and_invoice(mock_service)
        _run(call_tool("create_credit_note", {"client": client.id, "amount": 100.0}))
        _run(call_tool("create_credit_note", {"client": client.id, "amount": 200.0}))
        result = _run(call_tool("list_credit_notes", {}))
        data = json.loads(result[0].text)
        assert len(data) == 2

    def test_get_credit_note(self, mock_service):
        client, _ = setup_client_and_invoice(mock_service)
        create_result = _run(call_tool("create_credit_note", {"client": client.id, "amount": 100.0}))
        credit_id = json.loads(create_result[0].text)["id"]
        result = _run(call_tool("get_credit_note", {"credit_id": credit_id}))
        data = json.loads(result[0].text)
        assert data["id"] == credit_id

    def test_get_credit_note_not_found(self, mock_service):
        result = _run(call_tool("get_credit_note", {"credit_id": "CN-NOPE"}))
        assert "not found" in result[0].text

    def test_apply_credit_note(self, mock_service):
        client, inv = setup_client_and_invoice(mock_service)
        create_result = _run(call_tool("create_credit_note", {"client": client.id, "amount": 1000.0}))
        credit_id = json.loads(create_result[0].text)["id"]
        result = _run(call_tool("apply_credit_note", {
            "credit_id": credit_id,
            "invoice_id": inv.id,
        }))
        data = json.loads(result[0].text)
        assert data["credit_note"]["applied_amount"] == 1000.0
        assert data["invoice"]["status"] == "paid"

    def test_void_credit_note(self, mock_service):
        client, _ = setup_client_and_invoice(mock_service)
        create_result = _run(call_tool("create_credit_note", {"client": client.id, "amount": 100.0}))
        credit_id = json.loads(create_result[0].text)["id"]
        result = _run(call_tool("void_credit_note", {"credit_id": credit_id}))
        data = json.loads(result[0].text)
        assert data["status"] == "void"

    def test_remove_credit_note(self, mock_service):
        client, _ = setup_client_and_invoice(mock_service)
        create_result = _run(call_tool("create_credit_note", {"client": client.id, "amount": 100.0}))
        credit_id = json.loads(create_result[0].text)["id"]
        result = _run(call_tool("remove_credit_note", {"credit_id": credit_id}))
        data = json.loads(result[0].text)
        assert data["removed"] is True

    def test_remove_credit_note_not_found(self, mock_service):
        result = _run(call_tool("remove_credit_note", {"credit_id": "CN-NOPE"}))
        assert "not found" in result[0].text

    def test_remove_applied_credit_note_fails(self, mock_service):
        client, inv = setup_client_and_invoice(mock_service)
        create_result = _run(call_tool("create_credit_note", {"client": client.id, "amount": 500.0}))
        credit_id = json.loads(create_result[0].text)["id"]
        _run(call_tool("apply_credit_note", {"credit_id": credit_id, "invoice_id": inv.id, "amount": 500.0}))
        result = _run(call_tool("remove_credit_note", {"credit_id": credit_id}))
        assert "Error" in result[0].text


class TestMCPClientStatement:
    def test_statement_basic(self, mock_service):
        client, inv = setup_client_and_invoice(mock_service)
        from datetime import date, timedelta
        today = date.today()
        result = _run(call_tool("client_statement", {
            "client": client.id,
            "period_start": (today - timedelta(days=1)).isoformat(),
            "period_end": (today + timedelta(days=365)).isoformat(),
        }))
        data = json.loads(result[0].text)
        assert data["client_id"] == client.id
        assert data["total_invoiced"] == 1000.0

    def test_statement_invalid_date(self, mock_service):
        client, _ = setup_client_and_invoice(mock_service)
        result = _run(call_tool("client_statement", {
            "client": client.id,
            "period_start": "not-a-date",
            "period_end": "2026-01-01",
        }))
        assert "Error" in result[0].text

    def test_statement_not_found(self, mock_service):
        result = _run(call_tool("client_statement", {
            "client": "nope",
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
        }))
        assert "Error" in result[0].text


class TestMCPSearchInvoices:
    def test_search_by_text(self, mock_service):
        client, _ = setup_client_and_invoice(mock_service)
        result = _run(call_tool("search_invoices", {"search": "Work"}))
        data = json.loads(result[0].text)
        assert data["count"] == 1

    def test_search_by_amount(self, mock_service):
        client, _ = setup_client_and_invoice(mock_service)
        result = _run(call_tool("search_invoices", {"min_amount": 500.0}))
        data = json.loads(result[0].text)
        assert data["count"] == 1

    def test_search_by_date_range(self, mock_service):
        client, _ = setup_client_and_invoice(mock_service)
        from datetime import date
        result = _run(call_tool("search_invoices", {
            "date_from": date.today().isoformat(),
        }))
        data = json.loads(result[0].text)
        assert data["count"] == 1

    def test_search_no_results(self, mock_service):
        client, _ = setup_client_and_invoice(mock_service)
        result = _run(call_tool("search_invoices", {"search": "nonexistent"}))
        data = json.loads(result[0].text)
        assert data["count"] == 0

    def test_search_invalid_date(self, mock_service):
        client, _ = setup_client_and_invoice(mock_service)
        result = _run(call_tool("search_invoices", {"date_from": "bad-date"}))
        assert "Error" in result[0].text


class TestMCPDunning:
    def test_get_dunning_config(self, mock_service):
        result = _run(call_tool("get_dunning_config", {}))
        data = json.loads(result[0].text)
        assert "first_reminder_days" in data
        assert "second_reminder_days" in data
        assert "final_notice_days" in data
        assert data["enabled"] is True

    def test_update_dunning_config(self, mock_service):
        result = _run(call_tool("update_dunning_config", {
            "first_reminder_days": 5,
            "second_reminder_days": 10,
            "final_notice_days": 20,
        }))
        data = json.loads(result[0].text)
        assert data["first_reminder_days"] == 5

    def test_update_dunning_config_invalid(self, mock_service):
        result = _run(call_tool("update_dunning_config", {
            "first_reminder_days": 30,
            "second_reminder_days": 10,
        }))
        assert "Error" in result[0].text


class TestMCPUnknownTool:
    def test_unknown_tool(self, mock_service):
        result = _run(call_tool("nonexistent_tool", {}))
        assert "Unknown tool" in result[0].text
