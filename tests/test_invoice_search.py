"""Tests for invoice search — date range, amount range, and text search."""

import pytest
from agent_invoice.service import InvoiceService
from agent_invoice.store import InvoiceStore
from datetime import date, timedelta
import shutil
import tempfile


@pytest.fixture
def svc():
    tmpdir = tempfile.mkdtemp()
    service = InvoiceService(InvoiceStore(data_dir=tmpdir))
    yield service
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def setup_invoices(svc):
    """Create a set of invoices for search testing."""
    client = svc.create_client(name="Searchable Corp")

    inv1 = svc.create_invoice(
        client_identifier=client.id,
        line_items=[{"description": "Consulting services", "quantity": 10, "unit_price": 100.0}],
        notes="Q1 engagement",
    )
    inv2 = svc.create_invoice(
        client_identifier=client.id,
        line_items=[{"description": "API usage", "quantity": 5, "unit_price": 50.0}],
        notes="Monthly API plan",
    )
    inv3 = svc.create_invoice(
        client_identifier=client.id,
        line_items=[{"description": "Hosting", "quantity": 1, "unit_price": 2000.0}],
        notes="Annual hosting",
    )
    return client, [inv1, inv2, inv3]


class TestInvoiceSearch:
    def test_search_by_text_in_notes(self, svc, setup_invoices):
        client, invoices = setup_invoices
        results = svc.list_invoices(search="Q1")
        assert len(results) == 1
        assert results[0].id == invoices[0].id

    def test_search_by_text_in_line_items(self, svc, setup_invoices):
        client, invoices = setup_invoices
        results = svc.list_invoices(search="API")
        assert len(results) == 1
        assert results[0].id == invoices[1].id

    def test_search_by_text_in_client_name(self, svc, setup_invoices):
        client, invoices = setup_invoices
        results = svc.list_invoices(search="Searchable")
        assert len(results) == 3  # all match client name

    def test_search_case_insensitive(self, svc, setup_invoices):
        client, invoices = setup_invoices
        results = svc.list_invoices(search="CONSULTING")
        assert len(results) == 1

    def test_search_no_match(self, svc, setup_invoices):
        results = svc.list_invoices(search="nonexistent")
        assert len(results) == 0

    def test_search_by_amount_range(self, svc, setup_invoices):
        client, invoices = setup_invoices
        # Amounts: 1000, 250, 2000
        results = svc.list_invoices(min_amount=500.0)
        assert len(results) == 2  # 1000 and 2000

        results = svc.list_invoices(max_amount=500.0)
        assert len(results) == 1  # 250

        results = svc.list_invoices(min_amount=200.0, max_amount=1000.0)
        assert len(results) == 2  # 1000 and 250

    def test_combined_filters(self, svc, setup_invoices):
        """Search with both text and amount filters."""
        client, invoices = setup_invoices
        results = svc.list_invoices(search="services", min_amount=500.0)
        assert len(results) == 1  # only the consulting one

    def test_date_range_filter(self, svc, setup_invoices):
        """Filter by issue date range."""
        client, invoices = setup_invoices
        today = date.today()

        # All issued today
        results = svc.list_invoices(date_from=today)
        assert len(results) == 3

        # From tomorrow — should be empty
        results = svc.list_invoices(date_from=today + timedelta(days=1))
        assert len(results) == 0

    def test_existing_list_still_works(self, svc, setup_invoices):
        """The original list_invoices signature still works without new filters."""
        client, invoices = setup_invoices
        results = svc.list_invoices()
        assert len(results) == 3

    def test_status_filter_with_search(self, svc, setup_invoices):
        client, invoices = setup_invoices
        # Mark one paid
        svc.add_payment(invoices[0].id, amount=1000.0)
        # Search for paid only
        results = svc.list_invoices(status="paid")
        assert len(results) == 1
        assert results[0].id == invoices[0].id
