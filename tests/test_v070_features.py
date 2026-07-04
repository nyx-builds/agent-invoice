"""Tests for v0.7.0 features: Expenses, Profit Analysis, Tax Reports, Bulk Operations."""

import pytest
import tempfile
import os
from datetime import date, timedelta

from agent_invoice.models import (
    Expense,
    ExpenseCategory,
    ClientProfitability,
    ProfitAnalysis,
    TaxSummaryReport,
)
from agent_invoice.store import InvoiceStore
from agent_invoice.service import InvoiceService


@pytest.fixture
def svc():
    """Create a service with a temporary store."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = InvoiceStore(data_dir=tmpdir)
        yield InvoiceService(store=store)


@pytest.fixture
def svc_with_data(svc):
    """Create a service with clients, invoices, payments, and expenses."""
    # Create clients
    client_a = svc.add_client("Client A", currency="USD")
    client_b = svc.add_client("Client B", currency="USD")

    # Create invoices
    inv1 = svc.create_invoice(
        "Client A",
        [{"description": "Consulting", "quantity": 10, "unit_price": 100.0, "tax_rate": 10.0}],
        due_days=30,
        tax_rate=10.0,
    )
    inv1 = svc.mark_sent(inv1.id)
    svc.record_payment(inv1.id, amount=1100.0, method="bank_transfer")

    inv2 = svc.create_invoice(
        "Client B",
        [{"description": "Development", "quantity": 5, "unit_price": 200.0}],
        due_days=30,
    )
    inv2 = svc.mark_sent(inv2.id)

    inv3 = svc.create_invoice(
        "Client A",
        [{"description": "Support", "quantity": 2, "unit_price": 50.0}],
        due_days=15,
    )

    # Create expenses
    svc.create_expense(
        description="OpenAI API credits",
        amount=500.0,
        category="api_costs",
        vendor="OpenAI",
    )
    svc.create_expense(
        description="AWS hosting",
        amount=300.0,
        category="infrastructure",
        vendor="AWS",
    )
    svc.create_expense(
        description="JetBrains license",
        amount=150.0,
        category="software",
        vendor="JetBrains",
    )
    svc.create_expense(
        description="Team lunch (non-deductible)",
        amount=50.0,
        category="other",
        tax_deductible=False,
    )

    return svc


# =========================================================================
# Expense Model Tests
# =========================================================================

class TestExpenseModel:
    def test_create_expense_defaults(self):
        exp = Expense(description="Test expense", amount=100.0)
        assert exp.id.startswith("EXP-")
        assert exp.currency == "USD"
        assert exp.category == ExpenseCategory.OTHER
        assert exp.tax_deductible is True
        assert exp.amount == 100.0

    def test_expense_with_category(self):
        exp = Expense(description="API costs", amount=50.0, category=ExpenseCategory.API_COSTS)
        assert exp.category == ExpenseCategory.API_COSTS

    def test_expense_zero_amount_rejected(self):
        with pytest.raises(ValueError):
            Expense(description="Free", amount=0.0)

    def test_expense_negative_amount_rejected(self):
        with pytest.raises(ValueError):
            Expense(description="Negative", amount=-10.0)

    def test_expense_all_categories(self):
        """Test all expense categories are valid."""
        for cat in ExpenseCategory:
            exp = Expense(description=f"Test {cat.value}", amount=10.0, category=cat)
            assert exp.category == cat


# =========================================================================
# Expense Store Tests
# =========================================================================

class TestExpenseStore:
    def test_save_and_get_expense(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = InvoiceStore(data_dir=tmpdir)
            exp = Expense(description="Test", amount=100.0)
            saved = store.save_expense(exp)
            assert saved.id == exp.id
            retrieved = store.get_expense(exp.id)
            assert retrieved is not None
            assert retrieved.description == "Test"

    def test_get_nonexistent_expense(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = InvoiceStore(data_dir=tmpdir)
            assert store.get_expense("EXP-NOPE") is None

    def test_delete_expense(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = InvoiceStore(data_dir=tmpdir)
            exp = store.save_expense(Expense(description="Test", amount=50.0))
            assert store.delete_expense(exp.id) is True
            assert store.get_expense(exp.id) is None
            assert store.delete_expense(exp.id) is False

    def test_list_expenses_filter_by_category(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = InvoiceStore(data_dir=tmpdir)
            store.save_expense(Expense(description="API", amount=100.0, category=ExpenseCategory.API_COSTS))
            store.save_expense(Expense(description="Software", amount=50.0, category=ExpenseCategory.SOFTWARE))
            store.save_expense(Expense(description="More API", amount=200.0, category=ExpenseCategory.API_COSTS))

            api_expenses = store.list_expenses(category=ExpenseCategory.API_COSTS)
            assert len(api_expenses) == 2

            sw_expenses = store.list_expenses(category="software")
            assert len(sw_expenses) == 1

    def test_list_expenses_filter_by_currency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = InvoiceStore(data_dir=tmpdir)
            store.save_expense(Expense(description="USD item", amount=100.0, currency="USD"))
            store.save_expense(Expense(description="EUR item", amount=80.0, currency="EUR"))

            usd_expenses = store.list_expenses(currency="usd")
            assert len(usd_expenses) == 1
            assert usd_expenses[0].currency == "USD"

    def test_list_expenses_filter_by_date_range(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = InvoiceStore(data_dir=tmpdir)
            store.save_expense(Expense(description="Past", amount=100.0, expense_date=date(2026, 1, 15)))
            store.save_expense(Expense(description="Mid", amount=200.0, expense_date=date(2026, 6, 15)))
            store.save_expense(Expense(description="Future", amount=300.0, expense_date=date(2026, 12, 15)))

            filtered = store.list_expenses(date_from=date(2026, 3, 1), date_to=date(2026, 9, 1))
            assert len(filtered) == 1
            assert filtered[0].description == "Mid"

    def test_list_expenses_filter_by_vendor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = InvoiceStore(data_dir=tmpdir)
            store.save_expense(Expense(description="Item 1", amount=100.0, vendor="OpenAI"))
            store.save_expense(Expense(description="Item 2", amount=200.0, vendor="Amazon AWS"))
            store.save_expense(Expense(description="Item 3", amount=300.0, vendor=None))

            filtered = store.list_expenses(vendor="aws")
            assert len(filtered) == 1
            assert filtered[0].vendor == "Amazon AWS"


# =========================================================================
# Expense Service Tests
# =========================================================================

class TestExpenseService:
    def test_create_expense(self, svc):
        exp = svc.create_expense(
            description="Test expense",
            amount=100.0,
            category="software",
            vendor="TestVendor",
        )
        assert exp.id.startswith("EXP-")
        assert exp.amount == 100.0
        assert exp.category == ExpenseCategory.SOFTWARE
        assert exp.vendor == "TestVendor"
        # Verify it was persisted
        retrieved = svc.get_expense(exp.id)
        assert retrieved is not None

    def test_create_expense_invalid_currency(self, svc):
        with pytest.raises(ValueError, match="Unsupported currency"):
            svc.create_expense(description="Test", amount=100.0, currency="XYZ")

    def test_create_expense_negative_amount(self, svc):
        with pytest.raises(ValueError, match="positive"):
            svc.create_expense(description="Test", amount=-50.0)

    def test_create_expense_invalid_category(self, svc):
        with pytest.raises(ValueError, match="Invalid category"):
            svc.create_expense(description="Test", amount=100.0, category="invalid_cat")

    def test_create_expense_string_category(self, svc):
        exp = svc.create_expense(description="Test", amount=100.0, category="api_costs")
        assert exp.category == ExpenseCategory.API_COSTS

    def test_get_nonexistent_expense(self, svc):
        assert svc.get_expense("EXP-NOPE") is None

    def test_list_expenses_all(self, svc):
        svc.create_expense(description="E1", amount=10.0)
        svc.create_expense(description="E2", amount=20.0)
        expenses = svc.list_expenses()
        assert len(expenses) == 2

    def test_update_expense(self, svc):
        exp = svc.create_expense(description="Original", amount=100.0)
        updated = svc.update_expense(exp.id, description="Updated", amount=200.0)
        assert updated.description == "Updated"
        assert updated.amount == 200.0

    def test_update_expense_nonexistent(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.update_expense("EXP-NOPE", amount=200.0)

    def test_update_expense_negative_amount(self, svc):
        exp = svc.create_expense(description="Test", amount=100.0)
        with pytest.raises(ValueError, match="positive"):
            svc.update_expense(exp.id, amount=-50.0)

    def test_remove_expense(self, svc):
        exp = svc.create_expense(description="Test", amount=100.0)
        assert svc.remove_expense(exp.id) is True
        assert svc.get_expense(exp.id) is None
        assert svc.remove_expense(exp.id) is False

    def test_expense_summary(self, svc_with_data):
        summary = svc_with_data.expense_summary(currency="USD")
        assert summary["total"] == 1000.0  # 500 + 300 + 150 + 50
        assert summary["expense_count"] == 4
        assert summary["currency"] == "USD"
        # Check breakdown
        cats = {item["category"]: item for item in summary["breakdown"]}
        assert cats["api_costs"]["amount"] == 500.0
        assert cats["infrastructure"]["amount"] == 300.0
        assert cats["software"]["amount"] == 150.0
        assert cats["other"]["amount"] == 50.0

    def test_expense_summary_percentages(self, svc_with_data):
        summary = svc_with_data.expense_summary(currency="USD")
        total_pct = sum(item["percentage"] for item in summary["breakdown"])
        assert abs(total_pct - 100.0) < 0.5  # Allow rounding

    def test_expense_summary_empty(self, svc):
        summary = svc.expense_summary()
        assert summary["total"] == 0.0
        assert summary["expense_count"] == 0
        assert summary["breakdown"] == []


# =========================================================================
# Profit Analysis Tests
# =========================================================================

class TestProfitAnalysis:
    def test_profit_analysis_basic(self, svc_with_data):
        analysis = svc_with_data.get_profit_analysis(currency="USD")
        # Revenue: 1100 (from inv1 payment)
        assert analysis.total_revenue == 1100.0
        # Expenses: 500 + 300 + 150 + 50 = 1000
        assert analysis.total_expenses == 1000.0
        # Gross profit: 1100 - 1000 = 100
        assert analysis.gross_profit == 100.0
        # Margin: 100/1100 * 100 ≈ 9.1
        assert analysis.gross_margin == pytest.approx(9.1, abs=0.5)

    def test_profit_analysis_currency(self, svc_with_data):
        analysis = svc_with_data.get_profit_analysis(currency="USD")
        assert analysis.currency == "USD"

    def test_profit_analysis_expense_breakdown(self, svc_with_data):
        analysis = svc_with_data.get_profit_analysis(currency="USD")
        assert len(analysis.expense_breakdown) > 0
        # Should be sorted by amount descending
        amounts = [item["amount"] for item in analysis.expense_breakdown]
        assert amounts == sorted(amounts, reverse=True)

    def test_profit_analysis_client_profitability(self, svc_with_data):
        analysis = svc_with_data.get_profit_analysis(currency="USD")
        assert len(analysis.client_profitability) == 2  # Client A and Client B

        # Client A should have collected 1100
        client_a = next(c for c in analysis.client_profitability if c.client_name == "Client A")
        assert client_a.total_collected == 1100.0
        assert client_a.invoice_count == 2  # inv1 and inv3

    def test_profit_analysis_no_revenue(self, svc):
        """Test profit analysis with no data."""
        svc.create_expense(description="Test", amount=100.0)
        analysis = svc.get_profit_analysis(currency="USD")
        assert analysis.total_revenue == 0.0
        assert analysis.total_expenses == 100.0
        assert analysis.gross_profit == -100.0
        assert analysis.gross_margin == 0.0

    def test_profit_analysis_no_data(self, svc):
        """Test profit analysis with completely empty store."""
        analysis = svc.get_profit_analysis(currency="USD")
        assert analysis.total_revenue == 0.0
        assert analysis.total_expenses == 0.0
        assert analysis.gross_profit == 0.0
        assert analysis.client_profitability == []

    def test_profit_analysis_with_period(self, svc_with_data):
        """Test profit analysis with date filtering."""
        analysis = svc_with_data.get_profit_analysis(
            period_start=date(2026, 1, 1),
            period_end=date.today(),
            currency="USD",
        )
        assert analysis.period_start == date(2026, 1, 1)
        assert analysis.total_expenses > 0


# =========================================================================
# Tax Summary Report Tests
# =========================================================================

class TestTaxSummaryReport:
    def test_tax_summary_basic(self, svc_with_data):
        report = svc_with_data.generate_tax_summary(
            period_start=date(2026, 1, 1),
            period_end=date.today() + timedelta(days=365),
            currency="USD",
        )
        # 3 invoices: inv1 (1000 subtotal + 100 tax = 1100 total), inv2 (1000 no tax), inv3 (100 no tax)
        assert report.total_invoiced == 2100.0  # 1000 + 1000 + 100 (subtotals)
        assert report.total_tax_collected == 100.0  # Only inv1 has tax
        assert report.effective_tax_rate > 0

    def test_tax_summary_tax_from_paid_only(self, svc_with_data):
        report = svc_with_data.generate_tax_summary(
            period_start=date(2026, 1, 1),
            period_end=date.today() + timedelta(days=365),
            currency="USD",
        )
        # inv1 is paid (100 tax), inv2/inv3 not paid
        assert report.total_tax_from_paid == 100.0

    def test_tax_summary_breakdown_by_rate(self, svc_with_data):
        report = svc_with_data.generate_tax_summary(
            period_start=date(2026, 1, 1),
            period_end=date.today() + timedelta(days=365),
            currency="USD",
        )
        assert len(report.tax_by_rate) > 0
        # Should have a 10.0% rate entry
        rate_10 = next(r for r in report.tax_by_rate if r["rate"] == 10.0)
        assert rate_10["tax_amount"] == 100.0

    def test_tax_summary_deductible_expenses(self, svc_with_data):
        report = svc_with_data.generate_tax_summary(
            period_start=date(2026, 1, 1),
            period_end=date.today() + timedelta(days=365),
            currency="USD",
        )
        # 500 + 300 + 150 = 950 (50 is non-deductible)
        assert report.tax_deductible_expenses == 950.0
        # Net taxable: 2100 - 950 = 1150
        assert report.net_taxable_income == 1150.0

    def test_tax_summary_empty_period(self, svc):
        report = svc.generate_tax_summary(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
        )
        assert report.total_invoiced == 0.0
        assert report.total_tax_collected == 0.0
        assert report.effective_tax_rate == 0.0

    def test_tax_summary_invoice_details(self, svc_with_data):
        report = svc_with_data.generate_tax_summary(
            period_start=date(2026, 1, 1),
            period_end=date.today() + timedelta(days=365),
            currency="USD",
        )
        assert len(report.invoice_details) == 3

    def test_tax_summary_all_currencies(self, svc_with_data):
        """Test with no currency filter (all currencies)."""
        report = svc_with_data.generate_tax_summary(
            period_start=date(2026, 1, 1),
            period_end=date.today() + timedelta(days=365),
        )
        assert report.currency is None


# =========================================================================
# Bulk Operations Tests
# =========================================================================

class TestBulkOperations:
    def test_bulk_mark_sent_success(self, svc):
        # Create draft invoices
        inv1 = svc.create_invoice(
            svc.add_client("Client A").name,
            [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        )
        inv2 = svc.create_invoice(
            svc.add_client("Client B").name,
            [{"description": "Work", "quantity": 1, "unit_price": 200.0}],
        )
        results = svc.bulk_mark_sent([inv1.id, inv2.id])
        assert len(results["success"]) == 2
        assert len(results["errors"]) == 0

        # Verify
        assert svc.get_invoice(inv1.id).status.value == "sent"
        assert svc.get_invoice(inv2.id).status.value == "sent"

    def test_bulk_mark_sent_partial_failure(self, svc):
        inv1 = svc.create_invoice(
            svc.add_client("Client A").name,
            [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        )
        results = svc.bulk_mark_sent([inv1.id, "INV-NOPE"])
        assert len(results["success"]) == 1
        assert len(results["errors"]) == 1
        assert results["errors"][0]["id"] == "INV-NOPE"

    def test_bulk_mark_sent_already_sent(self, svc):
        inv1 = svc.create_invoice(
            svc.add_client("Client A").name,
            [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        )
        svc.mark_sent(inv1.id)
        results = svc.bulk_mark_sent([inv1.id])
        assert len(results["success"]) == 0
        assert len(results["errors"]) == 1

    def test_bulk_mark_paid_success(self, svc):
        inv1 = svc.create_invoice(
            svc.add_client("Client A").name,
            [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        )
        inv2 = svc.create_invoice(
            svc.add_client("Client B").name,
            [{"description": "Work", "quantity": 1, "unit_price": 200.0}],
        )
        svc.mark_sent(inv1.id)
        svc.mark_sent(inv2.id)
        results = svc.bulk_mark_paid([inv1.id, inv2.id])
        assert len(results["success"]) == 2
        assert svc.get_invoice(inv1.id).status.value == "paid"
        assert svc.get_invoice(inv2.id).status.value == "paid"

    def test_bulk_mark_paid_already_paid(self, svc):
        inv1 = svc.create_invoice(
            svc.add_client("Client A").name,
            [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        )
        svc.mark_paid(inv1.id)
        results = svc.bulk_mark_paid([inv1.id])
        assert len(results["success"]) == 0
        assert len(results["errors"]) == 1

    def test_bulk_cancel_success(self, svc):
        inv1 = svc.create_invoice(
            svc.add_client("Client A").name,
            [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        )
        inv2 = svc.create_invoice(
            svc.add_client("Client B").name,
            [{"description": "Work", "quantity": 1, "unit_price": 200.0}],
        )
        results = svc.bulk_cancel([inv1.id, inv2.id])
        assert len(results["success"]) == 2
        assert svc.get_invoice(inv1.id).status.value == "cancelled"
        assert svc.get_invoice(inv2.id).status.value == "cancelled"

    def test_bulk_cancel_paid_invoice(self, svc):
        inv1 = svc.create_invoice(
            svc.add_client("Client A").name,
            [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        )
        svc.mark_paid(inv1.id)
        results = svc.bulk_cancel([inv1.id])
        assert len(results["success"]) == 0
        assert len(results["errors"]) == 1

    def test_bulk_export_markdown(self, svc):
        inv1 = svc.create_invoice(
            svc.add_client("Client A").name,
            [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        )
        inv2 = svc.create_invoice(
            svc.add_client("Client B").name,
            [{"description": "Work", "quantity": 1, "unit_price": 200.0}],
        )
        results = svc.bulk_export([inv1.id, inv2.id], format="markdown")
        assert len(results["exports"]) == 2
        assert results["exports"][0]["format"] == "markdown"
        assert "Invoice" in results["exports"][0]["content"]

    def test_bulk_export_json(self, svc):
        inv1 = svc.create_invoice(
            svc.add_client("Client A").name,
            [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        )
        results = svc.bulk_export([inv1.id], format="json")
        assert len(results["exports"]) == 1
        assert results["exports"][0]["format"] == "json"

    def test_bulk_export_partial_failure(self, svc):
        inv1 = svc.create_invoice(
            svc.add_client("Client A").name,
            [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        )
        results = svc.bulk_export([inv1.id, "INV-NOPE"])
        assert len(results["exports"]) == 1
        assert len(results["errors"]) == 1

    def test_bulk_empty_list(self, svc):
        results = svc.bulk_mark_sent([])
        assert len(results["success"]) == 0
        assert len(results["errors"]) == 0
