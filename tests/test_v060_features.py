"""Tests for v0.6.0 features: A/R Aging, Revenue Analytics, and Estimates."""

import pytest
from datetime import date, timedelta
from pathlib import Path
import tempfile
import shutil

from agent_invoice.models import (
    ARAgingReport,
    ClientARAging,
    Estimate,
    EstimateStatus,
    InvoiceStatus,
    RevenueAnalytics,
)
from agent_invoice.service import InvoiceService
from agent_invoice.store import InvoiceStore


@pytest.fixture
def tmp_store():
    tmpdir = tempfile.mkdtemp()
    yield InvoiceStore(data_dir=Path(tmpdir))
    shutil.rmtree(tmpdir)


@pytest.fixture
def svc(tmp_store):
    return InvoiceService(tmp_store)


@pytest.fixture
def populated_svc(svc):
    """Service with multiple clients, invoices, and payments."""
    # Create clients
    svc.create_client(name="Acme Corp", email="billing@acme.com", currency="USD")
    svc.create_client(name="Globex", email="pay@globex.com", currency="USD")
    svc.create_client(name="Initech", email="accounts@initech.com", currency="USD")

    # Create invoices with various dates (past due and current)
    # Invoice 1: Acme, issued 60 days ago, 30-day terms (overdue by 30 days), partially paid
    inv1 = svc.create_invoice(
        client_identifier="Acme Corp",
        line_items=[{"description": "API calls", "quantity": 100, "unit_price": 2.00}],
        due_days=30,
    )
    inv1.issue_date = date.today() - timedelta(days=60)
    inv1.due_date = date.today() - timedelta(days=30)
    inv1.status = InvoiceStatus.PARTIALLY_PAID
    inv1 = svc.store.save_invoice(inv1)
    svc.record_payment(inv1.id, amount=50.0, method="bank_transfer")

    # Invoice 2: Globex, issued 100 days ago, 30-day terms (overdue by 70 days), unpaid
    inv2 = svc.create_invoice(
        client_identifier="Globex",
        line_items=[{"description": "Consulting", "quantity": 10, "unit_price": 50.00}],
        due_days=30,
    )
    inv2.issue_date = date.today() - timedelta(days=100)
    inv2.due_date = date.today() - timedelta(days=70)
    inv2 = svc.store.save_invoice(inv2)

    # Invoice 3: Acme, issued 10 days ago, 30-day terms (not overdue yet), unpaid
    inv3 = svc.create_invoice(
        client_identifier="Acme Corp",
        line_items=[{"description": "Monthly sub", "quantity": 1, "unit_price": 500.00}],
        due_days=30,
    )
    inv3.issue_date = date.today() - timedelta(days=10)
    inv3.due_date = date.today() + timedelta(days=20)
    inv3 = svc.store.save_invoice(inv3)

    # Invoice 4: Initech, issued 5 days ago, paid (for revenue analytics)
    inv4 = svc.create_invoice(
        client_identifier="Initech",
        line_items=[{"description": "Setup", "quantity": 1, "unit_price": 1000.00}],
        due_days=15,
    )
    inv4.issue_date = date.today() - timedelta(days=5)
    inv4 = svc.store.save_invoice(inv4)
    svc.record_payment(inv4.id, amount=1000.0, method="wire")

    return svc


# ============================================================================
# A/R Aging Report Tests
# ============================================================================

