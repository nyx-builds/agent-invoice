"""Tests for v0.8.0 Usage Metering & Agent Billing."""

import tempfile
from datetime import date, timedelta

import pytest

from agent_invoice.models import UsageEvent, UsageSummary
from agent_invoice.service import InvoiceService
from agent_invoice.store import InvoiceStore


@pytest.fixture
def svc():
    """Create a service with a temporary data directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = InvoiceStore(data_dir=tmpdir)
        yield InvoiceService(store=store)


@pytest.fixture
def svc_with_client(svc):
    """Service with a pre-registered client."""
    svc.add_client("Acme Corp", email="billing@acme.com", currency="USD")
    return svc


@pytest.fixture
def svc_with_usage(svc_with_client):
    """Service with client and multiple usage events."""
    s = svc_with_client
    s.record_usage(
        description="Claude Sonnet inference",
        cost=1.50,
        client_identifier="Acme Corp",
        provider="anthropic",
        model="claude-3-5-sonnet",
        input_tokens=5000,
        output_tokens=2000,
        request_count=3,
    )
    s.record_usage(
        description="GPT-4 inference",
        cost=2.00,
        client_identifier="Acme Corp",
        provider="openai",
        model="gpt-4",
        input_tokens=3000,
        output_tokens=1500,
        request_count=2,
    )
    s.record_usage(
        description="More Claude usage",
        cost=0.75,
        client_identifier="Acme Corp",
        provider="anthropic",
        model="claude-3-5-sonnet",
        input_tokens=2000,
        output_tokens=500,
        request_count=1,
    )
    return s


class TestRecordUsage:
    """Test record_usage service method."""

    def test_record_basic_usage(self, svc_with_client):
        event = svc_with_client.record_usage(
            description="API call",
            cost=0.50,
            client_identifier="Acme Corp",
        )
        assert event.id.startswith("USE-")
        assert event.cost == 0.50
        assert event.client_id is not None
        assert event.client_name == "Acme Corp"
        assert event.provider == "openai"  # default
        assert event.billed is False
        assert event.invoice_id is None

    def test_record_full_usage(self, svc_with_client):
        event = svc_with_client.record_usage(
            description="Claude inference",
            cost=1.234567,
            client_identifier="Acme Corp",
            provider="anthropic",
            model="claude-3-opus",
            input_tokens=10000,
            output_tokens=5000,
            cache_read_tokens=2000,
            cache_write_tokens=1000,
            request_count=5,
            metadata={"project": "webapp", "agent_id": "agent-001"},
        )
        assert event.provider == "anthropic"
        assert event.model == "claude-3-opus"
        assert event.input_tokens == 10000
        assert event.output_tokens == 5000
        assert event.cache_read_tokens == 2000
        assert event.cache_write_tokens == 1000
        assert event.request_count == 5
        assert event.total_tokens == 18000
        assert event.metadata["project"] == "webapp"
        assert event.cost == 1.234567  # 6 decimal precision

    def test_record_usage_no_client(self, svc):
        """Usage can be recorded without a client (unattributed)."""
        event = svc.record_usage(
            description="Internal compute",
            cost=0.30,
        )
        assert event.client_id is None
        assert event.client_name is None

    def test_record_usage_nonexistent_client(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.record_usage(
                description="Test",
                cost=1.0,
                client_identifier="Nonexistent",
            )

    def test_record_usage_negative_cost(self, svc):
        with pytest.raises(ValueError, match="cannot be negative"):
            svc.record_usage(
                description="Test",
                cost=-1.0,
            )

    def test_record_usage_zero_cost(self, svc):
        """Zero cost is allowed (free tier)."""
        event = svc.record_usage(description="Free tier", cost=0.0)
        assert event.cost == 0.0


class TestGetUsageEvent:
    def test_get_existing_event(self, svc_with_client):
        event = svc_with_client.record_usage(description="Test", cost=1.0)
        fetched = svc_with_client.get_usage_event(event.id)
        assert fetched is not None
        assert fetched.id == event.id

    def test_get_nonexistent_event(self, svc):
        assert svc.get_usage_event("USE-NONEXIST") is None


class TestListUsageEvents:
    def test_list_all(self, svc_with_usage):
        events = svc_with_usage.list_usage_events()
        assert len(events) == 3

    def test_list_by_client(self, svc_with_usage):
        events = svc_with_usage.list_usage_events(client_identifier="Acme Corp")
        assert len(events) == 3

    def test_list_by_provider(self, svc_with_usage):
        events = svc_with_usage.list_usage_events(provider="anthropic")
        assert len(events) == 2
        for e in events:
            assert e.provider == "anthropic"

    def test_list_by_model(self, svc_with_usage):
        events = svc_with_usage.list_usage_events(model="gpt-4")
        assert len(events) == 1
        assert events[0].model == "gpt-4"

    def test_list_by_billed_status(self, svc_with_usage):
        events = svc_with_usage.list_usage_events(billed=False)
        assert len(events) == 3
        events = svc_with_usage.list_usage_events(billed=True)
        assert len(events) == 0

    def test_list_by_date_range(self, svc_with_usage):
        today = date.today()
        events = svc_with_usage.list_usage_events(
            date_from=today,
            date_to=today,
        )
        assert len(events) == 3

    def test_list_by_date_range_future(self, svc_with_usage):
        future = date.today() + timedelta(days=365)
        events = svc_with_usage.list_usage_events(date_from=future)
        assert len(events) == 0


class TestRemoveUsageEvent:
    def test_remove_unbilled(self, svc_with_usage):
        events = svc_with_usage.list_usage_events()
        event_id = events[0].id
        assert svc_with_usage.remove_usage_event(event_id) is True
        assert svc_with_usage.get_usage_event(event_id) is None

    def test_remove_nonexistent(self, svc):
        assert svc.remove_usage_event("USE-NONEXIST") is False

    def test_remove_billed_event(self, svc_with_usage):
        """Cannot delete a billed usage event."""
        events = svc_with_usage.list_usage_events()
        event = events[0]
        event.billed = True
        svc_with_usage.store.save_usage_event(event)

        with pytest.raises(ValueError, match="Cannot delete billed"):
            svc_with_usage.remove_usage_event(event.id)


class TestUsageSummary:
    def test_summary_totals(self, svc_with_usage):
        summary = svc_with_usage.get_usage_summary()
        assert summary.total_events == 3
        assert summary.total_cost == round(1.50 + 2.00 + 0.75, 6)
        assert summary.unbilled_events == 3
        assert summary.billed_events == 0
        assert summary.unbilled_cost == summary.total_cost
        assert summary.billed_cost == 0.0

    def test_summary_token_totals(self, svc_with_usage):
        summary = svc_with_usage.get_usage_summary()
        # input: 5000 + 3000 + 2000 = 10000
        # output: 2000 + 1500 + 500 = 4000
        assert summary.total_input_tokens == 10000
        assert summary.total_output_tokens == 4000
        assert summary.total_tokens == 14000

    def test_summary_by_provider(self, svc_with_usage):
        summary = svc_with_usage.get_usage_summary()
        by_provider = {p["provider"]: p for p in summary.by_provider}
        assert "anthropic" in by_provider
        assert "openai" in by_provider
        assert by_provider["anthropic"]["events"] == 2
        assert by_provider["openai"]["events"] == 1
        # anthropic cost: 1.50 + 0.75 = 2.25
        assert by_provider["anthropic"]["cost"] == round(2.25, 6)

    def test_summary_by_model(self, svc_with_usage):
        summary = svc_with_usage.get_usage_summary()
        by_model = {m["model"]: m for m in summary.by_model}
        assert by_model["claude-3-5-sonnet"]["events"] == 2
        assert by_model["gpt-4"]["events"] == 1

    def test_summary_by_client(self, svc_with_usage):
        summary = svc_with_usage.get_usage_summary()
        assert len(summary.by_client) >= 1
        acme = [c for c in summary.by_client if c["client_name"] == "Acme Corp"]
        assert len(acme) == 1
        assert acme[0]["events"] == 3

    def test_summary_daily(self, svc_with_usage):
        summary = svc_with_usage.get_usage_summary()
        assert len(summary.daily) >= 1
        today_str = date.today().strftime("%Y-%m-%d")
        today_entry = [d for d in summary.daily if d["date"] == today_str]
        assert len(today_entry) == 1
        assert today_entry[0]["events"] == 3

    def test_summary_with_filters(self, svc_with_usage):
        summary = svc_with_usage.get_usage_summary(provider="anthropic")
        assert summary.total_events == 2
        assert summary.total_cost == round(1.50 + 0.75, 6)

    def test_summary_empty(self, svc):
        summary = svc.get_usage_summary()
        assert summary.total_events == 0
        assert summary.total_cost == 0.0
        assert summary.by_provider == []
        assert summary.by_client == []


class TestAggregateUsage:
    def test_aggregate_basic(self, svc_with_usage):
        today = date.today()
        record = svc_with_usage.aggregate_usage_to_record(
            client_identifier="Acme Corp",
            period_start=today,
            period_end=today,
        )
        assert record["client_name"] == "Acme Corp"
        assert record["event_count"] == 3
        assert record["total_cost"] == round(1.50 + 2.00 + 0.75, 2)
        assert len(record["line_items"]) == 2  # 2 unique provider/model pairs

    def test_aggregate_line_items_content(self, svc_with_usage):
        today = date.today()
        record = svc_with_usage.aggregate_usage_to_record(
            client_identifier="Acme Corp",
            period_start=today,
            period_end=today,
        )
        # Check line items have proper descriptions
        descriptions = [li["description"] for li in record["line_items"]]
        assert any("anthropic" in d for d in descriptions)
        assert any("openai" in d for d in descriptions)

        # Check costs
        for li in record["line_items"]:
            assert li["quantity"] == 1
            assert li["unit_price"] > 0

    def test_aggregate_provider_breakdown(self, svc_with_usage):
        today = date.today()
        record = svc_with_usage.aggregate_usage_to_record(
            client_identifier="Acme Corp",
            period_start=today,
            period_end=today,
        )
        providers = {p["provider"] for p in record["provider_breakdown"]}
        assert "anthropic" in providers
        assert "openai" in providers

    def test_aggregate_no_events(self, svc_with_client):
        today = date.today()
        record = svc_with_client.aggregate_usage_to_record(
            client_identifier="Acme Corp",
            period_start=today,
            period_end=today,
        )
        assert record["event_count"] == 0
        assert record["total_cost"] == 0.0
        assert record["line_items"] == []

    def test_aggregate_nonexistent_client(self, svc):
        today = date.today()
        with pytest.raises(ValueError, match="not found"):
            svc.aggregate_usage_to_record(
                client_identifier="Ghost",
                period_start=today,
                period_end=today,
            )

    def test_aggregate_excludes_billed(self, svc_with_usage):
        """By default, only unbilled events are aggregated."""
        events = svc_with_usage.list_usage_events()
        # Mark one as billed
        event = events[0]
        event.billed = True
        event.invoice_id = "INV-0001"
        svc_with_usage.store.save_usage_event(event)

        today = date.today()
        record = svc_with_usage.aggregate_usage_to_record(
            client_identifier="Acme Corp",
            period_start=today,
            period_end=today,
        )
        assert record["event_count"] == 2  # Only unbilled

    def test_aggregate_includes_billed(self, svc_with_usage):
        """Can include billed events with include_billed=True."""
        events = svc_with_usage.list_usage_events()
        event = events[0]
        event.billed = True
        event.invoice_id = "INV-0001"
        svc_with_usage.store.save_usage_event(event)

        today = date.today()
        record = svc_with_usage.aggregate_usage_to_record(
            client_identifier="Acme Corp",
            period_start=today,
            period_end=today,
            include_billed=True,
        )
        assert record["event_count"] == 3


class TestCreateInvoiceFromUsage:
    def test_create_invoice_basic(self, svc_with_usage):
        today = date.today()
        invoice, record = svc_with_usage.create_invoice_from_usage(
            client_identifier="Acme Corp",
            period_start=today,
            period_end=today,
        )
        assert invoice.id.startswith("INV-")
        assert invoice.client_name == "Acme Corp"
        assert len(invoice.line_items) == 2
        # Total should equal sum of all usage costs
        assert invoice.total == round(1.50 + 2.00 + 0.75, 2)

    def test_events_marked_billed(self, svc_with_usage):
        today = date.today()
        invoice, record = svc_with_usage.create_invoice_from_usage(
            client_identifier="Acme Corp",
            period_start=today,
            period_end=today,
        )
        # All events should now be billed
        events = svc_with_usage.list_usage_events()
        for e in events:
            assert e.billed is True
            assert e.invoice_id == invoice.id

    def test_no_unbilled_remaining(self, svc_with_usage):
        today = date.today()
        svc_with_usage.create_invoice_from_usage(
            client_identifier="Acme Corp",
            period_start=today,
            period_end=today,
        )
        summary = svc_with_usage.get_usage_summary()
        assert summary.unbilled_events == 0
        assert summary.billed_events == 3

    def test_double_invoicing_fails(self, svc_with_usage):
        today = date.today()
        # First invoice
        svc_with_usage.create_invoice_from_usage(
            client_identifier="Acme Corp",
            period_start=today,
            period_end=today,
        )
        # Second invoice should fail — no unbilled events
        with pytest.raises(ValueError, match="No unbilled usage events"):
            svc_with_usage.create_invoice_from_usage(
                client_identifier="Acme Corp",
                period_start=today,
                period_end=today,
            )

    def test_invoice_with_markup(self, svc_with_usage):
        today = date.today()
        invoice, record = svc_with_usage.create_invoice_from_usage(
            client_identifier="Acme Corp",
            period_start=today,
            period_end=today,
            markup_percent=20.0,  # 20% markup
        )
        base_cost = round(1.50 + 2.00 + 0.75, 2)  # 4.25
        expected_total = round(base_cost * 1.20, 2)
        assert invoice.total == expected_total

    def test_invoice_with_notes(self, svc_with_usage):
        today = date.today()
        invoice, record = svc_with_usage.create_invoice_from_usage(
            client_identifier="Acme Corp",
            period_start=today,
            period_end=today,
            notes="Monthly AI usage",
        )
        assert "Monthly AI usage" in invoice.notes
        assert "Usage-based billing" in invoice.notes

    def test_invoice_due_date(self, svc_with_usage):
        today = date.today()
        invoice, record = svc_with_usage.create_invoice_from_usage(
            client_identifier="Acme Corp",
            period_start=today,
            period_end=today,
            due_days=15,
        )
        assert invoice.due_date == today + timedelta(days=15)

    def test_no_events_raises(self, svc_with_client):
        today = date.today()
        with pytest.raises(ValueError, match="No unbilled usage events"):
            svc_with_client.create_invoice_from_usage(
                client_identifier="Acme Corp",
                period_start=today,
                period_end=today,
            )


class TestUsageEventModel:
    def test_total_tokens_property(self):
        event = UsageEvent(
            description="Test",
            cost=1.0,
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=20,
            cache_write_tokens=10,
        )
        assert event.total_tokens == 180

    def test_default_values(self):
        event = UsageEvent(description="Test", cost=1.0)
        assert event.provider == "openai"
        assert event.request_count == 1
        assert event.billed is False
        assert event.metadata == {}
        assert event.input_tokens == 0
        assert event.currency == "USD"

    def test_id_format(self):
        event = UsageEvent(description="Test", cost=1.0)
        assert event.id.startswith("USE-")
        assert len(event.id) == 12  # USE- + 8 hex chars


class TestUsageSummaryModel:
    def test_defaults(self):
        summary = UsageSummary()
        assert summary.total_events == 0
        assert summary.total_cost == 0.0
        assert summary.by_provider == []
