"""Tests for credit note functionality — create, list, apply, void, and edge cases."""

import pytest
from agent_invoice.service import InvoiceService
from agent_invoice.store import InvoiceStore
from agent_invoice.models import CreditNoteStatus, InvoiceStatus
from datetime import date, timedelta
from pathlib import Path
import shutil
import tempfile


@pytest.fixture
def svc():
    """Create a service with a temporary data directory."""
    tmpdir = tempfile.mkdtemp()
    service = InvoiceService(InvoiceStore(data_dir=tmpdir))
    yield service
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def client_and_invoice(svc):
    """Create a client and an unpaid invoice."""
    client = svc.create_client(name="Acme Corp", email="billing@acme.com", currency="USD")
    inv = svc.create_invoice(
        client_identifier=client.id,
        line_items=[{"description": "API calls", "quantity": 10, "unit_price": 100.0}],
        due_days=30,
    )
    return client, inv


class TestCreateCreditNote:
    def test_create_basic_credit_note(self, svc, client_and_invoice):
        client, _ = client_and_invoice
        credit = svc.create_credit_note(
            client_identifier=client.id,
            amount=250.00,
            reason="overpayment",
        )
        assert credit.id.startswith("CN-")
        assert credit.client_id == client.id
        assert credit.amount == 250.00
        assert credit.currency == "USD"
        assert credit.status == CreditNoteStatus.OPEN
        assert credit.reason == "overpayment"
        assert credit.remaining_amount == 250.00
        assert credit.applied_amount == 0.0

    def test_create_credit_note_with_invoice_link(self, svc, client_and_invoice):
        client, inv = client_and_invoice
        credit = svc.create_credit_note(
            client_identifier=client.id,
            amount=100.00,
            reason="billing error",
            invoice_id=inv.id,
        )
        assert credit.invoice_id == inv.id

    def test_create_credit_note_client_not_found(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.create_credit_note(client_identifier="nope", amount=100.0)

    def test_create_credit_note_negative_amount(self, svc, client_and_invoice):
        client, _ = client_and_invoice
        with pytest.raises(ValueError, match="positive"):
            svc.create_credit_note(client_identifier=client.id, amount=-50.0)

    def test_create_credit_note_zero_amount(self, svc, client_and_invoice):
        client, _ = client_and_invoice
        with pytest.raises(ValueError, match="positive"):
            svc.create_credit_note(client_identifier=client.id, amount=0.0)

    def test_create_credit_note_with_invalid_currency(self, svc, client_and_invoice):
        client, _ = client_and_invoice
        with pytest.raises(ValueError, match="Unsupported currency"):
            svc.create_credit_note(client_identifier=client.id, amount=100.0, currency="XYZ")

    def test_create_credit_note_invoice_wrong_client(self, svc):
        """Credit note can't link to another client's invoice."""
        client_a = svc.create_client(name="Client A")
        client_b = svc.create_client(name="Client B")
        inv = svc.create_invoice(
            client_identifier=client_a.id,
            line_items=[{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        )
        with pytest.raises(ValueError, match="does not belong"):
            svc.create_credit_note(
                client_identifier=client_b.id,
                amount=50.0,
                invoice_id=inv.id,
            )

    def test_create_credit_note_with_custom_currency(self, svc):
        client = svc.create_client(name="Euro Client", currency="EUR")
        credit = svc.create_credit_note(client_identifier=client.id, amount=100.0)
        assert credit.currency == "EUR"


class TestListCreditNotes:
    def test_list_all_credit_notes(self, svc, client_and_invoice):
        client, _ = client_and_invoice
        svc.create_credit_note(client_identifier=client.id, amount=100.0)
        svc.create_credit_note(client_identifier=client.id, amount=200.0)
        credits = svc.list_credit_notes()
        assert len(credits) == 2

    def test_list_by_status(self, svc, client_and_invoice):
        client, _ = client_and_invoice
        svc.create_credit_note(client_identifier=client.id, amount=100.0)
        credits = svc.list_credit_notes(status="open")
        assert len(credits) == 1
        credits = svc.list_credit_notes(status="applied")
        assert len(credits) == 0

    def test_list_by_client_name(self, svc, client_and_invoice):
        client, _ = client_and_invoice
        other = svc.create_client(name="Other Corp")
        svc.create_credit_note(client_identifier=client.id, amount=100.0)
        svc.create_credit_note(client_identifier=other.id, amount=50.0)
        credits = svc.list_credit_notes(client=client.name)
        assert len(credits) == 1

    def test_list_invalid_status(self, svc):
        with pytest.raises(ValueError, match="Invalid credit note status"):
            svc.list_credit_notes(status="bogus")


class TestApplyCreditNote:
    def test_apply_credit_note_full_payment(self, svc, client_and_invoice):
        """Apply credit note that fully covers an invoice."""
        client, inv = client_and_invoice
        credit = svc.create_credit_note(client_identifier=client.id, amount=1000.00)
        updated_credit, updated_inv = svc.apply_credit_note(credit.id, inv.id)
        # Invoice total = 1000 (10 × 100)
        assert updated_credit.applied_amount == 1000.00
        assert updated_credit.remaining_amount == 0.0
        assert updated_credit.status == CreditNoteStatus.APPLIED
        assert updated_inv.status == InvoiceStatus.PAID
        assert updated_inv.amount_paid == 1000.00
        assert updated_inv.amount_remaining == 0.0

    def test_apply_credit_note_partial_payment(self, svc, client_and_invoice):
        """Apply credit note that partially covers an invoice."""
        client, inv = client_and_invoice
        credit = svc.create_credit_note(client_identifier=client.id, amount=300.00)
        updated_credit, updated_inv = svc.apply_credit_note(credit.id, inv.id)
        # Invoice total = 1000
        assert updated_credit.applied_amount == 300.00
        assert updated_credit.remaining_amount == 0.0
        assert updated_credit.status == CreditNoteStatus.APPLIED
        assert updated_inv.status == InvoiceStatus.PARTIALLY_PAID
        assert updated_inv.amount_remaining == 700.00

    def test_apply_credit_note_with_explicit_amount(self, svc, client_and_invoice):
        """Apply credit note with a specific amount."""
        client, inv = client_and_invoice
        credit = svc.create_credit_note(client_identifier=client.id, amount=1000.00)
        updated_credit, updated_inv = svc.apply_credit_note(credit.id, inv.id, amount=400.0)
        assert updated_credit.applied_amount == 400.00
        assert updated_credit.remaining_amount == 600.00
        assert updated_credit.status == CreditNoteStatus.OPEN
        assert updated_inv.amount_paid == 400.00
        assert updated_inv.amount_remaining == 600.00

    def test_apply_credit_note_multiple_invoices(self, svc, client_and_invoice):
        """Apply credit note across multiple invoices."""
        client, inv1 = client_and_invoice
        inv2 = svc.create_invoice(
            client_identifier=client.id,
            line_items=[{"description": "More work", "quantity": 5, "unit_price": 100.0}],
        )
        credit = svc.create_credit_note(client_identifier=client.id, amount=1200.00)
        # Apply to inv1 (1000 total)
        svc.apply_credit_note(credit.id, inv1.id)
        # Apply remaining to inv2 (500 total)
        updated_credit, updated_inv2 = svc.apply_credit_note(credit.id, inv2.id)
        assert updated_credit.applied_amount == 1200.00
        assert updated_credit.remaining_amount == 0.0
        assert updated_inv2.amount_paid == 200.00

    def test_apply_credit_note_not_found(self, svc, client_and_invoice):
        _, inv = client_and_invoice
        with pytest.raises(ValueError, match="not found"):
            svc.apply_credit_note("CN-NOPE", inv.id)

    def test_apply_credit_note_to_paid_invoice(self, svc, client_and_invoice):
        """Can't apply credit to a fully paid invoice."""
        client, inv = client_and_invoice
        svc.add_payment(inv.id, amount=1000.0)
        credit = svc.create_credit_note(client_identifier=client.id, amount=500.0)
        with pytest.raises(ValueError, match="status paid"):
            svc.apply_credit_note(credit.id, inv.id)

    def test_apply_credit_note_currency_mismatch(self, svc):
        """Can't apply USD credit note to EUR invoice."""
        client_usd = svc.create_client(name="USD Client", currency="USD")
        client_eur = svc.create_client(name="EUR Client", currency="EUR")
        inv = svc.create_invoice(
            client_identifier=client_eur.id,
            line_items=[{"description": "Work", "quantity": 1, "unit_price": 100.0}],
            currency="EUR",
        )
        credit = svc.create_credit_note(client_identifier=client_usd.id, amount=100.0, currency="USD")
        with pytest.raises(ValueError, match="Currency mismatch"):
            svc.apply_credit_note(credit.id, inv.id)

    def test_apply_credit_note_void_fails(self, svc, client_and_invoice):
        """Can't apply a voided credit note."""
        client, inv = client_and_invoice
        credit = svc.create_credit_note(client_identifier=client.id, amount=100.0)
        svc.void_credit_note(credit.id)
        with pytest.raises(ValueError, match="voided"):
            svc.apply_credit_note(credit.id, inv.id)


class TestVoidCreditNote:
    def test_void_open_credit_note(self, svc, client_and_invoice):
        client, _ = client_and_invoice
        credit = svc.create_credit_note(client_identifier=client.id, amount=100.0)
        voided = svc.void_credit_note(credit.id)
        assert voided.status == CreditNoteStatus.VOID

    def test_void_already_applied_fails(self, svc, client_and_invoice):
        client, inv = client_and_invoice
        credit = svc.create_credit_note(client_identifier=client.id, amount=500.0)
        svc.apply_credit_note(credit.id, inv.id, amount=500.0)
        with pytest.raises(ValueError, match="applied"):
            svc.void_credit_note(credit.id)

    def test_void_not_found(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.void_credit_note("CN-NOPE")


class TestRemoveCreditNote:
    def test_remove_voided_credit_note(self, svc, client_and_invoice):
        client, _ = client_and_invoice
        credit = svc.create_credit_note(client_identifier=client.id, amount=100.0)
        svc.void_credit_note(credit.id)
        assert svc.remove_credit_note(credit.id) is True

    def test_remove_open_credit_note(self, svc, client_and_invoice):
        """Open credit notes can be removed if they have no applications."""
        client, _ = client_and_invoice
        credit = svc.create_credit_note(client_identifier=client.id, amount=100.0)
        assert svc.remove_credit_note(credit.id) is True

    def test_remove_applied_credit_note_fails(self, svc, client_and_invoice):
        client, inv = client_and_invoice
        credit = svc.create_credit_note(client_identifier=client.id, amount=500.0)
        svc.apply_credit_note(credit.id, inv.id, amount=500.0)
        with pytest.raises(ValueError, match="applied"):
            svc.remove_credit_note(credit.id)

    def test_remove_not_found(self, svc):
        assert svc.remove_credit_note("CN-NOPE") is False


class TestGetCreditNote:
    def test_get_existing(self, svc, client_and_invoice):
        client, _ = client_and_invoice
        credit = svc.create_credit_note(client_identifier=client.id, amount=100.0)
        fetched = svc.get_credit_note(credit.id)
        assert fetched is not None
        assert fetched.id == credit.id

    def test_get_nonexistent(self, svc):
        assert svc.get_credit_note("CN-NOPE") is None


class TestCreditNoteProperties:
    def test_remaining_amount_decreases_after_apply(self, svc, client_and_invoice):
        client, inv = client_and_invoice
        credit = svc.create_credit_note(client_identifier=client.id, amount=500.0)
        svc.apply_credit_note(credit.id, inv.id, amount=300.0)
        credit = svc.get_credit_note(credit.id)
        assert credit.remaining_amount == 200.0
        assert credit.applied_amount == 300.0
        assert credit.status == CreditNoteStatus.OPEN