class TestARAgingReport:

    def test_generates_report(self, populated_svc):
        report = populated_svc.generate_ar_aging_report()
        assert isinstance(report, ARAgingReport)
        assert report.client_count > 0
        assert report.total_outstanding > 0

    def test_bucket_labels(self, populated_svc):
        report = populated_svc.generate_ar_aging_report()
        labels = [b.label for b in report.bucket_totals]
        assert "0-30" in labels
        assert "31-60" in labels
        assert "61-90" in labels
        assert "91+" in labels or "91-None" not in labels

    def test_outstanding_total_matches(self, populated_svc):
        report = populated_svc.generate_ar_aging_report()
        # Sum of all client totals should equal grand total
        client_sum = sum(c.total_outstanding for c in report.clients)
        assert abs(client_sum - report.total_outstanding) < 0.02

    def test_client_in_right_bucket(self, populated_svc):
        report = populated_svc.generate_ar_aging_report()
        # Globex invoice is 70 days overdue -> should be in 61-90 bucket
        globex = next((c for c in report.clients if c.client_name == "Globex"), None)
        assert globex is not None
        bucket_61_90 = next((b for b in globex.buckets if b.label == "61-90"), None)
        assert bucket_61_90 is not None
        assert bucket_61_90.invoice_count >= 1
        assert bucket_61_90.total_outstanding > 0

    def test_invoice_details_populated(self, populated_svc):
        report = populated_svc.generate_ar_aging_report()
        for client in report.clients:
            for detail in client.invoice_details:
                assert "id" in detail
                assert "total" in detail
                assert "amount_remaining" in detail
                assert "days_overdue" in detail
                assert "bucket" in detail

    def test_empty_report_when_all_paid(self, svc):
        svc.create_client(name="PaidClient", email="p@p.com")
        inv = svc.create_invoice(
            client_identifier="PaidClient",
            line_items=[{"description": "Thing", "quantity": 1, "unit_price": 100}],
            due_days=30,
        )
        svc.record_payment(inv.id, amount=100.0)
        report = svc.generate_ar_aging_report()
        assert report.client_count == 0
        assert report.total_outstanding == 0.0

    def test_custom_buckets(self, populated_svc):
        report = populated_svc.generate_ar_aging_report(
            bucket_ranges=[(0, 15), (16, 45), (46, None)]
        )
        labels = [b.label for b in report.bucket_totals]
        assert "0-15" in labels
        assert "16-45" in labels
        assert "46+" in labels

    def test_currency_filter(self, populated_svc):
        report = populated_svc.generate_ar_aging_report(currency="USD")
        assert report.currency == "USD"
        # All invoices are USD so should have results
        assert report.client_count > 0

    def test_days_overdue_calculation(self, populated_svc):
        report = populated_svc.generate_ar_aging_report()
        # Find the Acme invoices
        acme = next((c for c in report.clients if c.client_name == "Acme Corp"), None)
        assert acme is not None
        # Acme has two outstanding invoices: one ~30 days overdue (in 0-30 bucket), one not overdue
        for detail in acme.invoice_details:
            if detail["days_overdue"] > 20:
                # 30 days overdue should be in 0-30 bucket (inclusive boundary)
                assert detail["bucket"] in ("0-30", "31-60")


# ============================================================================
# Revenue Analytics Tests
# ============================================================================

class TestRevenueAnalytics:

    def test_generates_analytics(self, populated_svc):
        start = date.today() - timedelta(days=120)
        end = date.today()
        analytics = populated_svc.get_revenue_analytics(start, end)
        assert isinstance(analytics, RevenueAnalytics)
        assert len(analytics.months) > 0
        assert analytics.total_invoiced > 0

    def test_collection_rate(self, populated_svc):
        start = date.today() - timedelta(days=120)
        end = date.today()
        analytics = populated_svc.get_revenue_analytics(start, end)
        # We have 3 invoices issued (200 + 500 + 1000) = 1700 invoiced
        # Collected: 50 (partial) + 1000 (Initech) = 1050
        assert analytics.collection_rate > 0
        assert analytics.collection_rate <= 100

    def test_avg_days_to_pay(self, populated_svc):
        start = date.today() - timedelta(days=120)
        end = date.today()
        analytics = populated_svc.get_revenue_analytics(start, end)
        # Initech was paid within ~5 days
        assert analytics.avg_days_to_pay > 0

    def test_top_clients(self, populated_svc):
        start = date.today() - timedelta(days=120)
        end = date.today()
        analytics = populated_svc.get_revenue_analytics(start, end)
        assert len(analytics.top_clients) > 0
        # Each entry should have required fields
        for tc in analytics.top_clients:
            assert "client_id" in tc
            assert "client_name" in tc
            assert "total_invoiced" in tc
            assert "total_paid" in tc

    def test_invalid_date_range(self, populated_svc):
        with pytest.raises(ValueError, match="period_start must be before"):
            populated_svc.get_revenue_analytics(
                date.today(),
                date.today() - timedelta(days=30),
            )

    def test_monthly_breakdown_format(self, populated_svc):
        start = date.today() - timedelta(days=30)
        end = date.today()
        analytics = populated_svc.get_revenue_analytics(start, end)
        for m in analytics.months:
            assert len(m.period) == 7  # "YYYY-MM"
            assert "-" in m.period
            assert m.invoiced >= 0
            assert m.collected >= 0

    def test_empty_period(self, svc):
        svc.create_client(name="Empty", email="e@e.com")
        analytics = svc.get_revenue_analytics(
            date.today() - timedelta(days=10),
            date.today(),
        )
        assert analytics.total_invoiced == 0
        assert analytics.collection_rate == 0


