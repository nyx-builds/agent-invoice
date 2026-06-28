"""Tests for CLI interface."""

import pytest
from click.testing import CliRunner

from agent_invoice.cli import main
from agent_invoice.service import InvoiceService
from agent_invoice.store import InvoiceStore


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def env_home(tmp_path, monkeypatch):
    """Set up a temp home dir for invoice data."""
    monkeypatch.setenv("AGENT_INVOICE_DIR", str(tmp_path / "invoice-data"))
    return tmp_path


class TestCLI:
    def test_version(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.3.0" in result.output

    def test_client_add(self, runner, env_home):
        result = runner.invoke(main, ["client", "add", "Acme Corp", "--email", "billing@acme.com"])
        assert result.exit_code == 0
        assert "Client created" in result.output
        assert "Acme Corp" in result.output

    def test_client_add_with_currency(self, runner, env_home):
        result = runner.invoke(main, ["client", "add", "Euro Corp", "--currency", "EUR"])
        assert result.exit_code == 0
        assert "EUR" in result.output

    def test_client_add_invalid_currency(self, runner, env_home):
        result = runner.invoke(main, ["client", "add", "Bad Corp", "--currency", "XYZ"])
        assert result.exit_code == 1
        assert "Unsupported currency" in result.output

    def test_client_add_duplicate(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        result = runner.invoke(main, ["client", "add", "Acme Corp"])
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_client_list(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Alpha"])
        runner.invoke(main, ["client", "add", "Beta"])
        result = runner.invoke(main, ["client", "list"])
        assert result.exit_code == 0
        assert "Alpha" in result.output
        assert "Beta" in result.output

    def test_client_list_empty(self, runner, env_home):
        result = runner.invoke(main, ["client", "list"])
        assert result.exit_code == 0
        assert "No clients" in result.output

    def test_invoice_create(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        result = runner.invoke(main, [
            "create",
            "--client", "Acme Corp",
            "--item", "Code review,40,150.00",
            "--due", "30",
        ])
        assert result.exit_code == 0
        assert "Invoice created" in result.output
        assert "$6000.00" in result.output

    def test_invoice_create_with_tax(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        result = runner.invoke(main, [
            "create",
            "--client", "Acme Corp",
            "--item", "Service,1,100.00,10.0",
            "--due", "30",
        ])
        assert result.exit_code == 0
        assert "$10.00" in result.output  # tax
        assert "$110.00" in result.output  # total

    def test_invoice_create_with_invoice_tax(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        result = runner.invoke(main, [
            "create",
            "--client", "Acme Corp",
            "--item", "Service,1,100.00",
            "--item", "Consulting,1,200.00",
            "--tax-rate", "8.5",
        ])
        assert result.exit_code == 0
        assert "$25.50" in result.output  # tax: 300 * 0.085

    def test_invoice_create_with_discount(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        result = runner.invoke(main, [
            "create",
            "--client", "Acme Corp",
            "--item", "Work,1,100.00",
            "--discount", "25.00",
        ])
        assert result.exit_code == 0
        assert "$75.00" in result.output  # 100 - 25

    def test_invoice_create_with_currency(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Euro Corp", "--currency", "EUR"])
        result = runner.invoke(main, [
            "create",
            "--client", "Euro Corp",
            "--item", "Service,1,100.00",
        ])
        assert result.exit_code == 0
        assert "€100.00" in result.output

    def test_invoice_create_two_part_item(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        result = runner.invoke(main, [
            "create",
            "--client", "Acme Corp",
            "--item", "Bug fixes,200.00",
        ])
        assert result.exit_code == 0
        assert "$200.00" in result.output

    def test_invoice_create_no_items(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        result = runner.invoke(main, ["create", "--client", "Acme Corp"])
        assert result.exit_code == 1
        assert "At least one" in result.output

    def test_invoice_create_unknown_client(self, runner, env_home):
        result = runner.invoke(main, [
            "create",
            "--client", "Ghost",
            "--item", "Work,100.00",
        ])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_invoice_list(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        runner.invoke(main, ["create", "--client", "Acme Corp", "--item", "Work,100.00"])
        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0
        assert "INV" in result.output

    def test_invoice_list_empty(self, runner, env_home):
        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0
        assert "No invoices" in result.output

    def _create_and_get_invoice_id(self, runner, client_name="Acme Corp"):
        """Helper to create an invoice and extract its ID via the service."""
        import os
        from agent_invoice.store import InvoiceStore
        from agent_invoice.service import InvoiceService
        data_dir = os.environ.get("AGENT_INVOICE_DIR")
        if not data_dir:
            return None
        store = InvoiceStore(data_dir=data_dir)
        svc = InvoiceService(store=store)
        client = svc.get_client(client_name)
        if not client:
            runner.invoke(main, ["client", "add", client_name])
        runner.invoke(main, ["create", "--client", client_name, "--item", "Work,100.00"])
        # Get all invoices and find the one we just created
        invoices = svc.list_invoices()
        if invoices:
            return invoices[-1].id
        return None

    def test_invoice_pay(self, runner, env_home):
        inv_id = self._create_and_get_invoice_id(runner)
        if inv_id:
            result = runner.invoke(main, ["pay", inv_id])
            assert result.exit_code == 0
            assert "PAID" in result.output

    def test_invoice_show(self, runner, env_home):
        inv_id = self._create_and_get_invoice_id(runner)
        if inv_id:
            result = runner.invoke(main, ["show", inv_id])
            assert result.exit_code == 0
            assert "Invoice" in result.output

    def test_earnings(self, runner, env_home):
        inv_id = self._create_and_get_invoice_id(runner)
        result = runner.invoke(main, ["earnings"])
        assert result.exit_code == 0
        assert "Earnings Summary" in result.output
        assert "$100.00" in result.output

    def test_invoice_send(self, runner, env_home):
        inv_id = self._create_and_get_invoice_id(runner)
        if inv_id:
            result = runner.invoke(main, ["send", inv_id])
            assert result.exit_code == 0
            assert "SENT" in result.output

    def test_invoice_export(self, runner, env_home):
        inv_id = self._create_and_get_invoice_id(runner)
        if inv_id:
            result = runner.invoke(main, ["export", inv_id, "--format", "json"])
            assert result.exit_code == 0
            assert inv_id in result.output

    def test_invoice_discount(self, runner, env_home):
        inv_id = self._create_and_get_invoice_id(runner)
        if inv_id:
            result = runner.invoke(main, ["discount", inv_id, "25.0"])
            assert result.exit_code == 0
            assert "Discount" in result.output or "discount" in result.output.lower()

    def test_client_remove(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        result = runner.invoke(main, ["client", "remove", "Acme Corp"])
        assert result.exit_code == 0
        assert "removed" in result.output.lower()


class TestPartialPaymentCLI:
    def _create_invoice(self, runner, env_home, client_name="Acme Corp"):
        """Helper to create a client and invoice, returns invoice ID."""
        import os
        runner.invoke(main, ["client", "add", client_name])
        runner.invoke(main, ["create", "--client", client_name, "--item", "Work,1,200.00"])
        store = InvoiceStore(data_dir=os.environ.get("AGENT_INVOICE_DIR"))
        svc = InvoiceService(store=store)
        invoices = svc.list_invoices()
        return invoices[-1].id if invoices else None

    def test_pay_full(self, runner, env_home):
        inv_id = self._create_invoice(runner, env_home)
        if inv_id:
            result = runner.invoke(main, ["pay", inv_id])
            assert result.exit_code == 0
            assert "PAID" in result.output

    def test_pay_partial(self, runner, env_home):
        inv_id = self._create_invoice(runner, env_home)
        if inv_id:
            result = runner.invoke(main, ["pay", inv_id, "--amount", "80.00"])
            assert result.exit_code == 0
            assert "Payment" in result.output
            assert "80.00" in result.output

    def test_pay_partial_with_method(self, runner, env_home):
        inv_id = self._create_invoice(runner, env_home)
        if inv_id:
            result = runner.invoke(main, ["pay", inv_id, "--amount", "100.00", "--method", "bank_transfer"])
            assert result.exit_code == 0
            assert "Payment" in result.output

    def test_pay_partial_with_reference(self, runner, env_home):
        inv_id = self._create_invoice(runner, env_home)
        if inv_id:
            result = runner.invoke(main, ["pay", inv_id, "--amount", "50.00", "--reference", "TXN-123"])
            assert result.exit_code == 0

    def test_pay_overpayment_fails(self, runner, env_home):
        inv_id = self._create_invoice(runner, env_home)
        if inv_id:
            result = runner.invoke(main, ["pay", inv_id, "--amount", "500.00"])
            assert result.exit_code == 1
            assert "exceeds" in result.output.lower() or "Error" in result.output

    def test_payments_list(self, runner, env_home):
        inv_id = self._create_invoice(runner, env_home)
        if inv_id:
            runner.invoke(main, ["pay", inv_id, "--amount", "80.00", "--method", "credit_card"])
            result = runner.invoke(main, ["payments", "list", inv_id])
            assert result.exit_code == 0
            assert "80.00" in result.output or "credit_card" in result.output

    def test_payments_list_empty(self, runner, env_home):
        inv_id = self._create_invoice(runner, env_home)
        if inv_id:
            result = runner.invoke(main, ["payments", "list", inv_id])
            assert result.exit_code == 0
            assert "No payments" in result.output

    def test_export_pdf(self, runner, env_home):
        inv_id = self._create_invoice(runner, env_home)
        if inv_id:
            import os
            output = os.path.join(str(env_home), "test_export.pdf")
            result = runner.invoke(main, ["export", inv_id, "--format", "pdf", "--output", output])
            assert result.exit_code == 0
            assert "PDF exported" in result.output

    def test_multiple_partial_payments(self, runner, env_home):
        inv_id = self._create_invoice(runner, env_home)
        if inv_id:
            # First payment
            result1 = runner.invoke(main, ["pay", inv_id, "--amount", "80.00"])
            assert result1.exit_code == 0
            # Second payment
            result2 = runner.invoke(main, ["pay", inv_id, "--amount", "120.00"])
            assert result2.exit_code == 0
            assert "PAID" in result2.output or "0.00" in result2.output


class TestRecurringCLI:
    def test_recurring_create(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        result = runner.invoke(main, [
            "recurring", "create",
            "--client", "Acme Corp",
            "--item", "Retainer,1,500.00",
            "--frequency", "monthly",
        ])
        assert result.exit_code == 0
        assert "Recurring invoice created" in result.output
        assert "REC-" in result.output

    def test_recurring_create_weekly(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        result = runner.invoke(main, [
            "recurring", "create",
            "--client", "Acme Corp",
            "--item", "Support,1,200.00",
            "--frequency", "weekly",
        ])
        assert result.exit_code == 0
        assert "weekly" in result.output

    def test_recurring_create_with_tax(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        result = runner.invoke(main, [
            "recurring", "create",
            "--client", "Acme Corp",
            "--item", "Retainer,1,500.00",
            "--tax-rate", "10.0",
        ])
        assert result.exit_code == 0
        assert "50.00" in result.output  # tax

    def test_recurring_list(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        runner.invoke(main, [
            "recurring", "create",
            "--client", "Acme Corp",
            "--item", "Retainer,1,500.00",
        ])
        result = runner.invoke(main, ["recurring", "list"])
        assert result.exit_code == 0
        assert "REC-" in result.output

    def test_recurring_list_empty(self, runner, env_home):
        result = runner.invoke(main, ["recurring", "list"])
        assert result.exit_code == 0
        assert "No recurring" in result.output

    def test_recurring_pause_resume(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        runner.invoke(main, [
            "recurring", "create",
            "--client", "Acme Corp",
            "--item", "Retainer,1,500.00",
        ])
        # Get the recurring ID via the service
        import os
        from agent_invoice.store import InvoiceStore
        from agent_invoice.service import InvoiceService
        data_dir = os.environ.get("AGENT_INVOICE_DIR")
        store = InvoiceStore(data_dir=data_dir)
        svc = InvoiceService(store=store)
        recs = svc.list_recurring()
        if recs:
            rec_id = recs[0].id
            pause_result = runner.invoke(main, ["recurring", "pause", rec_id])
            assert pause_result.exit_code == 0
            assert "paused" in pause_result.output.lower()

            resume_result = runner.invoke(main, ["recurring", "resume", rec_id])
            assert resume_result.exit_code == 0
            assert "resumed" in resume_result.output.lower()

    def test_recurring_generate(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        runner.invoke(main, [
            "recurring", "create",
            "--client", "Acme Corp",
            "--item", "Retainer,1,500.00",
        ])
        # Get the recurring ID via the service
        import os
        from agent_invoice.store import InvoiceStore
        from agent_invoice.service import InvoiceService
        data_dir = os.environ.get("AGENT_INVOICE_DIR")
        store = InvoiceStore(data_dir=data_dir)
        svc = InvoiceService(store=store)
        recs = svc.list_recurring()
        if recs:
            rec_id = recs[0].id
            gen_result = runner.invoke(main, ["recurring", "generate", rec_id])
            assert gen_result.exit_code == 0
            assert "Invoice generated" in gen_result.output

    def test_recurring_process(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        runner.invoke(main, [
            "recurring", "create",
            "--client", "Acme Corp",
            "--item", "Retainer,1,500.00",
        ])
        result = runner.invoke(main, ["recurring", "process"])
        assert result.exit_code == 0

    def test_recurring_remove(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        runner.invoke(main, [
            "recurring", "create",
            "--client", "Acme Corp",
            "--item", "Retainer,1,500.00",
        ])
        # Get the recurring ID via the service
        import os
        from agent_invoice.store import InvoiceStore
        from agent_invoice.service import InvoiceService
        data_dir = os.environ.get("AGENT_INVOICE_DIR")
        store = InvoiceStore(data_dir=data_dir)
        svc = InvoiceService(store=store)
        recs = svc.list_recurring()
        if recs:
            rec_id = recs[0].id
            result = runner.invoke(main, ["recurring", "remove", rec_id])
            assert result.exit_code == 0
            assert "removed" in result.output.lower()


class TestNumberingCLI:
    def test_numbering_show(self, runner, env_home):
        result = runner.invoke(main, ["numbering", "show"])
        assert result.exit_code == 0
        assert "INV" in result.output
        assert "Prefix" in result.output

    def test_numbering_set_prefix(self, runner, env_home):
        result = runner.invoke(main, ["numbering", "set", "--prefix", "BIL"])
        assert result.exit_code == 0
        assert "Numbering updated" in result.output
        assert "BIL" in result.output

    def test_numbering_set_multiple(self, runner, env_home):
        result = runner.invoke(main, ["numbering", "set", "--prefix", "2026", "--separator", "/", "--digits", "3"])
        assert result.exit_code == 0
        assert "2026" in result.output

    def test_numbering_set_no_options(self, runner, env_home):
        result = runner.invoke(main, ["numbering", "set"])
        assert result.exit_code == 1
        assert "at least one" in result.output.lower()


class TestCurrenciesCLI:
    def test_currencies_list(self, runner):
        result = runner.invoke(main, ["currencies"])
        assert result.exit_code == 0
        assert "USD" in result.output
        assert "EUR" in result.output
        assert "GBP" in result.output
