import io
import os
from typing import List, Optional, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, model_validator
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT


# ========= Nested schemas =========

class Order(BaseModel):
    model_config = ConfigDict(extra="ignore")
    order_number_auto: Optional[str] = None
    order_number: Optional[str] = None


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Optional[int] = None
    quantity: Optional[float] = None
    color: Optional[str] = None
    order: Optional[Order] = None


class Allocation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    allocated_qty: Optional[float] = None
    order_item: Optional[OrderItem] = None


class NvlCatalog(BaseModel):
    model_config = ConfigDict(extra="ignore")
    material_code: Optional[str] = None
    material_name: Optional[str] = None


class StandardTrimming(BaseModel):
    model_config = ConfigDict(extra="ignore")
    trimming_code: Optional[str] = None
    trimming_name: Optional[str] = None


class Supplier(BaseModel):
    model_config = ConfigDict(extra="ignore")
    supplier_name: Optional[str] = None
    address: Optional[str] = None


class Buyer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    nickname: Optional[str] = None
    username: Optional[str] = None


class PRItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Optional[int] = None
    source_type: Optional[str] = None
    item_name_snapshot: Optional[str] = None
    unit: Optional[str] = None
    total_quantity: Optional[float] = None
    unit_price: Optional[float] = None
    subtotal: Optional[float] = None
    lead_days: Optional[int] = None
    notes: Optional[str] = None
    supplier: Optional[Supplier] = None
    nvl_catalog: Optional[NvlCatalog] = None
    standard_trimming: Optional[StandardTrimming] = None
    order_allocations: Optional[List[Allocation]] = []


class PurchaseRequestPDFRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    pr_number_auto: Optional[str] = None
    order_date: Optional[str] = None
    expected_sync_date: Optional[str] = None
    total_value: Optional[float] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    createdAt: Optional[str] = None
    buyer: Optional[Buyer] = None
    items: Optional[List[PRItem]] = []

    @model_validator(mode="before")
    @classmethod
    def extract_data(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        extracted = values
        # NocoBase CustomRequestAction sends {"data": {...}} — unwrap.
        if "data" in values and isinstance(values["data"], dict):
            extracted = values["data"]
        elif "currentRecord" in values and isinstance(values.get("currentRecord"), dict):
            cr = values["currentRecord"]
            if isinstance(cr.get("data"), dict):
                extracted = cr["data"]
            else:
                extracted = cr
        return extracted


router = APIRouter(prefix="/purchase-request", tags=["namkhoi"])


# ========= Helpers =========

def format_money(val: Any) -> str:
    if val is None or val == "":
        return "-"
    try:
        fval = float(val)
        if fval == 0:
            return "-"
        return f"{fval:,.0f}"
    except Exception:
        return str(val)


def format_qty(val: Any) -> str:
    if val is None or val == "":
        return "-"
    try:
        fval = float(val)
        if fval == 0:
            return "-"
        if fval == int(fval):
            return f"{int(fval):,}"
        return f"{fval:,.2f}"
    except Exception:
        return str(val)


def _fmt_date(date_str: Optional[str]) -> str:
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return str(date_str)[:10]


def _register_fonts() -> tuple:
    base = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts")
    paths = {
        "normal": os.path.join(base, "Times-Roman.ttf"),
        "bold": os.path.join(base, "Times-Bold.ttf"),
        "italic": os.path.join(base, "Times-Italic.ttf"),
        "bolditalic": os.path.join(base, "Times-BoldItalic.ttf"),
    }
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    fn, fb, fi, fbi = "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"
    try:
        if os.path.exists(paths["normal"]) and os.path.exists(paths["bold"]):
            pdfmetrics.registerFont(TTFont("TimesNewRoman", paths["normal"]))
            pdfmetrics.registerFont(TTFont("TimesNewRoman-Bold", paths["bold"]))
            fn, fb = "TimesNewRoman", "TimesNewRoman-Bold"
        if os.path.exists(paths["italic"]):
            pdfmetrics.registerFont(TTFont("TimesNewRoman-Italic", paths["italic"]))
            fi = "TimesNewRoman-Italic"
        if os.path.exists(paths["bolditalic"]):
            pdfmetrics.registerFont(TTFont("TimesNewRoman-BoldItalic", paths["bolditalic"]))
            fbi = "TimesNewRoman-BoldItalic"
    except Exception as e:
        print("Font load error:", e)
    return fn, fb, fi, fbi


def _load_logo(height_cm: float = 2.5):
    logo_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "images", "logo.jpg")
    try:
        from PIL import Image as PILImage
        img = PILImage.open(logo_path)
        w, h = img.size
        ratio = height_cm * cm / h
        return RLImage(logo_path, width=w * ratio, height=height_cm * cm)
    except Exception:
        return None


