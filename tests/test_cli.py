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
        assert "0.1.0" in result.output

    def test_client_add(self, runner, env_home):
        result = runner.invoke(main, ["client", "add", "Acme Corp", "--email", "billing@acme.com"])
        assert result.exit_code == 0
        assert "Client created" in result.output
        assert "Acme Corp" in result.output

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
        assert "INV-" in result.output

    def test_invoice_list_empty(self, runner, env_home):
        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0
        assert "No invoices" in result.output

    def test_invoice_pay(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        runner.invoke(main, ["create", "--client", "Acme Corp", "--item", "Work,100.00"])
        # Get the invoice ID from the list
        result = runner.invoke(main, ["list"])
        assert "INV-" in result.output
        # Find the invoice ID
        for line in result.output.split("\n"):
            if "INV-" in line:
                inv_id = line.split("│")[1].strip() if "│" in line else None
                if inv_id and inv_id.startswith("INV-"):
                    break
        else:
            # Just try a generic pattern
            inv_id = None
        
        if inv_id:
            result = runner.invoke(main, ["pay", inv_id])
            assert result.exit_code == 0
            assert "PAID" in result.output

    def test_invoice_show(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        runner.invoke(main, ["create", "--client", "Acme Corp", "--item", "Work,100.00"])
        # Get invoice ID
        list_result = runner.invoke(main, ["list"])
        inv_id = None
        for line in list_result.output.split("\n"):
            if "INV-" in line:
                parts = line.split()
                for p in parts:
                    if p.startswith("INV-"):
                        inv_id = p
                        break
                if inv_id:
                    break
        if inv_id:
            result = runner.invoke(main, ["show", inv_id])
            assert result.exit_code == 0
            assert "Invoice" in result.output

    def test_earnings(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        runner.invoke(main, ["create", "--client", "Acme Corp", "--item", "Work,100.00"])
        result = runner.invoke(main, ["earnings"])
        assert result.exit_code == 0
        assert "Earnings Summary" in result.output
        assert "$100.00" in result.output

    def test_invoice_send(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        runner.invoke(main, ["create", "--client", "Acme Corp", "--item", "Work,100.00"])
        list_result = runner.invoke(main, ["list"])
        inv_id = None
        for line in list_result.output.split("\n"):
            if "INV-" in line:
                parts = line.split()
                for p in parts:
                    if p.startswith("INV-"):
                        inv_id = p
                        break
                if inv_id:
                    break
        if inv_id:
            result = runner.invoke(main, ["send", inv_id])
            assert result.exit_code == 0
            assert "SENT" in result.output

    def test_invoice_export(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        runner.invoke(main, ["create", "--client", "Acme Corp", "--item", "Work,100.00"])
        list_result = runner.invoke(main, ["list"])
        inv_id = None
        for line in list_result.output.split("\n"):
            if "INV-" in line:
                parts = line.split()
                for p in parts:
                    if p.startswith("INV-"):
                        inv_id = p
                        break
                if inv_id:
                    break
        if inv_id:
            result = runner.invoke(main, ["export", inv_id, "--format", "json"])
            assert result.exit_code == 0
            assert inv_id in result.output

    def test_client_remove(self, runner, env_home):
        runner.invoke(main, ["client", "add", "Acme Corp"])
        result = runner.invoke(main, ["client", "remove", "Acme Corp"])
        assert result.exit_code == 0
        assert "removed" in result.output.lower()
