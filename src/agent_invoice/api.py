"""REST API server for Agent Invoice — FastAPI-based HTTP API."""

from __future__ import annotations

from datetime import date as date_type
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel as APIBaseModel

from .models import CURRENCIES, InvoiceStatus, RecurrenceFrequency
from .service import InvoiceService
from .store import InvoiceStore


def _get_service() -> InvoiceService:
    return InvoiceService(InvoiceStore())


def _invoice_to_dict(inv) -> dict:
    """Serialize an Invoice to a summary dict."""
    return {
        "id": inv.id, "client": inv.client_name, "currency": inv.currency,
        "status": inv.status.value, "subtotal": inv.subtotal, "tax": inv.total_tax,
        "total": inv.total, "amount_paid": inv.amount_paid,
        "amount_remaining": inv.amount_remaining,
        "due_date": str(inv.due_date) if inv.due_date else None,
    }


# --- Request schemas ---


class ClientCreateRequest(APIBaseModel):
    name: str
    email: Optional[str] = None
    address: Optional[str] = None
    currency: str = "USD"


class ClientUpdateRequest(APIBaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    currency: Optional[str] = None


class LineItemInput(APIBaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float
    tax_rate: Optional[float] = None


class InvoiceCreateRequest(APIBaseModel):
    client: str
    items: list[LineItemInput]
    due_days: int = 30
    notes: Optional[str] = None
    currency: Optional[str] = None
    tax_rate: Optional[float] = None
    discount_amount: Optional[float] = None


class PaymentRequest(APIBaseModel):
    amount: float
    method: Optional[str] = None
    reference: Optional[str] = None
    notes: Optional[str] = None
    payment_date: Optional[str] = None  # YYYY-MM-DD


class DiscountRequest(APIBaseModel):
    amount: float


class LineItemAddRequest(APIBaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float
    tax_rate: Optional[float] = None


class RecurringCreateRequest(APIBaseModel):
    client: str
    items: list[LineItemInput]
    frequency: str = "monthly"
    due_days: int = 30
    notes: Optional[str] = None
    currency: Optional[str] = None
    tax_rate: Optional[float] = None
    discount_amount: Optional[float] = None


class TemplateCreateRequest(APIBaseModel):
    name: str
    items: list[LineItemInput]
    description: Optional[str] = None
    category: Optional[str] = None
    due_days: int = 30
    currency: str = "USD"
    tax_rate: Optional[float] = None
    discount_amount: Optional[float] = None
    notes: Optional[str] = None


class TemplateUseRequest(APIBaseModel):
    client: str
    due_days: Optional[int] = None
    discount_amount: Optional[float] = None
    notes: Optional[str] = None
    currency: Optional[str] = None


class DunningConfigRequest(APIBaseModel):
    first_reminder_days: Optional[int] = None
    second_reminder_days: Optional[int] = None
    final_notice_days: Optional[int] = None
    enabled: Optional[bool] = None


class DunningSendRequest(APIBaseModel):
    level: Optional[str] = None
    message: Optional[str] = None


class NumberingUpdateRequest(APIBaseModel):
    prefix: Optional[str] = None
    separator: Optional[str] = None
    digits: Optional[int] = None
    next_number: Optional[int] = None


class CreditNoteCreateRequest(APIBaseModel):
    client: str
    amount: float
    reason: Optional[str] = None
    invoice_id: Optional[str] = None
    currency: Optional[str] = None


class CreditNoteApplyRequest(APIBaseModel):
    invoice_id: str
    amount: Optional[float] = None


# --- App factory ---


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent Invoice API",
        description="REST API for autonomous agent billing — create invoices, manage clients, track payments, dunning, templates",
        version="0.5.0",
    )

    # --- Clients ---

    @app.post("/clients", status_code=201)
    def create_client(req: ClientCreateRequest):
        svc = _get_service()
        try:
            c = svc.add_client(name=req.name, email=req.email, address=req.address, currency=req.currency)
            return {"id": c.id, "name": c.name, "email": c.email, "currency": c.currency}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/clients")
    def list_clients():
        svc = _get_service()
        clients = svc.list_clients()
        return [{"id": c.id, "name": c.name, "email": c.email, "currency": c.currency} for c in clients]

    @app.get("/clients/{client_id}")
    def get_client(client_id: str):
        svc = _get_service()
        c = svc.get_client(client_id)
        if not c:
            raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found")
        return c.model_dump()

    @app.patch("/clients/{client_id}")
    def update_client(client_id: str, req: ClientUpdateRequest):
        svc = _get_service()
        try:
            c = svc.update_client(client_id, name=req.name, email=req.email, address=req.address, currency=req.currency)
            return c.model_dump()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/clients/{client_id}")
    def delete_client(client_id: str):
        svc = _get_service()
        if svc.remove_client(client_id):
            return {"deleted": True}
        raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found")

    # --- Invoices ---

    @app.post("/invoices", status_code=201)
    def create_invoice(req: InvoiceCreateRequest):
        svc = _get_service()
        try:
            items = [i.model_dump() for i in req.items]
            inv = svc.create_invoice(
                client_identifier=req.client,
                line_items=items,
                due_days=req.due_days,
                notes=req.notes,
                currency=req.currency,
                tax_rate=req.tax_rate,
                discount_amount=req.discount_amount,
            )
            return {
                "id": inv.id, "client": inv.client_name, "currency": inv.currency,
                "subtotal": inv.subtotal, "tax": inv.total_tax, "discount": inv.discount_amount,
                "total": inv.total, "due_date": str(inv.due_date) if inv.due_date else None,
                "status": inv.status.value,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/invoices")
    def list_invoices(
        status: Optional[str] = Query(None),
        client: Optional[str] = Query(None),
        currency: Optional[str] = Query(None),
        date_from: Optional[str] = Query(None),
        date_to: Optional[str] = Query(None),
        min_amount: Optional[float] = Query(None),
        max_amount: Optional[float] = Query(None),
        search: Optional[str] = Query(None),
    ):
        svc = _get_service()
        from datetime import date as date_type
        parsed_from = None
        parsed_to = None
        if date_from:
            try:
                parsed_from = date_type.fromisoformat(date_from)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid date_from format: {date_from}")
        if date_to:
            try:
                parsed_to = date_type.fromisoformat(date_to)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid date_to format: {date_to}")
        status_enum = InvoiceStatus(status) if status else None
        invoices = svc.list_invoices(
            status=status_enum, client=client, currency=currency,
            date_from=parsed_from, date_to=parsed_to,
            min_amount=min_amount, max_amount=max_amount,
            search=search,
        )
        return [_invoice_to_dict(inv) for inv in invoices]

    @app.get("/invoices/{invoice_id}")
    def get_invoice(invoice_id: str):
        svc = _get_service()
        inv = svc.get_invoice(invoice_id)
        if not inv:
            raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found")
        data = inv.model_dump(mode="json")
        data["amount_paid"] = inv.amount_paid
        data["amount_remaining"] = inv.amount_remaining
        return data

    @app.post("/invoices/{invoice_id}/send")
    def mark_sent(invoice_id: str):
        svc = _get_service()
        try:
            inv = svc.mark_sent(invoice_id)
            return {"id": inv.id, "status": "sent"}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/invoices/{invoice_id}/pay")
    def mark_paid(invoice_id: str):
        svc = _get_service()
        try:
            inv = svc.mark_paid(invoice_id)
            return {"id": inv.id, "status": "paid", "total": inv.total, "currency": inv.currency}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/invoices/{invoice_id}/cancel")
    def cancel_invoice(invoice_id: str):
        svc = _get_service()
        try:
            inv = svc.cancel_invoice(invoice_id)
            return {"id": inv.id, "status": "cancelled"}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/invoices/{invoice_id}/discount")
    def apply_discount(invoice_id: str, req: DiscountRequest):
        svc = _get_service()
        try:
            inv = svc.apply_discount(invoice_id, req.amount)
            return {"id": inv.id, "discount": inv.discount_amount, "total": inv.total}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/invoices/{invoice_id}/items", status_code=201)
    def add_line_item(invoice_id: str, req: LineItemAddRequest):
        svc = _get_service()
        try:
            item_data = req.model_dump()
            if req.tax_rate is None:
                del item_data["tax_rate"]
            inv = svc.add_line_item(invoice_id, item_data)
            return {"id": inv.id, "items": len(inv.line_items), "total": inv.total}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/invoices/{invoice_id}/items/{index}")
    def remove_line_item(invoice_id: str, index: int):
        svc = _get_service()
        try:
            inv = svc.remove_line_item(invoice_id, index)
            return {"id": inv.id, "items": len(inv.line_items), "total": inv.total}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/invoices/{invoice_id}")
    def delete_invoice(invoice_id: str):
        svc = _get_service()
        if svc.remove_invoice(invoice_id):
            return {"deleted": True}
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found")

    # --- Payments ---

    @app.post("/invoices/{invoice_id}/payments", status_code=201)
    def record_payment(invoice_id: str, req: PaymentRequest):
        svc = _get_service()
        try:
            payment_date = None
            if req.payment_date:
                try:
                    payment_date = date_type.fromisoformat(req.payment_date)
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid date format: {req.payment_date}. Use YYYY-MM-DD.")
            inv = svc.record_payment(
                invoice_id=invoice_id,
                amount=req.amount,
                method=req.method,
                reference=req.reference,
                notes=req.notes,
                payment_date=payment_date,
            )
            return {
                "id": inv.id, "status": inv.status.value, "amount_paid": inv.amount_paid,
                "amount_remaining": inv.amount_remaining, "total": inv.total, "currency": inv.currency,
                "payment_count": len(inv.payments),
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/invoices/{invoice_id}/payments")
    def list_payments(invoice_id: str):
        svc = _get_service()
        try:
            payments = svc.list_payments(invoice_id)
            return [{"id": p.id, "amount": p.amount, "method": p.method, "reference": p.reference, "notes": p.notes, "date": str(p.payment_date)} for p in payments]
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.delete("/invoices/{invoice_id}/payments/{payment_id}")
    def remove_payment(invoice_id: str, payment_id: str):
        svc = _get_service()
        try:
            inv = svc.remove_payment(invoice_id, payment_id)
            return {"id": inv.id, "status": inv.status.value, "amount_paid": inv.amount_paid, "amount_remaining": inv.amount_remaining}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # --- Export ---

    @app.get("/invoices/{invoice_id}/export")
    def export_invoice(
        invoice_id: str,
        format: str = Query("markdown", enum=["markdown", "json", "pdf"]),
        company_name: Optional[str] = Query(None),
        company_address: Optional[str] = Query(None),
        company_email: Optional[str] = Query(None),
    ):
        svc = _get_service()
        inv = svc.get_invoice(invoice_id)
        if not inv:
            raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found")
        if format == "markdown":
            return JSONResponse(content={"format": "markdown", "content": inv.to_markdown()})
        elif format == "json":
            return JSONResponse(content={"format": "json", "content": inv.model_dump(mode="json")})
        elif format == "pdf":
            try:
                pdf_path = svc.export_pdf(
                    invoice_id=invoice_id,
                    company_name=company_name,
                    company_address=company_address,
                    company_email=company_email,
                )
                return {"format": "pdf", "path": pdf_path}
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

    # --- Earnings ---

    @app.get("/earnings")
    def earnings_summary(currency: Optional[str] = Query(None)):
        svc = _get_service()
        summary = svc.earnings_summary(currency=currency)
        return summary.model_dump()

    # --- Recurring ---

    @app.post("/recurring", status_code=201)
    def create_recurring(req: RecurringCreateRequest):
        svc = _get_service()
        try:
            items = [i.model_dump() for i in req.items]
            rec = svc.create_recurring(
                client_identifier=req.client,
                line_items=items,
                frequency=req.frequency,
                due_days=req.due_days,
                notes=req.notes,
                currency=req.currency,
                tax_rate=req.tax_rate,
                discount_amount=req.discount_amount,
            )
            return {
                "id": rec.id, "client": rec.client_name, "frequency": rec.frequency.value,
                "currency": rec.currency, "total": rec.total,
                "next_date": str(rec.next_date) if rec.next_date else None, "active": rec.active,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/recurring")
    def list_recurring(active_only: bool = Query(False)):
        svc = _get_service()
        recs = svc.list_recurring(active_only=active_only)
        result = []
        for rec in recs:
            result.append({
                "id": rec.id, "client": rec.client_name, "frequency": rec.frequency.value,
                "currency": rec.currency, "total": rec.total, "active": rec.active,
                "next_date": str(rec.next_date) if rec.next_date else None, "generated_count": len(rec.invoice_ids),
            })
        return result

    @app.post("/recurring/{recurring_id}/generate")
    def generate_from_recurring(recurring_id: str):
        svc = _get_service()
        try:
            inv = svc.generate_from_recurring(recurring_id)
            return {"id": inv.id, "client": inv.client_name, "currency": inv.currency, "total": inv.total, "status": inv.status.value}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/recurring/{recurring_id}/pause")
    def pause_recurring(recurring_id: str):
        svc = _get_service()
        try:
            rec = svc.pause_recurring(recurring_id)
            return {"id": rec.id, "active": False}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/recurring/{recurring_id}/resume")
    def resume_recurring(recurring_id: str):
        svc = _get_service()
        try:
            rec = svc.resume_recurring(recurring_id)
            return {"id": rec.id, "active": True, "next_date": str(rec.next_date)}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/recurring/{recurring_id}")
    def delete_recurring(recurring_id: str):
        svc = _get_service()
        if svc.remove_recurring(recurring_id):
            return {"deleted": True}
        raise HTTPException(status_code=404, detail=f"Recurring invoice '{recurring_id}' not found")

    @app.post("/recurring/process-due")
    def process_due_recurring():
        svc = _get_service()
        generated = svc.process_due_recurring()
        return {"generated_count": len(generated), "invoices": [{"id": inv.id, "client": inv.client_name, "total": inv.total} for inv in generated]}

    # --- Templates ---

    @app.get("/templates")
    def list_templates(category: Optional[str] = Query(None)):
        svc = _get_service()
        templates = svc.list_templates(category=category)
        result = []
        for tpl in templates:
            result.append({
                "id": tpl.id, "name": tpl.name, "description": tpl.description,
                "category": tpl.category, "currency": tpl.currency, "total": tpl.total,
                "due_days": tpl.due_days, "items": len(tpl.line_items),
            })
        return result

    @app.get("/templates/{template_id}")
    def get_template(template_id: str):
        svc = _get_service()
        tpl = svc.get_template(template_id)
        if not tpl:
            raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
        data = tpl.model_dump(mode="json")
        data["subtotal"] = tpl.subtotal
        data["total_tax"] = tpl.total_tax
        data["total"] = tpl.total
        return data

    @app.post("/templates", status_code=201)
    def create_template(req: TemplateCreateRequest):
        svc = _get_service()
        try:
            items = [i.model_dump() for i in req.items]
            tpl = svc.create_template(
                name=req.name, line_items=items, description=req.description,
                category=req.category, due_days=req.due_days, currency=req.currency,
                tax_rate=req.tax_rate, discount_amount=req.discount_amount, notes=req.notes,
            )
            return {"id": tpl.id, "name": tpl.name, "total": tpl.total}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/templates/{template_id}/use", status_code=201)
    def use_template(template_id: str, req: TemplateUseRequest):
        svc = _get_service()
        try:
            overrides = {}
            if req.due_days is not None:
                overrides["due_days"] = req.due_days
            if req.discount_amount is not None:
                overrides["discount_amount"] = req.discount_amount
            if req.notes is not None:
                overrides["notes"] = req.notes
            if req.currency is not None:
                overrides["currency"] = req.currency
            inv = svc.create_invoice_from_template(template_id, req.client, overrides=overrides)
            return {
                "id": inv.id, "client": inv.client_name, "currency": inv.currency,
                "total": inv.total, "status": inv.status.value,
                "due_date": str(inv.due_date) if inv.due_date else None,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/templates/{template_id}")
    def delete_template(template_id: str):
        svc = _get_service()
        try:
            if svc.remove_template(template_id):
                return {"deleted": True}
            raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # --- Dunning ---

    @app.get("/dunning/config")
    def get_dunning_config():
        svc = _get_service()
        config = svc.get_dunning_config()
        return config.model_dump()

    @app.patch("/dunning/config")
    def update_dunning_config(req: DunningConfigRequest):
        svc = _get_service()
        try:
            config = svc.update_dunning_config(
                first_reminder_days=req.first_reminder_days,
                second_reminder_days=req.second_reminder_days,
                final_notice_days=req.final_notice_days,
                enabled=req.enabled,
            )
            return config.model_dump()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/dunning/send/{invoice_id}", status_code=201)
    def send_dunning_reminder(invoice_id: str, req: DunningSendRequest):
        svc = _get_service()
        try:
            action = svc.send_dunning_reminder(invoice_id, level=req.level, message=req.message)
            return action.model_dump(mode="json")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/dunning/process")
    def process_dunning():
        svc = _get_service()
        actions = svc.process_overdue_dunning()
        return {"processed_count": len(actions), "actions": [a.model_dump(mode="json") for a in actions]}

    @app.get("/dunning/actions")
    def list_dunning_actions(invoice: Optional[str] = Query(None)):
        svc = _get_service()
        actions = svc.list_dunning_actions(invoice_id=invoice)
        return [a.model_dump(mode="json") for a in actions]

    @app.delete("/dunning/actions/{action_id}")
    def delete_dunning_action(action_id: str):
        svc = _get_service()
        if svc.remove_dunning_action(action_id):
            return {"deleted": True}
        raise HTTPException(status_code=404, detail=f"Dunning action '{action_id}' not found")

    # --- Numbering ---

    @app.get("/numbering")
    def get_numbering_config():
        svc = _get_service()
        config = svc.get_numbering_config()
        return {
            "prefix": config.prefix, "separator": config.separator,
            "digits": config.digits, "next_number": config.next_number,
            "next_formatted": config.format_number(),
        }

    @app.patch("/numbering")
    def update_numbering_config(req: NumberingUpdateRequest):
        svc = _get_service()
        config = svc.update_numbering_config(
            prefix=req.prefix, separator=req.separator,
            digits=req.digits, next_number=req.next_number,
        )
        return {
            "prefix": config.prefix, "separator": config.separator,
            "digits": config.digits, "next_number": config.next_number,
            "next_formatted": config.format_number(),
        }

    # --- Currencies ---

    @app.get("/currencies")
    def list_currencies():
        result = []
        for code, info in sorted(CURRENCIES.items()):
            result.append({"code": code, "symbol": info["symbol"], "name": info["name"], "decimals": info["decimals"]})
        return result

    # --- Credit notes ---

    @app.post("/credit-notes", status_code=201)
    def create_credit_note(req: CreditNoteCreateRequest):
        svc = _get_service()
        try:
            credit = svc.create_credit_note(
                client_identifier=req.client,
                amount=req.amount,
                reason=req.reason,
                invoice_id=req.invoice_id,
                currency=req.currency,
            )
            return {
                "id": credit.id, "client": credit.client_name,
                "amount": credit.amount, "currency": credit.currency,
                "reason": credit.reason, "status": credit.status.value,
                "remaining": credit.remaining_amount,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/credit-notes")
    def list_credit_notes(
        client: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
    ):
        svc = _get_service()
        try:
            credits = svc.list_credit_notes(client=client, status=status)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        result = []
        for credit in credits:
            result.append({
                "id": credit.id, "client": credit.client_name,
                "amount": credit.amount, "currency": credit.currency,
                "applied_amount": credit.applied_amount,
                "remaining_amount": credit.remaining_amount,
                "status": credit.status.value, "reason": credit.reason,
                "issue_date": str(credit.issue_date),
            })
        return result

    @app.get("/credit-notes/{credit_id}")
    def get_credit_note(credit_id: str):
        svc = _get_service()
        credit = svc.get_credit_note(credit_id)
        if not credit:
            raise HTTPException(status_code=404, detail=f"Credit note '{credit_id}' not found")
        data = credit.model_dump(mode="json")
        data["applied_amount"] = credit.applied_amount
        data["remaining_amount"] = credit.remaining_amount
        return data

    @app.post("/credit-notes/{credit_id}/apply")
    def apply_credit_note(credit_id: str, req: CreditNoteApplyRequest):
        svc = _get_service()
        try:
            credit, invoice = svc.apply_credit_note(
                credit_id=credit_id,
                invoice_id=req.invoice_id,
                amount=req.amount,
            )
            return {
                "credit_note": {
                    "id": credit.id, "applied_amount": credit.applied_amount,
                    "remaining_amount": credit.remaining_amount, "status": credit.status.value,
                },
                "invoice": {
                    "id": invoice.id, "status": invoice.status.value,
                    "amount_paid": invoice.amount_paid, "amount_remaining": invoice.amount_remaining,
                },
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/credit-notes/{credit_id}/void")
    def void_credit_note(credit_id: str):
        svc = _get_service()
        try:
            credit = svc.void_credit_note(credit_id)
            return {"id": credit.id, "status": credit.status.value}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/credit-notes/{credit_id}")
    def delete_credit_note(credit_id: str):
        svc = _get_service()
        try:
            if svc.remove_credit_note(credit_id):
                return {"deleted": True}
            raise HTTPException(status_code=404, detail=f"Credit note '{credit_id}' not found")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # --- Client statements ---

    @app.get("/clients/{client}/statement")
    def client_statement(
        client: str,
        period_start: str = Query(..., description="YYYY-MM-DD"),
        period_end: str = Query(..., description="YYYY-MM-DD"),
        currency: Optional[str] = Query(None),
    ):
        from datetime import date as date_type
        svc = _get_service()
        try:
            start = date_type.fromisoformat(period_start)
            end = date_type.fromisoformat(period_end)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
        try:
            stmt = svc.generate_client_statement(
                client_identifier=client,
                period_start=start,
                period_end=end,
                currency=currency,
            )
            return stmt.model_dump(mode="json")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return app
