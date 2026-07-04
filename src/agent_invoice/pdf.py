"""PDF export for Agent Invoice — generates professional invoice PDFs."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
)
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

from .models import CURRENCIES, Estimate, Invoice, format_amount, get_currency_symbol


# Color palette
PRIMARY = colors.HexColor("#1a365d")      # Dark navy
ACCENT = colors.HexColor("#2b6cb0")       # Medium blue
LIGHT_BG = colors.HexColor("#ebf4ff")     # Light blue background
TEXT_DARK = colors.HexColor("#1a202c")     # Near black
TEXT_MED = colors.HexColor("#4a5568")      # Medium gray
TEXT_LIGHT = colors.HexColor("#718096")    # Light gray
GREEN = colors.HexColor("#276749")        # Success green
RED = colors.HexColor("#c53030")          # Alert red
BORDER = colors.HexColor("#cbd5e0")       # Border gray
TABLE_HEADER_BG = colors.HexColor("#1a365d")
TABLE_ALT_ROW = colors.HexColor("#f7fafc")


def _get_styles() -> dict[str, ParagraphStyle]:
    """Create paragraph styles for the invoice PDF."""
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "InvoiceTitle",
            parent=styles["Title"],
            fontSize=22,
            leading=28,
            textColor=PRIMARY,
            spaceAfter=4,
            fontName="Helvetica-Bold",
        ),
        "subtitle": ParagraphStyle(
            "InvoiceSubtitle",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=TEXT_MED,
            spaceAfter=12,
        ),
        "heading": ParagraphStyle(
            "SectionHeading",
            parent=styles["Heading2"],
            fontSize=12,
            leading=16,
            textColor=PRIMARY,
            spaceAfter=6,
            fontName="Helvetica-Bold",
        ),
        "label": ParagraphStyle(
            "Label",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=TEXT_LIGHT,
            fontName="Helvetica",
        ),
        "value": ParagraphStyle(
            "Value",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=TEXT_DARK,
            fontName="Helvetica-Bold",
        ),
        "normal": ParagraphStyle(
            "Normal",
            parent=styles["Normal"],
            fontSize=9,
            leading=13,
            textColor=TEXT_DARK,
            fontName="Helvetica",
        ),
        "small": ParagraphStyle(
            "Small",
            parent=styles["Normal"],
            fontSize=8,
            leading=11,
            textColor=TEXT_LIGHT,
            fontName="Helvetica",
        ),
        "total": ParagraphStyle(
            "Total",
            parent=styles["Normal"],
            fontSize=13,
            leading=18,
            textColor=PRIMARY,
            fontName="Helvetica-Bold",
        ),
        "footer": ParagraphStyle(
            "Footer",
            parent=styles["Normal"],
            fontSize=8,
            leading=11,
            textColor=TEXT_LIGHT,
            fontName="Helvetica",
            alignment=TA_CENTER,
        ),
        "status_draft": ParagraphStyle(
            "StatusDraft",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=TEXT_MED,
            fontName="Helvetica-Bold",
        ),
        "status_paid": ParagraphStyle(
            "StatusPaid",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=GREEN,
            fontName="Helvetica-Bold",
        ),
        "status_overdue": ParagraphStyle(
            "StatusOverdue",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=RED,
            fontName="Helvetica-Bold",
        ),
    }


def _status_style_name(status: str) -> str:
    """Get the style name for a given invoice status."""
    mapping = {
        "paid": "status_paid",
        "overdue": "status_overdue",
        "partially_paid": "status_paid",
    }
    return mapping.get(status, "status_draft")


def generate_pdf(
    invoice: Invoice,
    output_path: Optional[str] = None,
    company_name: Optional[str] = None,
    company_address: Optional[str] = None,
    company_email: Optional[str] = None,
) -> str:
    """Generate a professional PDF invoice.

    Args:
        invoice: The Invoice object to render.
        output_path: Path to save the PDF. If None, saves to ~/.agent-invoice/exports/.
        company_name: Your company name for the header.
        company_address: Your company address.
        company_email: Your company email.

    Returns:
        The path to the generated PDF file.
    """
    # Determine output path
    if output_path is None:
        export_dir = Path.home() / ".agent-invoice" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        safe_id = invoice.id.replace("/", "_").replace("\\", "_")
        output_path = str(export_dir / f"{safe_id}.pdf")

    # Ensure parent dir exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=25 * mm,
        rightMargin=25 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = _get_styles()
    story = []
    sym = get_currency_symbol(invoice.currency)
    curr_info = CURRENCIES.get(invoice.currency, {})
    decimals = curr_info.get("decimals", 2)

    # === HEADER ===
    # Company name (left) + Invoice label (right)
    header_data = [
        [
            Paragraph(company_name or "INVOICE", styles["title"]),
            Paragraph("INVOICE", ParagraphStyle(
                "RightTitle", parent=styles["title"], alignment=TA_RIGHT, fontSize=16
            )),
        ],
    ]
    header_table = Table(header_data, colWidths=[3.5 * inch, 2.5 * inch])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=2, color=PRIMARY, spaceAfter=12))

    # === INVOICE DETAILS ROW ===
    # Left: From / To info  |  Right: Invoice meta
    from_lines = []
    if company_name:
        from_lines.append(f"<b>{company_name}</b>")
    if company_address:
        from_lines.append(company_address)
    if company_email:
        from_lines.append(company_email)
    from_text = "<br/>".join(from_lines) if from_lines else "<b>From:</b> <i>Not specified</i>"

    to_lines = [f"<b>{invoice.client_name or invoice.client_id}</b>"]
    # We don't have client address in invoice model directly, but we can add notes

    inv_meta_lines = [
        f"<b>Invoice #:</b>  {invoice.id}",
        f"<b>Date:</b>  {invoice.issue_date}",
        f"<b>Due Date:</b>  {invoice.due_date or 'N/A'}",
        f"<b>Currency:</b>  {invoice.currency}",
        f"<b>Status:</b>  {invoice.status.value.replace('_', ' ').upper()}",
    ]

    details_data = [
        [
            Paragraph(f"<b>From:</b><br/>{from_text}", styles["normal"]),
            Paragraph(f"<b>Bill To:</b><br/>{'<br/>'.join(to_lines)}", styles["normal"]),
            Paragraph("<br/>".join(inv_meta_lines), styles["normal"]),
        ],
    ]
    details_table = Table(details_data, colWidths=[2 * inch, 2 * inch, 2 * inch])
    details_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(details_table)
    story.append(Spacer(1, 16))

    # === LINE ITEMS TABLE ===
    story.append(Paragraph("Items", styles["heading"]))

    item_header = ["Description", "Qty", "Unit Price", "Tax %", "Tax", "Total"]
    item_rows = [item_header]
    for item in invoice.line_items:
        tax_pct = f"{item.tax_rate}%" if item.tax_rate > 0 else "—"
        tax_amt = f"{sym}{item.tax_amount:.{decimals}f}" if item.tax_amount else "—"
        item_rows.append([
            item.description,
            str(item.quantity),
            f"{sym}{item.unit_price:.{decimals}f}",
            tax_pct,
            tax_amt,
            f"{sym}{item.total:.{decimals}f}",
        ])

    # Summary rows
    item_rows.append(["", "", "", "", "Subtotal:", f"{sym}{invoice.subtotal:.{decimals}f}"])
    if invoice.total_tax > 0:
        item_rows.append(["", "", "", "", "Tax:", f"{sym}{invoice.total_tax:.{decimals}f}"])
    if invoice.discount_amount > 0:
        item_rows.append(["", "", "", "", "Discount:", f"-{sym}{invoice.discount_amount:.{decimals}f}"])
    item_rows.append(["", "", "", "", "TOTAL:", f"{sym}{invoice.total:.{decimals}f}"])

    col_widths = [2.5 * inch, 0.6 * inch, 0.9 * inch, 0.6 * inch, 0.7 * inch, 0.9 * inch]
    items_table = Table(item_rows, colWidths=col_widths, repeatRows=1)

    # Style the table
    num_data_rows = len(invoice.line_items)
    style_commands = [
        # Header row
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        # All cells
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        # Right-align numeric columns
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        # Grid
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, PRIMARY),
    ]

    # Alternating row colors for data rows
    for i in range(1, num_data_rows + 1):
        if i % 2 == 0:
            style_commands.append(("BACKGROUND", (0, i), (-1, i), TABLE_ALT_ROW))

    # Summary rows styling (after the data rows)
    summary_start = num_data_rows + 1
    style_commands.extend([
        ("LINEABOVE", (0, summary_start), (-1, summary_start), 1, PRIMARY),
        ("FONTNAME", (4, summary_start), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, summary_start), (-1, -1), LIGHT_BG),
    ])
    # Total row
    total_row = len(item_rows) - 1
    style_commands.extend([
        ("FONTNAME", (4, total_row), (-1, total_row), "Helvetica-Bold"),
        ("FONTSIZE", (4, total_row), (-1, total_row), 11),
        ("LINEABOVE", (4, total_row), (-1, total_row), 1.5, PRIMARY),
    ])

    items_table.setStyle(TableStyle(style_commands))
    story.append(items_table)
    story.append(Spacer(1, 16))

    # === PAYMENTS SECTION ===
    if invoice.payments:
        story.append(Paragraph("Payments", styles["heading"]))

        pay_header = ["Date", "Amount", "Method", "Reference", "Notes"]
        pay_rows = [pay_header]
        for p in invoice.payments:
            pay_rows.append([
                str(p.payment_date),
                f"{sym}{p.amount:.{decimals}f}",
                p.method or "—",
                p.reference or "—",
                p.notes or "—",
            ])
        # Summary
        pay_rows.append(["", f"Paid: {sym}{invoice.amount_paid:.{decimals}f}", "", "", ""])
        pay_rows.append(["", f"Remaining: {sym}{invoice.amount_remaining:.{decimals}f}", "", "", ""])

        pay_col_widths = [1 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch, 1.4 * inch]
        pay_table = Table(pay_rows, colWidths=pay_col_widths, repeatRows=1)
        pay_num_data = len(invoice.payments)
        pay_style = [
            ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("LINEBELOW", (0, 0), (-1, 0), 1.5, PRIMARY),
            # Summary rows
            ("LINEABOVE", (0, pay_num_data + 1), (-1, pay_num_data + 1), 1, PRIMARY),
            ("FONTNAME", (0, pay_num_data + 1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, pay_num_data + 1), (-1, -1), LIGHT_BG),
        ]
        for i in range(1, pay_num_data + 1):
            if i % 2 == 0:
                pay_style.append(("BACKGROUND", (0, i), (-1, i), TABLE_ALT_ROW))
        pay_table.setStyle(TableStyle(pay_style))
        story.append(pay_table)
        story.append(Spacer(1, 16))

    # === NOTES ===
    if invoice.notes:
        story.append(Paragraph("Notes", styles["heading"]))
        story.append(Paragraph(invoice.notes, styles["normal"]))
        story.append(Spacer(1, 16))

    # === FOOTER ===
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=8))
    story.append(Paragraph(
        f"Generated by Agent Invoice on {date.today().isoformat()}",
        styles["footer"],
    ))

    # Build the PDF
    doc.build(story)
    return output_path


def generate_estimate_pdf(
    estimate: Estimate,
    output_path: Optional[str] = None,
    company_name: Optional[str] = None,
    company_address: Optional[str] = None,
    company_email: Optional[str] = None,
) -> str:
    """Generate a professional PDF estimate/quote.

    Args:
        estimate: The Estimate object to render.
        output_path: Path to save the PDF. If None, saves to ~/.agent-invoice/exports/.
        company_name: Your company name for the header.
        company_address: Your company address.
        company_email: Your company email.

    Returns:
        The path to the generated PDF file.
    """
    # Determine output path
    if output_path is None:
        export_dir = Path.home() / ".agent-invoice" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        safe_id = estimate.id.replace("/", "_").replace("\\", "_")
        output_path = str(export_dir / f"{safe_id}.pdf")

    # Ensure parent dir exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=25 * mm,
        rightMargin=25 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = _get_styles()
    story = []
    sym = get_currency_symbol(estimate.currency)
    curr_info = CURRENCIES.get(estimate.currency, {})
    decimals = curr_info.get("decimals", 2)

    # === HEADER ===
    header_data = [
        [
            Paragraph(company_name or "ESTIMATE", styles["title"]),
            Paragraph("ESTIMATE", ParagraphStyle(
                "RightTitle", parent=styles["title"], alignment=TA_RIGHT, fontSize=16
            )),
        ],
    ]
    header_table = Table(header_data, colWidths=[3.5 * inch, 2.5 * inch])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=2, color=PRIMARY, spaceAfter=12))

    # === ESTIMATE DETAILS ROW ===
    from_lines = []
    if company_name:
        from_lines.append(f"<b>{company_name}</b>")
    if company_address:
        from_lines.append(company_address)
    if company_email:
        from_lines.append(company_email)
    from_text = "<br/>".join(from_lines) if from_lines else "<b>From:</b> <i>Not specified</i>"

    to_lines = [f"<b>{estimate.client_name or estimate.client_id}</b>"]

    est_meta_lines = [
        f"<b>Estimate #:</b>  {estimate.id}",
        f"<b>Date:</b>  {estimate.issue_date}",
        f"<b>Valid Until:</b>  {estimate.expiry_date or 'N/A'}",
        f"<b>Currency:</b>  {estimate.currency}",
        f"<b>Status:</b>  {estimate.status.value.replace('_', ' ').upper()}",
    ]

    details_data = [
        [
            Paragraph(f"<b>From:</b><br/>{from_text}", styles["normal"]),
            Paragraph(f"<b>Quote For:</b><br/>{'<br/>'.join(to_lines)}", styles["normal"]),
            Paragraph("<br/>".join(est_meta_lines), styles["normal"]),
        ],
    ]
    details_table = Table(details_data, colWidths=[2 * inch, 2 * inch, 2 * inch])
    details_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(details_table)
    story.append(Spacer(1, 16))

    # === LINE ITEMS TABLE ===
    story.append(Paragraph("Items", styles["heading"]))

    item_header = ["Description", "Qty", "Unit Price", "Tax %", "Tax", "Total"]
    item_rows = [item_header]
    for item in estimate.line_items:
        tax_pct = f"{item.tax_rate}%" if item.tax_rate > 0 else "—"
        tax_amt = f"{sym}{item.tax_amount:.{decimals}f}" if item.tax_amount else "—"
        item_rows.append([
            item.description,
            str(item.quantity),
            f"{sym}{item.unit_price:.{decimals}f}",
            tax_pct,
            tax_amt,
            f"{sym}{item.total:.{decimals}f}",
        ])

    # Summary rows
    item_rows.append(["", "", "", "", "Subtotal:", f"{sym}{estimate.subtotal:.{decimals}f}"])
    if estimate.total_tax > 0:
        item_rows.append(["", "", "", "", "Tax:", f"{sym}{estimate.total_tax:.{decimals}f}"])
    if estimate.discount_amount > 0:
        item_rows.append(["", "", "", "", "Discount:", f"-{sym}{estimate.discount_amount:.{decimals}f}"])
    item_rows.append(["", "", "", "", "TOTAL:", f"{sym}{estimate.total:.{decimals}f}"])

    col_widths = [2.5 * inch, 0.6 * inch, 0.9 * inch, 0.6 * inch, 0.7 * inch, 0.9 * inch]
    items_table = Table(item_rows, colWidths=col_widths, repeatRows=1)

    num_data_rows = len(estimate.line_items)
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, PRIMARY),
    ]

    for i in range(1, num_data_rows + 1):
        if i % 2 == 0:
            style_commands.append(("BACKGROUND", (0, i), (-1, i), TABLE_ALT_ROW))

    summary_start = num_data_rows + 1
    style_commands.extend([
        ("LINEABOVE", (0, summary_start), (-1, summary_start), 1, PRIMARY),
        ("FONTNAME", (4, summary_start), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, summary_start), (-1, -1), LIGHT_BG),
    ])
    total_row = len(item_rows) - 1
    style_commands.extend([
        ("FONTNAME", (4, total_row), (-1, total_row), "Helvetica-Bold"),
        ("FONTSIZE", (4, total_row), (-1, total_row), 11),
        ("LINEABOVE", (4, total_row), (-1, total_row), 1.5, PRIMARY),
    ])

    items_table.setStyle(TableStyle(style_commands))
    story.append(items_table)
    story.append(Spacer(1, 16))

    # === TERMS ===
    if estimate.terms:
        story.append(Paragraph("Terms & Conditions", styles["heading"]))
        story.append(Paragraph(estimate.terms, styles["normal"]))
        story.append(Spacer(1, 16))

    # === NOTES ===
    if estimate.notes:
        story.append(Paragraph("Notes", styles["heading"]))
        story.append(Paragraph(estimate.notes, styles["normal"]))
        story.append(Spacer(1, 16))

    # === ACCEPTANCE / CONVERSION STATUS ===
    if estimate.accepted_date:
        story.append(Paragraph(
            f"Accepted on: {estimate.accepted_date}",
            styles["value"],
        ))
        story.append(Spacer(1, 8))
    if estimate.converted_invoice_id:
        story.append(Paragraph(
            f"Converted to Invoice: {estimate.converted_invoice_id}",
            styles["value"],
        ))
        story.append(Spacer(1, 16))

    # === FOOTER ===
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=8))
    story.append(Paragraph(
        f"This is a quote/estimate, not an invoice. Generated by Agent Invoice on {date.today().isoformat()}",
        styles["footer"],
    ))

    # Build the PDF
    doc.build(story)
    return output_path
