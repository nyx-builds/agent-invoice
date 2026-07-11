"""JSON file-based storage for Agent Invoice."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

from .models import Client, CreditNote, CreditNoteStatus, DunningAction, DunningConfig, Estimate, Expense, ExpenseCategory, Invoice, InvoiceStatus, InvoiceTemplate, NumberingConfig, RecurringInvoice, UsageEvent


DEFAULT_DATA_DIR = os.path.expanduser("~/.agent-invoice")


class InvoiceStore:
    """Manages persistence of invoices, clients, and config as JSON files."""

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = Path(data_dir or os.environ.get("AGENT_INVOICE_DIR", DEFAULT_DATA_DIR))
        self.invoices_dir = self.data_dir / "invoices"
        self.clients_dir = self.data_dir / "clients"
        self.recurring_dir = self.data_dir / "recurring"
        self.templates_dir = self.data_dir / "templates"
        self.dunning_dir = self.data_dir / "dunning"
        self.credit_notes_dir = self.data_dir / "credit_notes"
        self.estimates_dir = self.data_dir / "estimates"
        self.expenses_dir = self.data_dir / "expenses"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.invoices_dir.mkdir(parents=True, exist_ok=True)
        self.clients_dir.mkdir(parents=True, exist_ok=True)
        self.recurring_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.dunning_dir.mkdir(parents=True, exist_ok=True)
        self.credit_notes_dir.mkdir(parents=True, exist_ok=True)
        self.estimates_dir.mkdir(parents=True, exist_ok=True)
        self.expenses_dir.mkdir(parents=True, exist_ok=True)

    # --- Numbering config ---

    def get_numbering_config(self) -> NumberingConfig:
        """Load or create the numbering configuration."""
        path = self.data_dir / "numbering.json"
        if path.exists():
            return NumberingConfig.model_validate_json(path.read_text())
        config = NumberingConfig()
        path.write_text(config.model_dump_json(indent=2))
        return config

    def save_numbering_config(self, config: NumberingConfig) -> NumberingConfig:
        """Save the numbering configuration."""
        path = self.data_dir / "numbering.json"
        path.write_text(config.model_dump_json(indent=2))
        return config

    def get_next_invoice_number(self) -> str:
        """Get the next invoice number using the configured numbering template."""
        config = self.get_numbering_config()
        number = config.advance()
        self.save_numbering_config(config)
        return number

    # --- Client operations ---

    def save_client(self, client: Client) -> Client:
        path = self.clients_dir / f"{client.id}.json"
        path.write_text(client.model_dump_json(indent=2))
        return client

    def get_client(self, client_id: str) -> Optional[Client]:
        path = self.clients_dir / f"{client_id}.json"
        if not path.exists():
            return None
        return Client.model_validate_json(path.read_text())

    def find_client_by_name(self, name: str) -> Optional[Client]:
        name_lower = name.lower()
        for path in self.clients_dir.glob("*.json"):
            client = Client.model_validate_json(path.read_text())
            if client.name.lower() == name_lower:
                return client
        return None

    def list_clients(self) -> list[Client]:
        clients = []
        for path in sorted(self.clients_dir.glob("*.json")):
            clients.append(Client.model_validate_json(path.read_text()))
        return clients

    def delete_client(self, client_id: str) -> bool:
        path = self.clients_dir / f"{client_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def update_client(self, client: Client) -> Client:
        """Save updated client data."""
        path = self.clients_dir / f"{client.id}.json"
        path.write_text(client.model_dump_json(indent=2))
        return client

    # --- Invoice operations ---

    @staticmethod
    def _safe_filename(invoice_id: str) -> str:
        """Convert an invoice ID to a safe filename by replacing path separators."""
        return invoice_id.replace("/", "_").replace("\\", "_")

    def save_invoice(self, invoice: Invoice) -> Invoice:
        # Check overdue status before saving
        invoice.check_overdue()
        path = self.invoices_dir / f"{self._safe_filename(invoice.id)}.json"
        path.write_text(invoice.model_dump_json(indent=2))
        return invoice

    def get_invoice(self, invoice_id: str) -> Optional[Invoice]:
        path = self.invoices_dir / f"{self._safe_filename(invoice_id)}.json"
        if not path.exists():
            return None
        return Invoice.model_validate_json(path.read_text())

    def list_invoices(
        self,
        status: Optional[InvoiceStatus] = None,
        client_id: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> list[Invoice]:
        invoices = []
        for path in sorted(self.invoices_dir.glob("*.json")):
            inv = Invoice.model_validate_json(path.read_text())
            # Auto-check overdue
            inv.check_overdue()
            if status and inv.status != status:
                continue
            if client_id and inv.client_id != client_id:
                continue
            if currency and inv.currency != currency.upper():
                continue
            invoices.append(inv)
        return invoices

    def delete_invoice(self, invoice_id: str) -> bool:
        path = self.invoices_dir / f"{self._safe_filename(invoice_id)}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # --- Recurring invoice operations ---

    def save_recurring(self, recurring: RecurringInvoice) -> RecurringInvoice:
        path = self.recurring_dir / f"{recurring.id}.json"
        path.write_text(recurring.model_dump_json(indent=2))
        return recurring

    def get_recurring(self, recurring_id: str) -> Optional[RecurringInvoice]:
        path = self.recurring_dir / f"{recurring_id}.json"
        if not path.exists():
            return None
        return RecurringInvoice.model_validate_json(path.read_text())

    def list_recurring(self, active_only: bool = False) -> list[RecurringInvoice]:
        recurrings = []
        for path in sorted(self.recurring_dir.glob("*.json")):
            rec = RecurringInvoice.model_validate_json(path.read_text())
            if active_only and not rec.active:
                continue
            recurrings.append(rec)
        return recurrings

    def delete_recurring(self, recurring_id: str) -> bool:
        path = self.recurring_dir / f"{recurring_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # --- Template operations ---

    def save_template(self, template: InvoiceTemplate) -> InvoiceTemplate:
        path = self.templates_dir / f"{template.id}.json"
        path.write_text(template.model_dump_json(indent=2))
        return template

    def get_template(self, template_id: str) -> Optional[InvoiceTemplate]:
        path = self.templates_dir / f"{template_id}.json"
        if not path.exists():
            return None
        return InvoiceTemplate.model_validate_json(path.read_text())

    def list_templates(self, category: Optional[str] = None) -> list[InvoiceTemplate]:
        templates = []
        for path in sorted(self.templates_dir.glob("*.json")):
            tpl = InvoiceTemplate.model_validate_json(path.read_text())
            if category and tpl.category != category:
                continue
            templates.append(tpl)
        return templates

    def delete_template(self, template_id: str) -> bool:
        path = self.templates_dir / f"{template_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # --- Dunning operations ---

    def get_dunning_config(self) -> DunningConfig:
        """Load or create the dunning configuration."""
        path = self.data_dir / "dunning_config.json"
        if path.exists():
            return DunningConfig.model_validate_json(path.read_text())
        config = DunningConfig()
        path.write_text(config.model_dump_json(indent=2))
        return config

    def save_dunning_config(self, config: DunningConfig) -> DunningConfig:
        """Save the dunning configuration."""
        path = self.data_dir / "dunning_config.json"
        path.write_text(config.model_dump_json(indent=2))
        return config

    def save_dunning_action(self, action: DunningAction) -> DunningAction:
        path = self.dunning_dir / f"{action.id}.json"
        path.write_text(action.model_dump_json(indent=2))
        return action

    def get_dunning_action(self, action_id: str) -> Optional[DunningAction]:
        path = self.dunning_dir / f"{action_id}.json"
        if not path.exists():
            return None
        return DunningAction.model_validate_json(path.read_text())

    def list_dunning_actions(
        self,
        invoice_id: Optional[str] = None,
    ) -> list[DunningAction]:
        actions = []
        for path in sorted(self.dunning_dir.glob("*.json")):
            action = DunningAction.model_validate_json(path.read_text())
            if invoice_id and action.invoice_id != invoice_id:
                continue
            actions.append(action)
        return actions

    def delete_dunning_action(self, action_id: str) -> bool:
        path = self.dunning_dir / f"{action_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # --- Credit note operations ---

    def save_credit_note(self, credit: CreditNote) -> CreditNote:
        path = self.credit_notes_dir / f"{credit.id}.json"
        path.write_text(credit.model_dump_json(indent=2))
        return credit

    def get_credit_note(self, credit_id: str) -> Optional[CreditNote]:
        path = self.credit_notes_dir / f"{credit_id}.json"
        if not path.exists():
            return None
        return CreditNote.model_validate_json(path.read_text())

    def list_credit_notes(
        self,
        client_id: Optional[str] = None,
        status: Optional[CreditNoteStatus] = None,
    ) -> list[CreditNote]:
        credits = []
        for path in sorted(self.credit_notes_dir.glob("*.json")):
            credit = CreditNote.model_validate_json(path.read_text())
            if client_id and credit.client_id != client_id:
                continue
            if status and credit.status != status:
                continue
            credits.append(credit)
        return credits

    def delete_credit_note(self, credit_id: str) -> bool:
        path = self.credit_notes_dir / f"{credit_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # --- Estimate operations ---

    def save_estimate(self, estimate: Estimate) -> Estimate:
        path = self.estimates_dir / f"{estimate.id}.json"
        path.write_text(estimate.model_dump_json(indent=2))
        return estimate

    def get_estimate(self, estimate_id: str) -> Optional[Estimate]:
        path = self.estimates_dir / f"{estimate_id}.json"
        if not path.exists():
            return None
        est = Estimate.model_validate_json(path.read_text())
        est.check_expired()
        return est

    def list_estimates(
        self,
        status: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> list[Estimate]:
        estimates = []
        for path in sorted(self.estimates_dir.glob("*.json")):
            est = Estimate.model_validate_json(path.read_text())
            est.check_expired()
            if status and est.status.value != status:
                continue
            if client_id and est.client_id != client_id:
                continue
            estimates.append(est)
        return estimates

    def delete_estimate(self, estimate_id: str) -> bool:
        path = self.estimates_dir / f"{estimate_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # --- Expense operations ---

    def save_expense(self, expense: Expense) -> Expense:
        path = self.expenses_dir / f"{expense.id}.json"
        path.write_text(expense.model_dump_json(indent=2))
        return expense

    def get_expense(self, expense_id: str) -> Optional[Expense]:
        path = self.expenses_dir / f"{expense_id}.json"
        if not path.exists():
            return None
        return Expense.model_validate_json(path.read_text())

    def list_expenses(
        self,
        category: Optional[ExpenseCategory | str] = None,
        currency: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        vendor: Optional[str] = None,
    ) -> list[Expense]:
        """List expenses with optional filters."""
        expenses = []
        for path in sorted(self.expenses_dir.glob("*.json")):
            exp = Expense.model_validate_json(path.read_text())
            # Category filter
            if category is not None:
                cat_str = category.value if isinstance(category, ExpenseCategory) else str(category)
                if exp.category.value != cat_str:
                    continue
            # Currency filter
            if currency and exp.currency != currency.upper():
                continue
            # Date range filters
            if date_from and exp.expense_date < date_from:
                continue
            if date_to and exp.expense_date > date_to:
                continue
            # Vendor filter (case-insensitive substring)
            if vendor and (not exp.vendor or vendor.lower() not in exp.vendor.lower()):
                continue
            expenses.append(exp)
        return expenses

    def delete_expense(self, expense_id: str) -> bool:
        path = self.expenses_dir / f"{expense_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # --- Usage event operations (v0.8.0) ---

    def _ensure_usage_dir(self) -> None:
        self.usage_dir.mkdir(parents=True, exist_ok=True)

    @property
    def usage_dir(self) -> Path:
        return self.data_dir / "usage_events"

    def save_usage_event(self, event: UsageEvent) -> UsageEvent:
        self.usage_dir.mkdir(parents=True, exist_ok=True)
        path = self.usage_dir / f"{event.id}.json"
        path.write_text(event.model_dump_json(indent=2))
        return event

    def get_usage_event(self, event_id: str) -> Optional[UsageEvent]:
        path = self.usage_dir / f"{event_id}.json"
        if not path.exists():
            return None
        return UsageEvent.model_validate_json(path.read_text())

    def list_usage_events(
        self,
        client_id: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        billed: Optional[bool] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> list[UsageEvent]:
        events = []
        for path in sorted(self.usage_dir.glob("*.json")):
            event = UsageEvent.model_validate_json(path.read_text())
            if client_id and event.client_id != client_id:
                continue
            if provider and event.provider != provider:
                continue
            if model and event.model != model:
                continue
            if billed is not None and event.billed != billed:
                continue
            event_date = event.recorded_at.date()
            if date_from and event_date < date_from:
                continue
            if date_to and event_date > date_to:
                continue
            events.append(event)
        return events

    def delete_usage_event(self, event_id: str) -> bool:
        path = self.usage_dir / f"{event_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False