# ========= PDF builder =========

def build_pr_pdf(data: PurchaseRequestPDFRequest) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=1.0 * cm, leftMargin=1.0 * cm,
        topMargin=0.8 * cm, bottomMargin=0.8 * cm,
    )
    FONT_NORMAL, FONT_BOLD, FONT_ITALIC, FONT_BOLD_ITALIC = _register_fonts()

    st_normal_c = ParagraphStyle("NC", fontName=FONT_NORMAL, fontSize=9, leading=11, alignment=TA_CENTER)
    st_normal_l = ParagraphStyle("NL", fontName=FONT_NORMAL, fontSize=9, leading=11, alignment=TA_LEFT)
    st_bold_c = ParagraphStyle("BC", fontName=FONT_BOLD, fontSize=9, leading=11, alignment=TA_CENTER)
    st_bold_l = ParagraphStyle("BL", fontName=FONT_BOLD, fontSize=9, leading=11, alignment=TA_LEFT)
    st_bold_r = ParagraphStyle("BR", fontName=FONT_BOLD, fontSize=9, leading=11, alignment=TA_RIGHT)
    st_bold_c10 = ParagraphStyle("BC10", fontName=FONT_BOLD, fontSize=10, leading=13, alignment=TA_CENTER)
    st_title = ParagraphStyle("Title", fontName=FONT_BOLD, fontSize=14, leading=17, alignment=TA_CENTER)
    st_italic_r = ParagraphStyle("IR", fontName=FONT_ITALIC, fontSize=9, leading=11, alignment=TA_RIGHT)

    elements = []

    # ---- Header: logo + company info ----
    logo_img = _load_logo(2.5)
    logo_cell = logo_img if logo_img else Paragraph("NK", st_bold_c10)
    company_cell = [
        Paragraph("<b>CÔNG TY TNHH NK FLEXIBLE</b>", st_bold_c10),
        Paragraph("<b>NK FLEXIBLE COMPANY LIMITED</b>", st_bold_c10),
        Paragraph("VP/Add: số 4 đường Trần Quý Khoách, Phường Tân Định, Quận 1, TP.HCM", st_bold_c),
        Paragraph("MST/Tax code: 0317898840   ·   Hotline: 0932 866 179", st_bold_c),
        Paragraph("Email: phoiaosaigon2015@gmail.com", st_bold_c),
        Paragraph("STK: 9668796789 — MBBank PGD 3 Tháng 2", st_bold_c),
    ]

    header_t = Table([[logo_cell, company_cell, ""]], colWidths=[3.0 * cm, 13.0 * cm, 3.0 * cm])
    header_t.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.black),
    ]))
    elements.append(header_t)
    elements.append(Spacer(1, 0.3 * cm))

    # ---- Title + meta row ----
    title_tbl = Table([
        [Paragraph("PHIẾU ĐỀ NGHỊ MUA HÀNG", st_title)],
        [Paragraph(f"Số phiếu: <b>{data.pr_number_auto or '—'}</b>", st_normal_c)],
    ], colWidths=[19.0 * cm])
    title_tbl.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#BFD4E8")),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
    ]))
    elements.append(title_tbl)
    elements.append(Spacer(1, 0.2 * cm))

    buyer_name = "—"
    if data.buyer:
        buyer_name = data.buyer.nickname or data.buyer.username or "—"

    meta_tbl = Table([[
        Paragraph(f"Ngày đặt: <b>{_fmt_date(data.order_date)}</b>", st_normal_l),
        Paragraph(f"Người đề nghị: <b>{buyer_name}</b>", st_normal_l),
        Paragraph(f"Ngày đồng bộ dự kiến: <b>{_fmt_date(data.expected_sync_date)}</b>", st_normal_l),
    ]], colWidths=[5.5 * cm, 7.0 * cm, 6.5 * cm])
    meta_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(meta_tbl)
    elements.append(Spacer(1, 0.2 * cm))

    # ---- Items table ----
    col_widths = [0.8 * cm, 2.0 * cm, 3.5 * cm, 3.2 * cm, 1.0 * cm, 1.5 * cm, 1.5 * cm, 1.8 * cm, 2.2 * cm, 1.5 * cm]
    # sum = 19.0 cm

    head = [
        Paragraph("<b>STT</b>", st_bold_c),
        Paragraph("<b>MÃ HÀNG</b>", st_bold_c),
        Paragraph("<b>TÊN MẶT HÀNG</b>", st_bold_c),
        Paragraph("<b>TÊN NCC<br/>ĐỊA CHỈ</b>", st_bold_c),
        Paragraph("<b>ĐVT</b>", st_bold_c),
        Paragraph("<b>SL ĐƠN HÀNG</b>", st_bold_c),
        Paragraph("<b>SL CẦN ĐẶT</b>", st_bold_c),
        Paragraph("<b>ĐƠN GIÁ</b>", st_bold_c),
        Paragraph("<b>THÀNH TIỀN</b>", st_bold_c),
        Paragraph("<b>GHI CHÚ</b>", st_bold_c),
    ]
    rows = [head]

    sum_subtotal = 0.0
    stt = 0

    for item in (data.items or []):
        allocations = item.order_allocations or []
        item_display_name = item.item_name_snapshot or ""
        if not item_display_name:
            if item.nvl_catalog and item.nvl_catalog.material_name:
                item_display_name = item.nvl_catalog.material_name
            elif item.standard_trimming and item.standard_trimming.trimming_name:
                item_display_name = item.standard_trimming.trimming_name
            else:
                item_display_name = ""

        item_code = "—"
        if item.nvl_catalog and item.nvl_catalog.material_code:
            item_code = item.nvl_catalog.material_code
        elif item.standard_trimming and item.standard_trimming.trimming_code:
            item_code = item.standard_trimming.trimming_code

        supplier_text = "—"
        if item.supplier:
            supplier_name = item.supplier.supplier_name or ""
            supplier_addr = item.supplier.address or ""
            if supplier_name and supplier_addr:
                supplier_text = f"<b>{supplier_name}</b><br/>{supplier_addr}"
            elif supplier_name:
                supplier_text = f"<b>{supplier_name}</b>"

        unit_price = float(item.unit_price or 0)

        if allocations:
            # 1 row per allocation (each order contribution)
            for alloc in allocations:
                stt += 1
                oi = alloc.order_item or OrderItem()
                o = oi.order or Order()
                mh = o.order_number_auto or o.order_number or "—"
                order_qty = oi.quantity or 0
                alloc_qty = alloc.allocated_qty or 0
                line_total = float(alloc_qty) * unit_price
                sum_subtotal += line_total

                name_with_color = item_display_name
                if oi.color:
                    name_with_color = f"{item_display_name} ({oi.color})" if item_display_name else oi.color

                rows.append([
                    Paragraph(f"<b>{stt}</b>", st_bold_c),
                    Paragraph(f"<b>{mh}</b>", st_bold_c),
                    Paragraph(name_with_color, st_normal_l),
                    Paragraph(supplier_text, st_normal_l),
                    Paragraph(item.unit or "", st_normal_c),
                    Paragraph(format_qty(order_qty), st_bold_c),
                    Paragraph(format_qty(alloc_qty), st_bold_c),
                    Paragraph(format_money(unit_price), st_bold_c),
                    Paragraph(format_money(line_total), st_bold_c),
                    Paragraph(item.notes or "", st_normal_l),
                ])
        else:
            # Fallback: no allocations, show item summary as 1 row
            stt += 1
            total_qty = float(item.total_quantity or 0)
            line_total = total_qty * unit_price
            sum_subtotal += line_total
            rows.append([
                Paragraph(f"<b>{stt}</b>", st_bold_c),
                Paragraph("—", st_bold_c),
                Paragraph(item_display_name, st_normal_l),
                Paragraph(supplier_text, st_normal_l),
                Paragraph(item.unit or "", st_normal_c),
                Paragraph("—", st_normal_c),
                Paragraph(format_qty(total_qty), st_bold_c),
                Paragraph(format_money(unit_price), st_bold_c),
                Paragraph(format_money(line_total), st_bold_c),
                Paragraph(item.notes or "", st_normal_l),
            ])

    # Totals
    vat_rate = 0.08
    vat_amount = sum_subtotal * vat_rate
    total_after_vat = sum_subtotal + vat_amount

    rows.append([
        Paragraph("<b>TỔNG CỘNG CHƯA VAT</b>", st_bold_r),
        "", "", "", "", "", "", "",
        Paragraph(f"<b>{format_money(sum_subtotal)}</b>", st_bold_c),
        "",
    ])
    rows.append([
        Paragraph("<b>VAT (8%)</b>", st_bold_r),
        "", "", "", "", "", "", "",
        Paragraph(f"<b>{format_money(vat_amount)}</b>", st_bold_c),
        "",
    ])
    rows.append([
        Paragraph("<b>TỔNG CỘNG</b>", st_bold_r),
        "", "", "", "", "", "", "",
        Paragraph(f"<b>{format_money(total_after_vat)}</b>", st_bold_c),
        "",
    ])

    items_table = Table(rows, colWidths=col_widths, repeatRows=1)
    n_data_rows = len(rows) - 1
    n_total_rows = 3
    n_items = n_data_rows - n_total_rows
    totals_start = 1 + n_items  # 1 = header row

    ts = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f5597")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        # Totals rows merge cols 0..7, value in col 8
        ("SPAN", (0, totals_start), (7, totals_start)),
        ("SPAN", (0, totals_start + 1), (7, totals_start + 1)),
        ("SPAN", (0, totals_start + 2), (7, totals_start + 2)),
        ("BACKGROUND", (0, totals_start), (-1, totals_start + 2), colors.HexColor("#dae3f3")),
        ("ALIGN", (0, totals_start), (7, totals_start + 2), "RIGHT"),
    ]
    items_table.setStyle(TableStyle(ts))
    elements.append(items_table)

    elements.append(Spacer(1, 0.8 * cm))

    # ---- Signatures ----
    date_str = datetime.now().strftime("TP. HCM, ngày %d tháng %m năm %Y")
    if data.createdAt:
        try:
            dt = datetime.fromisoformat(data.createdAt.replace("Z", "+00:00"))
            date_str = dt.strftime("TP. HCM, ngày %d tháng %m năm %Y")
        except Exception:
            pass

    sig_row = Table([[
        "",
        Paragraph(date_str, st_italic_r),
    ]], colWidths=[9.5 * cm, 9.5 * cm])
    elements.append(sig_row)
    elements.append(Spacer(1, 0.2 * cm))

    sig_headers = Table([[
        Paragraph("<b>NGƯỜI ĐỀ NGHỊ</b>", st_bold_c10),
        Paragraph("<b>GIÁM ĐỐC</b>", st_bold_c10),
    ]], colWidths=[9.5 * cm, 9.5 * cm])
    elements.append(sig_headers)
    elements.append(Spacer(1, 2.0 * cm))

    sig_names = Table([[
        Paragraph(f"<b>{buyer_name}</b>", st_bold_c10),
        Paragraph("<b>NGUYỄN TRỌNG NGHĨA</b>", st_bold_c10),
    ]], colWidths=[9.5 * cm, 9.5 * cm])
    elements.append(sig_names)

    doc.build(elements)
    buffer.seek(0)
    return buffer.read()


@router.post("")
async def export_pr_pdf(data: PurchaseRequestPDFRequest):
    try:
        pdf_bytes = build_pr_pdf(data)
        fname_suffix = (data.pr_number_auto or datetime.now().strftime("%Y%m%d_%H%M%S")).replace("/", "_")
        headers = {
            "Content-Disposition": f'attachment; filename="PR_{fname_suffix}.pdf"',
            "Access-Control-Expose-Headers": "Content-Disposition",
            "Content-Length": str(len(pdf_bytes)),
        }
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
