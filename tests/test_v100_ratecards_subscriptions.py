"""Tests for v1.0.0 — Rate Cards & Subscriptions (Recurring Billing).

Tests: rate cards (model pricing, cost calculation, usage recording),
subscription plans, subscription lifecycle (trial/active/cancel/pause),
subscription invoicing, MRR summary, batch usage recording.
"""

import pytest
from datetime import date, timedelta

from agent_invoice.models import (
    BillingCycle,
    SubscriptionStatus,
    UsageEvent,
)
from agent_invoice.service import InvoiceService
from agent_invoice.store import InvoiceStore


@pytest.fixture
def svc():
    import tempfile
    tmpdir = tempfile.mkdtemp()
    return InvoiceService(store=InvoiceStore(data_dir=tmpdir))


@pytest.fixture
def client(svc):
    return svc.add_client("Acme Corp", email="billing@acme.com")


# =============================================================================
# Rate Cards
# =============================================================================

class TestRateCards:
    def test_create_rate_card_minimal(self, svc):
        card = svc.create_rate_card(name="Test Card")
        assert card.id.startswith("RATE-")
        assert card.name == "Test Card"
        assert card.currency == "USD"
        assert card.active is True
        assert len(card.models) == 0

    def test_create_rate_card_with_models(self, svc):
        card = svc.create_rate_card(
            name="Prod 2026",
            currency="EUR",
            models=[
                {"provider": "openai", "model": "gpt-4", "input_rate": 30, "output_rate": 60},
                {"provider": "anthropic", "model": "claude-3", "input_rate": 15, "output_rate": 75, "cache_read_rate": 1.5},
            ],
        )
        assert card.currency == "EUR"
        assert len(card.models) == 2
        pricing = card.get_pricing("openai", "gpt-4")
        assert pricing is not None
        assert pricing.input_rate == 30
        assert pricing.output_rate == 60

    def test_create_rate_card_empty_name(self, svc):
        with pytest.raises(ValueError, match="name is required"):
            svc.create_rate_card(name="")

    def test_get_rate_card(self, svc):
        card = svc.create_rate_card(name="Test")
        fetched = svc.get_rate_card(card.id)
        assert fetched is not None
        assert fetched.id == card.id
        assert svc.get_rate_card("RATE-NOPE") is None

    def test_list_rate_cards(self, svc):
        svc.create_rate_card(name="Card 1", active=True)
        svc.create_rate_card(name="Card 2", active=False)
        all_cards = svc.list_rate_cards()
        assert len(all_cards) == 2
        active = svc.list_rate_cards(active_only=True)
        assert len(active) == 1
        assert active[0].name == "Card 1"

    def test_update_rate_card(self, svc):
        card = svc.create_rate_card(name="Old")
        updated = svc.update_rate_card(card.id, name="New", currency="EUR", active=False)
        assert updated.name == "New"
        assert updated.currency == "EUR"
        assert updated.active is False

    def test_update_rate_card_not_found(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.update_rate_card("RATE-NOPE", name="X")

    def test_remove_rate_card(self, svc):
        card = svc.create_rate_card(name="Test")
        assert svc.remove_rate_card(card.id) is True
        assert svc.remove_rate_card(card.id) is False

    def test_add_model_pricing(self, svc):
        card = svc.create_rate_card(name="Test")
        updated = svc.add_model_pricing(
            card_id=card.id,
            provider="openai",
            model="gpt-4",
            input_rate=30,
            output_rate=60,
            cache_read_rate=1.5,
            request_rate=0.002,
        )
        assert len(updated.models) == 1
        pricing = updated.get_pricing("openai", "gpt-4")
        assert pricing.input_rate == 30
        assert pricing.request_rate == 0.002

    def test_add_model_pricing_negative(self, svc):
        card = svc.create_rate_card(name="Test")
        with pytest.raises(ValueError, match="cannot be negative"):
            svc.add_model_pricing(card.id, "openai", "gpt-4", input_rate=-1, output_rate=0)

    def test_remove_model_pricing(self, svc):
        card = svc.create_rate_card(name="Test")
        svc.add_model_pricing(card.id, "openai", "gpt-4", input_rate=30, output_rate=60)
        updated = svc.remove_model_pricing(card.id, "openai", "gpt-4")
        assert len(updated.models) == 0

    def test_remove_model_pricing_not_found(self, svc):
        card = svc.create_rate_card(name="Test")
        with pytest.raises(ValueError, match="No pricing found"):
            svc.remove_model_pricing(card.id, "openai", "gpt-4")

    def test_calculate_usage_cost(self, svc):
        card = svc.create_rate_card(
            name="Test",
            models=[{"provider": "openai", "model": "gpt-4", "input_rate": 30, "output_rate": 60}],
        )
        # 1M tokens @ $30/M = $30 input, 500K @ $60/M = $30 output
        cost = svc.calculate_usage_cost(card.id, "openai", "gpt-4", input_tokens=1_000_000, output_tokens=500_000)
        assert cost == 60.0

    def test_calculate_usage_cost_no_pricing(self, svc):
        card = svc.create_rate_card(name="Test")
        cost = svc.calculate_usage_cost(card.id, "openai", "gpt-4", input_tokens=1000)
        assert cost is None

    def test_calculate_usage_cost_card_not_found(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.calculate_usage_cost("RATE-NOPE", "openai", "gpt-4")

    def test_calculate_with_request_rate(self, svc):
        card = svc.create_rate_card(name="Test")
        svc.add_model_pricing(card.id, "openai", "gpt-4", input_rate=0, output_rate=0, request_rate=0.01)
        cost = svc.calculate_usage_cost(card.id, "openai", "gpt-4", request_count=100)
        assert cost == 1.0


class TestUsageWithRateCard:
    def test_record_usage_with_rate_card(self, svc, client):
        card = svc.create_rate_card(
            name="Test",
            models=[{"provider": "openai", "model": "gpt-4", "input_rate": 30, "output_rate": 60}],
        )
        event = svc.record_usage_with_rate_card(
            card_id=card.id,
            description="GPT-4 chat",
            provider="openai",
            model="gpt-4",
            client_identifier=client.name,
            input_tokens=1000,
            output_tokens=500,
        )
        # 1000 * 30/1M = 0.03, 500 * 60/1M = 0.03 => 0.06
        assert event.cost == 0.06
        assert event.currency == "USD"
        assert event.client_name == "Acme Corp"

    def test_record_usage_no_pricing_raises(self, svc, client):
        card = svc.create_rate_card(name="Test")
        with pytest.raises(ValueError, match="no pricing for openai:gpt-4"):
            svc.record_usage_with_rate_card(
                card_id=card.id,
                description="chat",
                provider="openai",
                model="gpt-4",
            )

    def test_record_usage_card_not_found(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.record_usage_with_rate_card(
                card_id="RATE-NOPE",
                description="x",
                provider="openai",
                model="gpt-4",
            )


class TestBatchUsage:
    def test_batch_with_rate_card(self, svc, client):
        card = svc.create_rate_card(
            name="Test",
            models=[{"provider": "openai", "model": "gpt-4", "input_rate": 30, "output_rate": 60}],
        )
        result = svc.batch_record_usage(
            events=[
                {"description": "call 1", "provider": "openai", "model": "gpt-4", "input_tokens": 1000, "output_tokens": 500},
                {"description": "call 2", "provider": "openai", "model": "gpt-4", "input_tokens": 2000, "output_tokens": 1000},
            ],
            card_id=card.id,
        )
        assert result.total_recorded == 2
        assert result.total_failed == 0
        assert result.total_cost == 0.18  # 0.06 + 0.12
        assert len(result.event_ids) == 2

    def test_batch_with_explicit_cost(self, svc, client):
        result = svc.batch_record_usage(
            events=[
                {"description": "call 1", "provider": "openai", "model": "gpt-4", "cost": 0.05},
                {"description": "call 2", "provider": "openai", "model": "gpt-4", "cost": 0.10},
            ],
        )
        assert result.total_recorded == 2
        assert result.total_cost == 0.15

    def test_batch_missing_cost_and_no_card(self, svc):
        result = svc.batch_record_usage(
            events=[
                {"description": "call 1", "provider": "openai", "model": "gpt-4"},
            ],
        )
        assert result.total_recorded == 0
        assert result.total_failed == 1
        assert "no 'cost'" in result.errors[0]["error"]

    def test_batch_partial_failure(self, svc, client):
        card = svc.create_rate_card(
            name="Test",
            models=[{"provider": "openai", "model": "gpt-4", "input_rate": 30, "output_rate": 60}],
        )
        result = svc.batch_record_usage(
            events=[
                {"description": "ok", "provider": "openai", "model": "gpt-4", "input_tokens": 1000},
                {"description": "bad", "provider": "google", "model": "gemini", "input_tokens": 1000},  # no pricing
            ],
            card_id=card.id,
        )
        assert result.total_recorded == 1
        assert result.total_failed == 1
        assert "No pricing for google:gemini" in result.errors[0]["error"]

    def test_batch_empty_raises(self, svc):
        with pytest.raises(ValueError, match="No events"):
            svc.batch_record_usage(events=[])


# =============================================================================
# Subscription Plans
# =============================================================================

class TestSubscriptionPlans:
    def test_create_plan(self, svc):
        plan = svc.create_plan(name="Pro", price=199.0, billing_cycle="monthly", trial_days=14)
        assert plan.id.startswith("PLN-")
        assert plan.name == "Pro"
        assert plan.price == 199.0
        assert plan.billing_cycle == BillingCycle.MONTHLY
        assert plan.trial_days == 14

    def test_create_plan_empty_name(self, svc):
        with pytest.raises(ValueError, match="name is required"):
            svc.create_plan(name="", price=10)

    def test_create_plan_negative_price(self, svc):
        with pytest.raises(ValueError, match="cannot be negative"):
            svc.create_plan(name="X", price=-5)

    def test_plan_monthly_price_normalization(self, svc):
        monthly = svc.create_plan(name="M", price=100, billing_cycle="monthly")
        yearly = svc.create_plan(name="Y", price=1200, billing_cycle="yearly")
        weekly = svc.create_plan(name="W", price=25, billing_cycle="weekly")
        assert monthly.monthly_price == 100.0
        assert yearly.monthly_price == 98.63  # 1200 * 30/365
        assert weekly.monthly_price == 107.14  # 25 * 30/7

    def test_get_plan(self, svc):
        plan = svc.create_plan(name="Pro", price=199)
        fetched = svc.get_plan(plan.id)
        assert fetched is not None
        assert fetched.name == "Pro"
        assert svc.get_plan("PLN-NOPE") is None

    def test_list_plans(self, svc):
        svc.create_plan(name="Active", price=10, active=True)
        svc.create_plan(name="Deprecated", price=5, active=False)
        all_plans = svc.list_plans()
        assert len(all_plans) == 2
        active = svc.list_plans(active_only=True)
        assert len(active) == 1
        assert active[0].name == "Active"

    def test_update_plan(self, svc):
        plan = svc.create_plan(name="Old", price=50)
        updated = svc.update_plan(plan.id, name="New", price=75, active=False)
        assert updated.name == "New"
        assert updated.price == 75.0
        assert updated.active is False

    def test_update_plan_not_found(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.update_plan("PLN-NOPE", name="X")

    def test_remove_plan(self, svc):
        plan = svc.create_plan(name="Test", price=10)
        assert svc.remove_plan(plan.id) is True
        assert svc.remove_plan(plan.id) is False

    def test_seed_builtin_plans(self, svc):
        plans = svc.seed_builtin_plans()
        assert len(plans) == 4
        names = [p.name for p in plans]
        assert "Starter Agent" in names
        assert "Professional Agent" in names
        assert "Enterprise Agent" in names

    def test_seed_builtin_plans_idempotent(self, svc):
        svc.seed_builtin_plans()
        plans = svc.seed_builtin_plans()
        assert len(plans) == 4  # still 4, not 8

    def test_seed_builtin_plans_overwrite(self, svc):
        svc.seed_builtin_plans()
        # Modify a plan
        svc.update_plan("PLN-STARTER", price=999)
        # Re-seed without overwrite
        svc.seed_builtin_plans(overwrite=False)
        assert svc.get_plan("PLN-STARTER").price == 999  # unchanged
        # Re-seed with overwrite
        svc.seed_builtin_plans(overwrite=True)
        assert svc.get_plan("PLN-STARTER").price == 49.0  # reset


# =============================================================================
# Subscriptions
# =============================================================================

class TestSubscriptions:
    def test_create_subscription_with_trial(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=14)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        assert sub.status == SubscriptionStatus.TRIALING
        assert sub.is_in_trial
        assert sub.trial_days_remaining == 14
        assert not sub.is_billable  # trialing, not billable yet

    def test_create_subscription_no_trial(self, svc, client):
        plan = svc.create_plan(name="Basic", price=29, trial_days=0)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        assert sub.status == SubscriptionStatus.ACTIVE
        assert not sub.is_in_trial
        assert sub.is_billable

    def test_create_subscription_client_not_found(self, svc):
        plan = svc.create_plan(name="Pro", price=199)
        with pytest.raises(ValueError, match="Client 'Nobody' not found"):
            svc.create_subscription(client_identifier="Nobody", plan_id=plan.id)

    def test_create_subscription_plan_not_found(self, svc, client):
        with pytest.raises(ValueError, match="Plan 'PLN-NOPE' not found"):
            svc.create_subscription(client_identifier=client.name, plan_id="PLN-NOPE")

    def test_create_subscription_inactive_plan(self, svc, client):
        plan = svc.create_plan(name="Dead", price=10, active=False)
        with pytest.raises(ValueError, match="not active"):
            svc.create_subscription(client_identifier=client.name, plan_id=plan.id)

    def test_get_subscription(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        fetched = svc.get_subscription(sub.id)
        assert fetched is not None
        assert fetched.id == sub.id
        assert svc.get_subscription("SUB-NOPE") is None

    def test_list_subscriptions(self, svc, client):
        plan1 = svc.create_plan(name="A", price=10, trial_days=0)
        plan2 = svc.create_plan(name="B", price=20, trial_days=14)
        svc.create_subscription(client_identifier=client.name, plan_id=plan1.id)
        svc.create_subscription(client_identifier=client.name, plan_id=plan2.id)
        all_subs = svc.list_subscriptions()
        assert len(all_subs) == 2
        active = svc.list_subscriptions(status="active")
        assert len(active) == 1
        trialing = svc.list_subscriptions(status="trialing")
        assert len(trialing) == 1

    def test_list_subscriptions_by_plan(self, svc, client):
        plan1 = svc.create_plan(name="A", price=10, trial_days=0)
        plan2 = svc.create_plan(name="B", price=20, trial_days=0)
        svc.create_subscription(client_identifier=client.name, plan_id=plan1.id)
        svc.create_subscription(client_identifier=client.name, plan_id=plan2.id)
        by_plan = svc.list_subscriptions(plan_id=plan1.id)
        assert len(by_plan) == 1

    def test_cancel_subscription_immediate(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=0)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        cancelled = svc.cancel_subscription(sub.id, immediately=True)
        assert cancelled.status == SubscriptionStatus.CANCELLED
        assert cancelled.ended_at is not None

    def test_cancel_subscription_at_period_end(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=0)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        cancelled = svc.cancel_subscription(sub.id, immediately=False)
        assert cancelled.status == SubscriptionStatus.ACTIVE  # still active
        assert cancelled.cancelled_at is not None
        assert cancelled.next_billing_date is None  # won't renew

    def test_cancel_already_cancelled(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=0)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        svc.cancel_subscription(sub.id, immediately=True)
        with pytest.raises(ValueError, match="already cancelled"):
            svc.cancel_subscription(sub.id)

    def test_pause_and_resume(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=0)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        paused = svc.pause_subscription(sub.id)
        assert paused.status == SubscriptionStatus.PAUSED
        resumed = svc.resume_subscription(sub.id)
        assert resumed.status == SubscriptionStatus.ACTIVE

    def test_resume_not_paused_raises(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=0)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        with pytest.raises(ValueError, match="Only paused"):
            svc.resume_subscription(sub.id)

    def test_remove_subscription(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=0)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        assert svc.remove_subscription(sub.id) is True
        assert svc.remove_subscription(sub.id) is False


class TestSubscriptionInvoicing:
    def test_generate_invoice_active(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=0, tax_rate=8.5)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        inv = svc.generate_subscription_invoice(sub.id)
        assert inv.total > 0
        assert inv.client_name == "Acme Corp"
        assert inv.currency == "USD"

    def test_generate_invoice_trialing_raises(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=14)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        with pytest.raises(ValueError, match="only active or past_due"):
            svc.generate_subscription_invoice(sub.id)

    def test_generate_invoice_advances_period(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=0)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        original_end = sub.current_period_end
        svc.generate_subscription_invoice(sub.id)
        updated = svc.get_subscription(sub.id)
        assert updated.current_period_start == original_end
        assert updated.current_period_end > original_end
        assert len(updated.invoice_ids) == 1

    def test_generate_multiple_invoices(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=0)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        svc.generate_subscription_invoice(sub.id)
        svc.generate_subscription_invoice(sub.id)
        updated = svc.get_subscription(sub.id)
        assert len(updated.invoice_ids) == 2

    def test_generate_invoice_cancelled_raises(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=0)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        svc.cancel_subscription(sub.id, immediately=True)
        with pytest.raises(ValueError, match="cancelled"):
            svc.generate_subscription_invoice(sub.id)


class TestProcessDueSubscriptions:
    def test_process_due_generates_for_active(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=0)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        # next_billing_date is today, so it should be due
        invoices = svc.process_due_subscriptions()
        assert len(invoices) == 1
        assert invoices[0].client_name == "Acme Corp"

    def test_process_due_skips_trialing(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=14)
        svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        invoices = svc.process_due_subscriptions()
        assert len(invoices) == 0

    def test_process_due_with_future_cutoff(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=0)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        # next_billing_date is today; cutoff in past shouldn't trigger
        yesterday = date.today() - timedelta(days=1)
        invoices = svc.process_due_subscriptions(as_of=yesterday)
        assert len(invoices) == 0


# =============================================================================
# MRR Summary
# =============================================================================

class TestMRRSummary:
    def test_mrr_empty(self, svc):
        summary = svc.get_mrr_summary()
        assert summary.mrr == 0.0
        assert summary.arr == 0.0
        assert summary.active_count == 0
        assert summary.total_count == 0

    def test_mrr_with_active_subscriptions(self, svc, client):
        plan_monthly = svc.create_plan(name="M", price=100, trial_days=0)
        plan_yearly = svc.create_plan(name="Y", price=1200, trial_days=0, billing_cycle="yearly")
        svc.create_subscription(client_identifier=client.name, plan_id=plan_monthly.id)
        svc.create_subscription(client_identifier=client.name, plan_id=plan_yearly.id)
        summary = svc.get_mrr_summary()
        assert summary.active_count == 2
        # monthly: $100/yr, yearly: $1200/12 = $100/mo
        assert summary.mrr == 198.63  # 100 + 98.63

    def test_mrr_excludes_trialing(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=14)
        svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        summary = svc.get_mrr_summary()
        assert summary.mrr == 0.0  # trialing not counted in MRR
        assert summary.trialing_count == 1
        assert summary.trial_mrr == 199.0

    def test_mrr_excludes_paused(self, svc, client):
        plan = svc.create_plan(name="Pro", price=199, trial_days=0)
        sub = svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        svc.pause_subscription(sub.id)
        summary = svc.get_mrr_summary()
        assert summary.mrr == 0.0
        assert summary.paused_count == 1
        assert summary.paused_mrr == 199.0

    def test_mrr_arr_calculation(self, svc, client):
        plan = svc.create_plan(name="Pro", price=100, trial_days=0)
        svc.create_subscription(client_identifier=client.name, plan_id=plan.id)
        summary = svc.get_mrr_summary()
        assert summary.mrr == 100.0
        assert summary.arr == 1200.0

    def test_mrr_by_plan(self, svc, client):
        plan1 = svc.create_plan(name="Basic", price=50, trial_days=0)
        plan2 = svc.create_plan(name="Pro", price=200, trial_days=0)
        svc.create_subscription(client_identifier=client.name, plan_id=plan1.id)
        svc.create_subscription(client_identifier=client.name, plan_id=plan1.id)
        svc.create_subscription(client_identifier=client.name, plan_id=plan2.id)
        summary = svc.get_mrr_summary()
        assert len(summary.by_plan) == 2
        pro = [p for p in summary.by_plan if p["plan_name"] == "Pro"][0]
        basic = [p for p in summary.by_plan if p["plan_name"] == "Basic"][0]
        assert pro["count"] == 1
        assert pro["mrr"] == 200.0
        assert basic["count"] == 2
        assert basic["mrr"] == 100.0

    def test_mrr_filter_by_currency(self, svc, client):
        plan_usd = svc.create_plan(name="USD Plan", price=100, currency="USD", trial_days=0)
        plan_eur = svc.create_plan(name="EUR Plan", price=90, currency="EUR", trial_days=0)
        svc.create_subscription(client_identifier=client.name, plan_id=plan_usd.id)
        svc.create_subscription(client_identifier=client.name, plan_id=plan_eur.id)
        summary = svc.get_mrr_summary(currency="EUR")
        assert summary.active_count == 1
        assert summary.mrr == 90.0

    def test_mrr_avg_subscription_value(self, svc, client):
        plan1 = svc.create_plan(name="Basic", price=50, trial_days=0)
        plan2 = svc.create_plan(name="Pro", price=200, trial_days=0)
        svc.create_subscription(client_identifier=client.name, plan_id=plan1.id)
        svc.create_subscription(client_identifier=client.name, plan_id=plan2.id)
        summary = svc.get_mrr_summary()
        assert summary.avg_subscription_value == 125.0  # (50+200)/2
