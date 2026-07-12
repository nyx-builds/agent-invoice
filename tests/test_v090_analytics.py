"""Tests for v0.9.0 — Usage Analytics & Cost Intelligence.

Tests: cost trends, projections, anomaly detection, model efficiency, provider comparison.
"""

import pytest
from datetime import date, datetime, timedelta, timezone

from agent_invoice.models import (
    CostTrend,
    CostProjection,
    CostAnomaly,
    AnomalyReport,
    ModelEfficiency,
    EfficiencyReport,
    ProviderComparison,
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
def populated_svc():
    """Service with diverse usage data across providers, models, and dates."""
    import tempfile
    tmpdir = tempfile.mkdtemp()
    svc = InvoiceService(store=InvoiceStore(data_dir=tmpdir))
    client = svc.add_client("Acme Corp")

    today = date.today()
    # Create events across 10 days, 2 providers, 3 models
    for i in range(10):
        d = today - timedelta(days=9 - i)

        # OpenAI / GPT-4 — consistent cost
        e1 = UsageEvent(
            client_id=client.id,
            client_name=client.name,
            description=f"GPT-4 inference day {i}",
            provider="openai",
            model="gpt-4",
            input_tokens=1000,
            output_tokens=500,
            cost=0.05,
            currency="USD",
            recorded_at=datetime(d.year, d.month, d.day, tzinfo=timezone.utc),
        )
        svc.store.save_usage_event(e1)

        # Anthropic / Claude — varying cost (spike on day 5)
        spike_cost = 0.50 if i == 5 else 0.03
        e2 = UsageEvent(
            client_id=client.id,
            client_name=client.name,
            description=f"Claude inference day {i}",
            provider="anthropic",
            model="claude-3-opus",
            input_tokens=2000,
            output_tokens=800,
            cache_read_tokens=500,
            cost=spike_cost,
            currency="USD",
            recorded_at=datetime(d.year, d.month, d.day, tzinfo=timezone.utc),
        )
        svc.store.save_usage_event(e2)

        # Google / Gemini — cheaper
        e3 = UsageEvent(
            client_id=client.id,
            client_name=client.name,
            description=f"Gemini inference day {i}",
            provider="google",
            model="gemini-pro",
            input_tokens=3000,
            output_tokens=1000,
            cost=0.01,
            currency="USD",
            request_count=5,
            recorded_at=datetime(d.year, d.month, d.day, tzinfo=timezone.utc),
        )
        svc.store.save_usage_event(e3)

    return svc


# ---------------------------------------------------------------------------
# Cost Trend Tests
# ---------------------------------------------------------------------------

class TestCostTrend:
    def test_daily_trend_with_data(self, populated_svc):
        today = date.today()
        trend = populated_svc.get_cost_trend(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert isinstance(trend, CostTrend)
        assert trend.granularity == "daily"
        assert len(trend.data_points) == 10
        assert trend.total_events == 30  # 3 events * 10 days
        assert trend.total_cost > 0
        assert trend.min_cost > 0
        assert trend.max_cost > 0
        assert trend.max_cost > trend.min_cost  # spike day should be max

    def test_weekly_trend(self, populated_svc):
        today = date.today()
        trend = populated_svc.get_cost_trend(
            date_from=today - timedelta(days=14),
            date_to=today,
            granularity="weekly",
        )
        assert trend.granularity == "weekly"
        assert len(trend.data_points) >= 1
        for dp in trend.data_points:
            assert "W" in dp["period"]  # ISO week format

    def test_monthly_trend(self, populated_svc):
        today = date.today()
        trend = populated_svc.get_cost_trend(
            date_from=today - timedelta(days=30),
            date_to=today,
            granularity="monthly",
        )
        assert trend.granularity == "monthly"
        assert len(trend.data_points) >= 1
        for dp in trend.data_points:
            assert "-" in dp["period"]  # YYYY-MM format

    def test_trend_no_data(self, svc):
        trend = svc.get_cost_trend(
            date_from=date(2025, 1, 1),
            date_to=date(2025, 1, 31),
        )
        assert isinstance(trend, CostTrend)
        assert len(trend.data_points) == 0
        assert trend.total_cost == 0.0

    def test_trend_direction_increasing(self, svc):
        """Verify trend direction detection for increasing costs."""
        client = svc.add_client("Test Inc")
        today = date.today()
        for i in range(5):
            d = today - timedelta(days=4 - i)
            # Cost increases significantly each day
            e = UsageEvent(
                client_id=client.id,
                client_name=client.name,
                description=f"day {i}",
                provider="openai",
                model="gpt-4",
                cost=0.01 * (i + 1) ** 3,  # 0.01, 0.08, 0.27, 0.64, 1.25
                currency="USD",
                recorded_at=datetime(d.year, d.month, d.day, tzinfo=timezone.utc),
            )
            svc.store.save_usage_event(e)

        trend = svc.get_cost_trend(
            date_from=today - timedelta(days=5),
            date_to=today,
        )
        assert trend.trend_direction == "increasing"
        assert trend.trend_percent > 10

    def test_trend_direction_stable(self, svc):
        """Verify trend direction detection for stable costs."""
        client = svc.add_client("Stable Inc")
        today = date.today()
        for i in range(5):
            d = today - timedelta(days=4 - i)
            e = UsageEvent(
                client_id=client.id,
                client_name=client.name,
                description=f"day {i}",
                provider="openai",
                model="gpt-4",
                cost=0.10,  # exactly the same each day
                currency="USD",
                recorded_at=datetime(d.year, d.month, d.day, tzinfo=timezone.utc),
            )
            svc.store.save_usage_event(e)

        trend = svc.get_cost_trend(
            date_from=today - timedelta(days=5),
            date_to=today,
        )
        assert trend.trend_direction == "stable"
        assert abs(trend.trend_percent) < 10

    def test_trend_with_client_filter(self, populated_svc):
        today = date.today()
        trend = populated_svc.get_cost_trend(
            client_identifier="Acme Corp",
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert len(trend.data_points) == 10
        assert trend.total_events == 30

    def test_trend_with_provider_filter(self, populated_svc):
        today = date.today()
        trend = populated_svc.get_cost_trend(
            provider="google",
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert len(trend.data_points) == 10
        assert trend.total_events == 10  # only google events

    def test_trend_data_point_fields(self, populated_svc):
        today = date.today()
        trend = populated_svc.get_cost_trend(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        dp = trend.data_points[0]
        assert "period" in dp
        assert "cost" in dp
        assert "events" in dp
        assert "tokens" in dp
        assert "input_tokens" in dp
        assert "output_tokens" in dp


# ---------------------------------------------------------------------------
# Cost Projection Tests
# ---------------------------------------------------------------------------

class TestCostProjection:
    def test_projection_with_data(self, populated_svc):
        projection = populated_svc.get_cost_projection(
            projection_days=7,
            lookback_days=10,
        )
        assert isinstance(projection, CostProjection)
        assert projection.projected_cost > 0
        assert len(projection.projected_breakdown) == 7
        assert projection.confidence in ("low", "medium", "high")
        assert len(projection.methodology) > 0

    def test_projection_no_data(self, svc):
        projection = svc.get_cost_projection(projection_days=7)
        assert isinstance(projection, CostProjection)
        assert projection.projected_cost == 0.0
        assert "No historical data" in projection.methodology

    def test_projection_confidence_levels(self, svc):
        client = svc.add_client("Confidence Test")
        today = date.today()

        # Add 20 days of data for high confidence
        for i in range(20):
            d = today - timedelta(days=19 - i)
            e = UsageEvent(
                client_id=client.id,
                client_name=client.name,
                description=f"day {i}",
                provider="openai",
                cost=0.05,
                currency="USD",
                recorded_at=datetime(d.year, d.month, d.day, tzinfo=timezone.utc),
            )
            svc.store.save_usage_event(e)

        proj = svc.get_cost_projection(projection_days=7, lookback_days=30)
        assert proj.confidence == "high"
        assert proj.historical_periods >= 14

    def test_projection_projection_days(self, populated_svc):
        for days in [1, 7, 14, 30, 90]:
            proj = populated_svc.get_cost_projection(
                projection_days=days,
                lookback_days=10,
            )
            assert len(proj.projected_breakdown) == days

    def test_projection_avg_daily_cost(self, populated_svc):
        proj = populated_svc.get_cost_projection(
            projection_days=7,
            lookback_days=10,
        )
        assert proj.avg_daily_cost > 0
        # projected = avg_daily * days
        expected = round(proj.avg_daily_cost * 7, 6)
        assert abs(proj.projected_cost - expected) < 0.001

    def test_projection_breakdown_format(self, populated_svc):
        proj = populated_svc.get_cost_projection(projection_days=3, lookback_days=10)
        for item in proj.projected_breakdown:
            assert "period" in item
            assert "projected_cost" in item
            assert item["is_projection"] is True


# ---------------------------------------------------------------------------
# Anomaly Detection Tests
# ---------------------------------------------------------------------------

class TestAnomalyDetection:
    def test_detect_spike(self, populated_svc):
        """The spike on day 5 should be detected."""
        today = date.today()
        report = populated_svc.detect_cost_anomalies(
            date_from=today - timedelta(days=10),
            date_to=today,
            threshold_percent=50.0,
        )
        assert isinstance(report, AnomalyReport)
        assert report.total_anomalies >= 1
        # The spike day should have higher severity
        spike = max(report.anomalies, key=lambda a: a.actual_cost)
        assert spike.actual_cost > spike.expected_cost
        assert spike.deviation_percent >= 50.0

    def test_no_anomalies_with_high_threshold(self, populated_svc):
        today = date.today()
        report = populated_svc.detect_cost_anomalies(
            date_from=today - timedelta(days=10),
            date_to=today,
            threshold_percent=10000.0,  # Very high threshold
        )
        assert report.total_anomalies == 0

    def test_no_data_no_anomalies(self, svc):
        report = svc.detect_cost_anomalies(
            date_from=date(2025, 1, 1),
            date_to=date(2025, 1, 31),
        )
        assert report.total_anomalies == 0
        assert report.baseline_avg_cost == 0.0

    def test_anomaly_severity_levels(self, svc):
        client = svc.add_client("Severity Test")
        today = date.today()

        # Create baseline and then a massive spike
        costs = [0.01, 0.01, 0.01, 0.01, 5.0]  # day 5 is 500x baseline
        for i, c in enumerate(costs):
            d = today - timedelta(days=4 - i)
            e = UsageEvent(
                client_id=client.id,
                client_name=client.name,
                description=f"day {i}",
                provider="openai",
                cost=c,
                currency="USD",
                recorded_at=datetime(d.year, d.month, d.day, tzinfo=timezone.utc),
            )
            svc.store.save_usage_event(e)

        report = svc.detect_cost_anomalies(
            date_from=today - timedelta(days=5),
            date_to=today,
            threshold_percent=50.0,
        )
        assert report.total_anomalies >= 1
        critical = [a for a in report.anomalies if a.severity == "critical"]
        assert len(critical) >= 1

    def test_anomaly_fields(self, populated_svc):
        today = date.today()
        report = populated_svc.detect_cost_anomalies(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        for anomaly in report.anomalies:
            assert isinstance(anomaly, CostAnomaly)
            assert anomaly.period  # non-empty
            assert anomaly.actual_cost >= anomaly.expected_cost  # it's a spike
            assert anomaly.deviation_percent >= 50.0
            assert anomaly.severity in ("info", "warning", "critical")
            assert anomaly.event_count > 0

    def test_anomaly_threshold_customizable(self, populated_svc):
        today = date.today()
        # Low threshold should catch more anomalies
        low_report = populated_svc.detect_cost_anomalies(
            date_from=today - timedelta(days=10),
            date_to=today,
            threshold_percent=10.0,
        )
        high_report = populated_svc.detect_cost_anomalies(
            date_from=today - timedelta(days=10),
            date_to=today,
            threshold_percent=200.0,
        )
        assert low_report.total_anomalies >= high_report.total_anomalies


# ---------------------------------------------------------------------------
# Model Efficiency Tests
# ---------------------------------------------------------------------------

class TestModelEfficiency:
    def test_efficiency_report(self, populated_svc):
        today = date.today()
        report = populated_svc.get_model_efficiency(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert isinstance(report, EfficiencyReport)
        assert len(report.models) == 3  # gpt-4, claude-3-opus, gemini-pro

    def test_model_metrics(self, populated_svc):
        today = date.today()
        report = populated_svc.get_model_efficiency(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        for m in report.models:
            assert isinstance(m, ModelEfficiency)
            assert m.total_cost > 0
            assert m.total_tokens > 0
            assert m.cost_per_1k_tokens >= 0
            assert m.cost_per_request >= 0
            assert m.avg_tokens_per_event > 0
            assert 0 <= m.output_ratio <= 1
            assert 0 <= m.cache_hit_ratio <= 1

    def test_cheapest_per_1k(self, populated_svc):
        today = date.today()
        report = populated_svc.get_model_efficiency(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert report.cheapest_per_1k_tokens is not None
        assert "provider" in report.cheapest_per_1k_tokens
        assert "model" in report.cheapest_per_1k_tokens
        assert "cost_per_1k" in report.cheapest_per_1k_tokens

    def test_cheapest_per_request(self, populated_svc):
        today = date.today()
        report = populated_svc.get_model_efficiency(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert report.cheapest_per_request is not None
        assert "provider" in report.cheapest_per_request

    def test_most_efficient_output(self, populated_svc):
        today = date.today()
        report = populated_svc.get_model_efficiency(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert report.most_efficient_output is not None
        assert report.most_efficient_output["output_ratio"] > 0

    def test_best_cache_utilization(self, populated_svc):
        today = date.today()
        report = populated_svc.get_model_efficiency(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert report.best_cache_utilization is not None
        # Claude has cache_read_tokens, so it should have best cache
        assert report.best_cache_utilization["cache_hit_ratio"] > 0

    def test_no_data_efficiency(self, svc):
        report = svc.get_model_efficiency()
        assert isinstance(report, EfficiencyReport)
        assert len(report.models) == 0
        assert report.cheapest_per_1k_tokens is None

    def test_gemini_cheapest(self, populated_svc):
        """Gemini should be cheapest per 1K tokens in our test data."""
        today = date.today()
        report = populated_svc.get_model_efficiency(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        cheapest = report.cheapest_per_1k_tokens
        assert cheapest["model"] == "gemini-pro"


# ---------------------------------------------------------------------------
# Provider Comparison Tests
# ---------------------------------------------------------------------------

class TestProviderComparison:
    def test_comparison_basic(self, populated_svc):
        today = date.today()
        comparison = populated_svc.compare_providers(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert isinstance(comparison, ProviderComparison)
        assert len(comparison.providers) == 3  # openai, anthropic, google
        assert comparison.total_cost > 0

    def test_provider_fields(self, populated_svc):
        today = date.today()
        comparison = populated_svc.compare_providers(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        for p in comparison.providers:
            assert "provider" in p
            assert "total_cost" in p
            assert "events" in p
            assert "tokens" in p
            assert "avg_cost_per_event" in p
            assert "share_percent" in p
            assert "model_count" in p
            assert "models" in p
            assert p["total_cost"] > 0
            assert p["events"] > 0

    def test_share_percent_sums_to_100(self, populated_svc):
        today = date.today()
        comparison = populated_svc.compare_providers(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        total_share = sum(p["share_percent"] for p in comparison.providers)
        assert abs(total_share - 100.0) < 1.0  # Allow rounding

    def test_providers_sorted_by_cost(self, populated_svc):
        today = date.today()
        comparison = populated_svc.compare_providers(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        costs = [p["total_cost"] for p in comparison.providers]
        assert costs == sorted(costs, reverse=True)

    def test_dominant_provider(self, populated_svc):
        today = date.today()
        comparison = populated_svc.compare_providers(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert comparison.dominant_provider is not None
        assert comparison.dominant_provider == comparison.providers[0]["provider"]

    def test_no_data_comparison(self, svc):
        comparison = svc.compare_providers()
        assert isinstance(comparison, ProviderComparison)
        assert len(comparison.providers) == 0
        assert comparison.total_cost == 0.0
        assert comparison.dominant_provider is None

    def test_comparison_with_client_filter(self, populated_svc):
        """Client filter should still work."""
        today = date.today()
        comparison = populated_svc.compare_providers(
            client_identifier="Acme Corp",
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert len(comparison.providers) == 3


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

class TestAnalyticsIntegration:
    def test_full_analytics_workflow(self, populated_svc):
        """Test the complete analytics workflow: record → trend → project → anomaly → efficiency → compare."""
        today = date.today()

        # 1. Get trend
        trend = populated_svc.get_cost_trend(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert trend.total_cost > 0

        # 2. Project forward
        proj = populated_svc.get_cost_projection(projection_days=14, lookback_days=10)
        assert proj.projected_cost > 0

        # 3. Detect anomalies
        anomalies = populated_svc.detect_cost_anomalies(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert anomalies.baseline_avg_cost > 0

        # 4. Model efficiency
        eff = populated_svc.get_model_efficiency(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert len(eff.models) == 3

        # 5. Compare providers
        comp = populated_svc.compare_providers(
            date_from=today - timedelta(days=10),
            date_to=today,
        )
        assert len(comp.providers) == 3

    def test_currency_filter_works(self, svc):
        """Currency filtering should work across all analytics."""
        client = svc.add_client("Multi-Currency Inc")
        today = date.today()

        for i in range(5):
            d = today - timedelta(days=4 - i)
            for currency, cost in [("USD", 0.05), ("EUR", 0.04)]:
                e = UsageEvent(
                    client_id=client.id,
                    client_name=client.name,
                    description=f"{currency} event {i}",
                    provider="openai",
                    cost=cost,
                    currency=currency,
                    recorded_at=datetime(d.year, d.month, d.day, tzinfo=timezone.utc),
                )
                svc.store.save_usage_event(e)

        # USD-only trend
        usd_trend = svc.get_cost_trend(
            date_from=today - timedelta(days=5),
            date_to=today,
            currency="USD",
        )
        assert usd_trend.total_events == 5  # Only USD events

        # EUR-only trend
        eur_trend = svc.get_cost_trend(
            date_from=today - timedelta(days=5),
            date_to=today,
            currency="EUR",
        )
        assert eur_trend.total_events == 5
