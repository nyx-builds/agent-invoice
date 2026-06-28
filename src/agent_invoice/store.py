"""JSON file-based storage for Agent Invoice."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .models import Client, Invoice, InvoiceStatus


DEFAULT_DATA_DIR = os.path.expanduser("~/.agent-invoice")


class InvoiceStore:
    """Manages persistence of invoices and clients as JSON files."""

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = Path(data_dir or os.environ.get("AGENT_INVOICE_DIR", DEFAULT_DATA_DIR))
        self.invoices_dir = self.data_dir / "invoices"
        self.clients_dir = self.data_dir / "clients"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.invoices_dir.mkdir(parents=True, exist_ok=True)
        self.clients_dir.mkdir(parents=True, exist_ok=True)

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

    # --- Invoice operations ---

    def save_invoice(self, invoice: Invoice) -> Invoice:
        # Check overdue status before saving
        invoice.check_overdue()
        path = self.invoices_dir / f"{invoice.id}.json"
        path.write_text(invoice.model_dump_json(indent=2))
        return invoice

    def get_invoice(self, invoice_id: str) -> Optional[Invoice]:
        path = self.invoices_dir / f"{invoice_id}.json"
        if not path.exists():
            return None
        return Invoice.model_validate_json(path.read_text())

    def list_invoices(
        self,
        status: Optional[InvoiceStatus] = None,
        client_id: Optional[str] = None,
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
            invoices.append(inv)
        return invoices

    def delete_invoice(self, invoice_id: str) -> bool:
        path = self.invoices_dir / f"{invoice_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def get_next_invoice_number(self) -> str:
        """Get the next sequential invoice number based on existing invoices."""
        existing = self.list_invoices()
        max_num = 0
        for inv in existing:
            try:
                num = int(inv.id.split("-")[1])
                max_num = max(max_num, num)
            except (IndexError, ValueError):
                continue
        return f"INV-{max_num + 1:04d}"