# ============================================================================
# Estimate Tests
# ============================================================================

class TestEstimates:

    def test_create_estimate(self, svc):
        svc.create_client(name="TestCo", email="t@t.com")
        est = svc.create_estimate(
            client_identifier="TestCo",
            line_items=[{"description": "Dev work", "quantity": 10, "unit_price": 100.0}],
        )
        assert est.id.startswith("EST-")
        assert est.status == EstimateStatus.DRAFT
        assert est.subtotal == 1000.0
        assert est.total == 1000.0
        assert est.expiry_date is not None

    def test_estimate_with_tax(self, svc):
        svc.create_client(name="TaxCo", email="t@t.com")
        est = svc.create_estimate(
            client_identifier="TaxCo",
            line_items=[{"description": "Service", "quantity": 1, "unit_price": 100.0, "tax_rate": 10.0}],
        )
        assert est.subtotal == 100.0
        assert est.total_tax == 10.0
        assert est.total == 110.0

    def test_estimate_with_discount(self, svc):
        svc.create_client(name="DiscCo", email="d@d.com")
        est = svc.create_estimate(
            client_identifier="DiscCo",
            line_items=[{"description": "Service", "quantity": 1, "unit_price": 200.0}],
            discount_amount=50.0,
        )
        assert est.subtotal == 200.0
        assert est.total == 150.0

    def test_estimate_expiry(self, svc):
        svc.create_client(name="ExpCo", email="e@e.com")
        est = svc.create_estimate(
            client_identifier="ExpCo",
            line_items=[{"description": "Thing", "quantity": 1, "unit_price": 50}],
            expiry_days=15,
        )
        assert est.expiry_date == date.today() + timedelta(days=15)

    def test_mark_sent(self, svc):
        svc.create_client(name="SendCo", email="s@s.com")
        est = svc.create_estimate(
            client_identifier="SendCo",
            line_items=[{"description": "X", "quantity": 1, "unit_price": 10}],
        )
        est = svc.send_estimate(est.id)
        assert est.status == EstimateStatus.SENT

    def test_mark_accepted(self, svc):
        svc.create_client(name="AccCo", email="a@a.com")
        est = svc.create_estimate(
            client_identifier="AccCo",
            line_items=[{"description": "X", "quantity": 1, "unit_price": 10}],
        )
        svc.send_estimate(est.id)
        est = svc.accept_estimate(est.id)
        assert est.status == EstimateStatus.ACCEPTED
        assert est.accepted_date == date.today()

    def test_mark_declined(self, svc):
        svc.create_client(name="DecCo", email="d@d.com")
        est = svc.create_estimate(
            client_identifier="DecCo",
            line_items=[{"description": "X", "quantity": 1, "unit_price": 10}],
        )
        est = svc.decline_estimate(est.id)
        assert est.status == EstimateStatus.DECLINED

    def test_cannot_accept_declined(self, svc):
        svc.create_client(name="DecCo2", email="d2@d.com")
        est = svc.create_estimate(
            client_identifier="DecCo2",
            line_items=[{"description": "X", "quantity": 1, "unit_price": 10}],
        )
        svc.decline_estimate(est.id)
        with pytest.raises(ValueError, match="Cannot accept estimate in 'declined'"):
            svc.accept_estimate(est.id)

    def test_convert_estimate_to_invoice(self, svc):
        svc.create_client(name="ConvCo", email="c@c.com")
        est = svc.create_estimate(
            client_identifier="ConvCo",
            line_items=[{"description": "Service", "quantity": 5, "unit_price": 100.0}],
            terms="Net 30",
        )
        svc.send_estimate(est.id)
        svc.accept_estimate(est.id)

        updated_est, invoice = svc.convert_estimate_to_invoice(est.id, due_days=30)
        assert updated_est.status == EstimateStatus.CONVERTED
        assert updated_est.converted_invoice_id == invoice.id
        assert invoice.subtotal == 500.0
        assert invoice.client_name == "ConvCo"
        assert invoice.due_date is not None

    def test_cannot_convert_declined(self, svc):
        svc.create_client(name="DeclConv", email="dc@dc.com")
        est = svc.create_estimate(
            client_identifier="DeclConv",
            line_items=[{"description": "X", "quantity": 1, "unit_price": 10}],
        )
        svc.decline_estimate(est.id)
        with pytest.raises(ValueError, match="Cannot convert a declined estimate"):
            svc.convert_estimate_to_invoice(est.id)

    def test_cannot_convert_expired(self, svc):
        svc.create_client(name="ExpConv", email="ec@ec.com")
        est = svc.create_estimate(
            client_identifier="ExpConv",
            line_items=[{"description": "X", "quantity": 1, "unit_price": 10}],
            expiry_days=30,
        )
        # Force expiration
        est.status = EstimateStatus.EXPIRED
        svc.store.save_estimate(est)
        with pytest.raises(ValueError, match="Cannot convert an expired estimate"):
            svc.convert_estimate_to_invoice(est.id)

    def test_cannot_convert_twice(self, svc):
        svc.create_client(name="TwiceConv", email="tc@tc.com")
        est = svc.create_estimate(
            client_identifier="TwiceConv",
            line_items=[{"description": "X", "quantity": 1, "unit_price": 10}],
        )
        svc.convert_estimate_to_invoice(est.id)
        with pytest.raises(ValueError, match="already been converted"):
            svc.convert_estimate_to_invoice(est.id)

    def test_list_estimates(self, svc):
        svc.create_client(name="ListCo", email="l@l.com")
        svc.create_estimate(
            client_identifier="ListCo",
            line_items=[{"description": "A", "quantity": 1, "unit_price": 10}],
        )
        est2 = svc.create_estimate(
            client_identifier="ListCo",
            line_items=[{"description": "B", "quantity": 1, "unit_price": 20}],
        )
        svc.send_estimate(est2.id)

        all_est = svc.list_estimates()
        assert len(all_est) >= 2

        sent_est = svc.list_estimates(status="sent")
        assert len(sent_est) == 1
        assert sent_est[0].status == EstimateStatus.SENT

    def test_list_invalid_status(self, svc):
        with pytest.raises(ValueError, match="Invalid estimate status"):
            svc.list_estimates(status="invalid")

    def test_delete_estimate(self, svc):
        svc.create_client(name="DelCo", email="d@d.com")
        est = svc.create_estimate(
            client_identifier="DelCo",
            line_items=[{"description": "X", "quantity": 1, "unit_price": 10}],
        )
        assert svc.remove_estimate(est.id) is True
        assert svc.get_estimate(est.id) is None

    def test_cannot_delete_converted(self, svc):
        svc.create_client(name="DelConvCo", email="dc@dc.com")
        est = svc.create_estimate(
            client_identifier="DelConvCo",
            line_items=[{"description": "X", "quantity": 1, "unit_price": 10}],
        )
        svc.convert_estimate_to_invoice(est.id)
        with pytest.raises(ValueError, match="Cannot remove a converted estimate"):
            svc.remove_estimate(est.id)

    def test_estimate_markdown(self, svc):
        svc.create_client(name="MdCo", email="m@m.com")
        est = svc.create_estimate(
            client_identifier="MdCo",
            line_items=[{"description": "Test item", "quantity": 2, "unit_price": 50.0}],
            terms="Net 30",
            notes="Test note",
        )
        md = est.to_markdown()
        assert "# Estimate" in md
        assert "Test item" in md
        assert "Net 30" in md
        assert "Test note" in md

    def test_estimate_nonexistent_client(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.create_estimate(
                client_identifier="Nonexistent",
                line_items=[{"description": "X", "quantity": 1, "unit_price": 10}],
            )

    def test_estimate_get_nonexistent(self, svc):
        assert svc.get_estimate("EST-XXXXXX") is None

    def test_estimate_auto_expire(self, svc):
        svc.create_client(name="AutoExp", email="ae@ae.com")
        est = svc.create_estimate(
            client_identifier="AutoExp",
            line_items=[{"description": "X", "quantity": 1, "unit_price": 10}],
            expiry_days=30,
        )
        # Force expiry date to past
        est.expiry_date = date.today() - timedelta(days=1)
        svc.store.save_estimate(est)

        # On get, should auto-expire
        fetched = svc.get_estimate(est.id)
        assert fetched.status == EstimateStatus.EXPIRED

    def test_invalid_currency(self, svc):
        svc.create_client(name="CurCo", email="c@c.com")
        with pytest.raises(ValueError, match="Unsupported currency"):
            svc.create_estimate(
                client_identifier="CurCo",
                line_items=[{"description": "X", "quantity": 1, "unit_price": 10}],
                currency="XYZ",
            )
