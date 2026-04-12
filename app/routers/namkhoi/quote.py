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
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

# --- Schemas ---
class Product(BaseModel):
    model_config = ConfigDict(extra='ignore')
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    selling_price: Optional[str] = None

class QuoteItem(BaseModel):
    model_config = ConfigDict(extra='ignore')
    order_quantity: Optional[int] = None
    quoted_price: Optional[float] = None
    subtotal: Optional[float] = None
    fabric_composition: Optional[str] = None
    item_notes: Optional[str] = None
    product: Optional[Product] = None

    @model_validator(mode='before')
    @classmethod
    def map_aliases(cls, values: Any) -> Any:
        if isinstance(values, dict):
            if 'quantity' in values and 'order_quantity' not in values:
                values['order_quantity'] = values['quantity']
            if 'unit_price' in values and 'quoted_price' not in values:
                values['quoted_price'] = values['unit_price']
            if 'subtotal_revenue' in values and 'subtotal' not in values:
                values['subtotal'] = values['subtotal_revenue']
        return values

class Customer(BaseModel):
    model_config = ConfigDict(extra='ignore')
    customer_name: Optional[str] = None

class QuotePDFRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')
    quote_number_auto: Optional[str] = None
    total_revenue: Optional[float] = None
    vat_rate: Optional[float] = None
    vat_amount: Optional[float] = None
    total_after_vat: Optional[float] = None
    createdAt: Optional[str] = None
    customer: Optional[Customer] = None
    quote_items: Optional[List[QuoteItem]] = []

    @model_validator(mode='before')
    @classmethod
    def extract_data(cls, values: Any) -> Any:
        if isinstance(values, dict):
            extracted = values
            if 'currentRecord' in values and isinstance(values.get('currentRecord'), dict):
                data_node = values['currentRecord'].get('data')
                if isinstance(data_node, dict):
                    extracted = data_node
            elif 'data' in values:
                if isinstance(values['data'], dict):
                    extracted = values['data']
                elif isinstance(values['data'], list) and len(values['data']) > 0:
                    first = values['data'][0]
                    if isinstance(first, dict):
                        if 'product_id' in first or 'unit_price' in first or 'quoted_price' in first:
                            extracted = {"quote_items": values['data']}
                        else:
                            extracted = first
            
            # Map alternative naming conventions
            if isinstance(extracted, dict):
                if 'items' in extracted and 'quote_items' not in extracted:
                    extracted['quote_items'] = extracted['items']
                if 'total_after_tax' in extracted and 'total_after_vat' not in extracted:
                    extracted['total_after_vat'] = extracted['total_after_tax']
            return extracted
        return values

router = APIRouter(prefix="/quote", tags=["namkhoi"])

def format_money(val: Any) -> str:
    if val is None or val == "":
        return "-"
    try:
        fval = float(val)
        if fval == 0:
            return "-"
        return f"{fval:,.0f}"
    except:
        return str(val)

def build_quote_pdf(data: QuotePDFRequest) -> bytes:
    buffer = io.BytesIO()
    
    # Page layout
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4, 
        rightMargin=1.0*cm, leftMargin=1.0*cm, 
        topMargin=1.0*cm, bottomMargin=1.0*cm
    )
    
    # Fonts
    font_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts", "Times-Roman.ttf")
    font_bold_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts", "Times-Bold.ttf")
    font_italic_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts", "Times-Italic.ttf")
    font_bold_italic_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts", "Times-BoldItalic.ttf")
    
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    has_font = False
    try:
        if os.path.exists(font_path) and os.path.exists(font_bold_path):
            pdfmetrics.registerFont(TTFont('TimesNewRoman', font_path))
            pdfmetrics.registerFont(TTFont('TimesNewRoman-Bold', font_bold_path))
            has_font = True
        if os.path.exists(font_italic_path):
            pdfmetrics.registerFont(TTFont('TimesNewRoman-Italic', font_italic_path))
        if os.path.exists(font_bold_italic_path):
            pdfmetrics.registerFont(TTFont('TimesNewRoman-BoldItalic', font_bold_italic_path))
    except Exception as e:
        print("Font load error:", e)
        pass
    
    FONT_NORMAL = "TimesNewRoman" if has_font else "Times-Roman"
    FONT_BOLD = "TimesNewRoman-Bold" if has_font else "Times-Bold"
    FONT_ITALIC = "TimesNewRoman-Italic" if (has_font and os.path.exists(font_italic_path)) else "Times-Italic"
    FONT_BOLD_ITALIC = "TimesNewRoman-BoldItalic" if (has_font and os.path.exists(font_bold_italic_path)) else "Times-BoldItalic"
    
    style_normal_center = ParagraphStyle('Normal_Center_Vi', fontName=FONT_NORMAL, fontSize=9, leading=12, alignment=TA_CENTER)
    style_bold_center = ParagraphStyle('Bold_Center_Vi', fontName=FONT_BOLD, fontSize=9, leading=12, alignment=TA_CENTER)
    style_bold_center_10 = ParagraphStyle('Bold_Center_10_Vi', fontName=FONT_BOLD, fontSize=10, leading=14, alignment=TA_CENTER)
    
    style_italic_center = ParagraphStyle('Italic_Center_Vi', fontName=FONT_ITALIC, fontSize=9, leading=12, alignment=TA_CENTER)
    style_bold_italic_left = ParagraphStyle('BoldItalic_Left_Vi', fontName=FONT_BOLD_ITALIC, fontSize=9, leading=12, alignment=TA_LEFT)
    style_bold_right = ParagraphStyle('Bold_Right_Vi', fontName=FONT_BOLD, fontSize=10, leading=14, alignment=TA_CENTER) # We will align it manually via spacer
    
    elements = []
    
    logo_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "images", "logo.jpg")
    try:
        from PIL import Image as PILImage
        img = PILImage.open(logo_path)
        w, h = img.size
        ratio = 2.5 * cm / h
        img_w = w * ratio
        img_h = 2.5 * cm
        logo_img = RLImage(logo_path, width=img_w, height=img_h)
    except Exception:
        logo_img = Paragraph("Logo", style_normal_center)
        
    company_text = [
        Paragraph("<b>CÔNG TY TNHH NK FLEXIBLE</b>", style_bold_center_10),
        Paragraph("<b>NK FLEXIBLE COMPANY LIMITED</b>", style_bold_center_10),
        Paragraph("<b>VP/Add: số 4 đường Trần Quý Khoách, Phường Tân Định, Quận 1, TP.HCM</b>", style_bold_center),
        Paragraph("<b>MST/Tax code: 0317898840</b>", style_bold_center),
        Paragraph("<b>Email: phoiaosaigon2015@gmail.com</b>", style_bold_center),
        Paragraph("<b>Hotline:</b>", style_bold_center),
    ]
    
    header_subtable = Table([[logo_img, company_text, ""]], colWidths=[3.0*cm, 13.0*cm, 3.0*cm])
    header_subtable.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    
    col_widths = [1.0*cm, 2.2*cm, 3.5*cm, 3.0*cm, 2.5*cm, 2.3*cm, 2.5*cm, 2.0*cm]
    # Sum = 19.0 cm
    
    table_data = [
        [header_subtable, "", "", "", "", "", "", ""],
        [Paragraph("<b>QUOTATION</b>", style_bold_center_10), "", "", "", "", "", "", ""],
        [Paragraph("<i>First of all, we would like to thank you for your interest in our company's products. We would like to send you the price quote as follows:</i>", style_italic_center), "", "", "", "", "", "", ""],
        [
            Paragraph("<b>Serial</b>", style_bold_center),
            Paragraph("<b>Style No</b>", style_bold_center),
            Paragraph("<b>Image</b>", style_bold_center),
            Paragraph("<b>Fabric Compositon</b>", style_bold_center),
            Paragraph("<b>Order Quantity</b>", style_bold_center),
            Paragraph("<b>Price<br/>VND/pc)</b>", style_bold_center),
            Paragraph("<b>Total</b>", style_bold_center),
            Paragraph("<b>Note</b>", style_bold_center),
        ]
    ]
    
    N = len(data.quote_items or [])
    for i, it in enumerate(data.quote_items or []):
        prod = it.product or Product()
        price = it.quoted_price
        if price is None:
            price = prod.selling_price
        
        table_data.append([
            Paragraph(f"<b>{i+1}</b>", style_bold_center),
            Paragraph(f"<b>{prod.product_code or prod.product_name or ''}</b>", style_bold_center),
            "", # Image
            Paragraph(it.fabric_composition or "", style_normal_center),
            Paragraph(f"{it.order_quantity or ''}", style_bold_center),
            Paragraph(f"<b>{format_money(price)}</b>", style_bold_center),
            Paragraph(f"<b>{format_money(it.subtotal)}</b>", style_bold_center),
            Paragraph(it.item_notes or "", style_normal_center),
        ])
    
    vat_rate_pct = int((data.vat_rate or 0) * 100) if data.vat_rate else 8
    
    table_data.append([
        Paragraph("<b>TOTAL</b>", style_bold_center), "", "", "", "", 
        Paragraph("<b>-</b>", style_bold_center), 
        Paragraph(f"<b>{format_money(data.total_revenue)}</b>", style_bold_center), 
        ""
    ])
    table_data.append([
        Paragraph(f"<b>VAT ({vat_rate_pct}%)</b>", style_bold_center), "", "", "", "", 
        "", 
        Paragraph(f"<b>{format_money(data.vat_amount)}</b>", style_bold_center), 
        ""
    ])
    table_data.append([
        Paragraph("<b>TOTAL</b>", style_bold_center), "", "", "", "", 
        "", 
        Paragraph(f"<b>{format_money(data.total_after_vat)}</b>", style_bold_center), 
        ""
    ])
    
    row_heights = [
        None,    # Header logo
        None,    # QUOTATION
        None,    # Greeting
        1.2*cm,  # Table headers
    ] + [2.0*cm for _ in range(N)] + [
        0.8*cm,  # TOTAL 1
        0.8*cm,  # VAT
        0.8*cm,  # TOTAL 2
    ]
    
    t_items = Table(table_data, colWidths=col_widths, rowHeights=row_heights)
    
    ts = [
        ('BOX', (0,0), (-1,-1), 1, colors.black),
        ('GRID', (0,3), (-1,-1), 1, colors.black),
        
        ('LINEBELOW', (0,0), (-1,0), 1, colors.black),
        ('LINEBELOW', (0,1), (-1,1), 1, colors.black),
        ('LINEBELOW', (0,2), (-1,2), 1, colors.black),
        ('LINEABOVE', (0, N+4), (-1, N+4), 1, colors.black),
        ('LINEABOVE', (0, N+5), (-1, N+5), 1, colors.black),
        
        ('TOPPADDING', (0,1), (-1,2), 6),
        ('BOTTOMPADDING', (0,1), (-1,2), 6),
        
        ('SPAN', (0,0), (-1,0)),
        ('SPAN', (0,1), (-1,1)),
        ('SPAN', (0,2), (-1,2)),
        
        ('SPAN', (0, N+4), (4, N+4)), # TOTAL 1
        ('SPAN', (0, N+5), (5, N+5)), # VAT
        ('SPAN', (0, N+6), (5, N+6)), # TOTAL 2
        
        ('BACKGROUND', (0,1), (-1,1), colors.HexColor("#9bc2e6")), # light blue
        ('BACKGROUND', (0,3), (-1,3), colors.HexColor("#2f5597")), # dark blue
        ('BACKGROUND', (0,4), (0, N+3), colors.HexColor("#dae3f3")), # light blue serial
        ('BACKGROUND', (0, N+4), (-1, N+6), colors.HexColor("#dae3f3")), # totals row background
        
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('LEFTPADDING', (0,0), (-1,-1), 1),
        ('RIGHTPADDING', (0,0), (-1,-1), 1),
    ]
    t_items.setStyle(TableStyle(ts))
    elements.append(t_items)
    
    elements.append(Spacer(1, 0.4*cm))
    
    elements.append(Paragraph("<b><i>Looking forward to hearing from you, and if you have any questions, please contact us.</i></b>", style_bold_italic_left))
    elements.append(Paragraph("<b><i>Thanks and best regard !</i></b>", style_bold_italic_left))
    elements.append(Paragraph("<b><i>Note: Quotation is valid from the date of signing until further notice.</i></b>", style_bold_italic_left))
    
    elements.append(Spacer(1, 0.8*cm))
    
    date_str = "HCM City, ................"
    if data.createdAt:
        try:
            dt = datetime.fromisoformat(data.createdAt.replace('Z', '+00:00'))
            date_str = dt.strftime("HCM City, %d %b %Y")
        except:
            pass
            
    # Draw right aligned text blocks as a small table to keep them perfectly aligned
    sig_data = [
        [Paragraph(f"<b>{date_str}</b>", style_bold_center_10)],
        [Paragraph("<b>Director</b>", style_bold_center_10)],
        [Spacer(1, 2.5*cm)],
        [Paragraph("<b>NGUYỄN TRỌNG NGHĨA</b>", style_bold_center_10)]
    ]
    t_sig = Table(sig_data, colWidths=[6*cm])
    t_sig.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
    
    # We want t_sig to be on the right side.
    t_bottom = Table([['', t_sig]], colWidths=[13*cm, 6*cm])
    elements.append(t_bottom)
    
    doc.build(elements)
    buffer.seek(0)
    return buffer.read()

@router.post("")
async def export_quote_pdf(data: QuotePDFRequest):
    try:
        pdf_bytes = build_quote_pdf(data)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        headers = {
            'Content-Disposition': f'attachment; filename="Quotation_{timestamp}.pdf"',
            'Access-Control-Expose-Headers': 'Content-Disposition',
            'Content-Length': str(len(pdf_bytes))
        }
        return Response(
            content=pdf_bytes, 
            media_type="application/pdf", 
            headers=headers
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
