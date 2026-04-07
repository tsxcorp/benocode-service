import io
import os
import re
from typing import List, Optional, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, model_validator
from datetime import datetime

import httpx
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- Schemas ---
class Customer(BaseModel):
    model_config = ConfigDict(extra='ignore')
    customer_name: Optional[str] = None
    tax_code: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    representative: Optional[str] = None

class Product(BaseModel):
    model_config = ConfigDict(extra='ignore')
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    season: Optional[str] = None
    color: Optional[str] = None

class OrderItem(BaseModel):
    model_config = ConfigDict(extra='ignore')
    quantity: Optional[int] = None
    unit_price: Optional[str] = None
    subtotal_revenue: Optional[str] = None
    size_summary: Optional[str] = None
    product: Optional[Product] = None

class PDFApiRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')
    order_number_auto: Optional[str] = None
    delivery_date: Optional[str] = None
    total_revenue: Optional[str] = None
    vat_rate: Optional[str] = None
    vat_amount: Optional[float] = None
    total_after_tax: Optional[str] = None
    customer: Optional[Customer] = None
    items: Optional[List[OrderItem]] = []

    @model_validator(mode='before')
    @classmethod
    def extract_data(cls, values: Any) -> Any:
        if isinstance(values, dict):
            if 'currentRecord' in values and isinstance(values.get('currentRecord'), dict):
                data_node = values['currentRecord'].get('data')
                if isinstance(data_node, dict):
                    return data_node
        return values

router = APIRouter(prefix="/order", tags=["namkhoi"])

# --- Number to Viet Words ---
def number_to_words_vn(n):
    if n == 0: return "không"
    units = ["", "nghìn", "triệu", "tỷ", "nghìn tỷ", "triệu tỷ"]
    def read_block(block, is_first=False):
        digits = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
        h = block // 100
        t = (block % 100) // 10
        u = block % 10
        res = []
        if h > 0 or not is_first:
            res.append(digits[h] + " trăm")
            if t == 0 and u > 0:
                res.append("lẻ")
        if t == 1:
            res.append("mười")
        elif t > 1:
            res.append(digits[t] + " mươi")
        if u == 1:
            if t > 1: res.append("mốt")
            else: res.append("một")
        elif u == 5 and t > 0:
            res.append("lăm")
        elif u > 0:
            res.append(digits[u])
        return " ".join(res)
    
    parts = []
    unit_idx = 0
    while n > 0:
        block = n % 1000
        if block > 0 or unit_idx == 0:
            parts.append(read_block(block, is_first=(n // 1000 == 0)) + (f" {units[unit_idx]}" if units[unit_idx] else ""))
        n //= 1000
        unit_idx += 1
    return " ".join(reversed(parts)).strip().capitalize() + " đồng"

def parse_sizes(size_summ: str):
    sizes = {'S': '', 'M': '', 'L': '', 'XL': ''}
    if not size_summ:
        return sizes
    tokens = re.findall(r'([sSmMlLxX]+)[\s:]*(\d+)', size_summ)
    for k, v in tokens:
        k_upper = k.upper()
        if k_upper in sizes:
            sizes[k_upper] = v
    return sizes

def build_pdf_document(data: PDFApiRequest) -> bytes:
    buffer = io.BytesIO()
    
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4, 
        rightMargin=1.0*cm, leftMargin=1.0*cm, 
        topMargin=1.5*cm, bottomMargin=1.5*cm
    )
    
    font_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts", "Roboto-Regular.ttf")
    font_bold_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts", "Roboto-Bold.ttf")
    
    has_font = False
    if os.path.exists(font_path) and os.path.exists(font_bold_path):
        pdfmetrics.registerFont(TTFont('Roboto', font_path))
        pdfmetrics.registerFont(TTFont('Roboto-Bold', font_bold_path))
        has_font = True
    
    FONT_NORMAL = "Roboto" if has_font else "Helvetica"
    FONT_BOLD = "Roboto-Bold" if has_font else "Helvetica-Bold"
    
    styles = getSampleStyleSheet()
    
    style_normal = ParagraphStyle('Normal_Vi', fontName=FONT_NORMAL, fontSize=9, leading=12)
    style_bold = ParagraphStyle('Bold_Vi', fontName=FONT_BOLD, fontSize=9, leading=12)
    style_center_bold = ParagraphStyle('Center_Bold_Vi', fontName=FONT_BOLD, fontSize=9, alignment=TA_CENTER, leading=12)
    style_center = ParagraphStyle('Center_Vi', fontName=FONT_NORMAL, fontSize=9, alignment=TA_CENTER)
    style_title = ParagraphStyle('Title_Vi', fontName=FONT_BOLD, fontSize=16, alignment=TA_CENTER, leading=20, spaceAfter=5, textColor=colors.HexColor("#A8294B"))
    
    elements = []
    
    # --- HEADER SECTION ---
    elements.append(Paragraph("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", style_center_bold))
    elements.append(Paragraph("ĐỘC LẬP - TỰ DO - HẠNH PHÚC", style_center_bold))
    elements.append(Paragraph("--------oOo--------", style_center_bold))
    elements.append(Spacer(1, 0.3*cm))
    
    elements.append(Paragraph("<u>ĐƠN ĐẶT HÀNG</u>", style_title))
    
    order_number = data.order_number_auto or ".................."
    elements.append(Paragraph(f"Số: {order_number}", style_center))
    elements.append(Spacer(1, 0.5*cm))
    
    # --- VENDOR & BUYER SECTION ---
    cust = data.customer or Customer()
    
    # Use Table for perfectly aligned info
    v_data = [
        [Paragraph("<b>BÊN BÁN : CÔNG TY TNHH NK FLEXIBLE</b>", style_normal), Paragraph(f"<b>BÊN MUA: {cust.customer_name or '................'}</b>", style_normal)],
        [Paragraph("Địa chỉ: 12B Đường Thạnh lộc 07, phường Thạnh Lộc, Quận 12, Thành phố Hồ Chí Minh", style_normal), Paragraph(f"Địa chỉ: {cust.address or '................'}", style_normal)],
        [Paragraph("Mã số thuế: 0317898840", style_normal), Paragraph(f"Mã số thuế: {cust.tax_code or '................'}", style_normal)],
        [Paragraph("Điện thoại: 0967186179", style_normal), Paragraph(f"Điện thoại: {cust.phone or '................'}", style_normal)],
        [Paragraph("Đại điện bởi: (Ông) NGUYỄN TRỌNG NGHĨA", style_normal), Paragraph(f"Đại điện bởi: {cust.representative or '................'}", style_normal)],
    ]
    t_parties = Table(v_data, colWidths=[9.5*cm, 9.5*cm])
    t_parties.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
    ]))
    elements.append(t_parties)
    elements.append(Spacer(1, 0.5*cm))
    
    # --- TABLE SECTION ---
    elements.append(Paragraph("<b>I. HÀNG HÓA, SỐ LƯỢNG, ĐƠN GIÁ, TỔNG GIÁ TRỊ:</b>", style_bold))
    elements.append(Spacer(1, 0.2*cm))
    
    row_1 = [
        Paragraph("<b>STT</b>", style_center_bold),
        Paragraph("<b>BST</b>", style_center_bold),
        Paragraph("<b>MÃ HÀNG</b>", style_center_bold),
        Paragraph("<b>HÌNH ẢNH</b>", style_center_bold),
        Paragraph("<b>Màu</b>", style_center_bold),
        Paragraph("<b>SỐ LƯỢNG<br/>(Pcs)</b>", style_center_bold),
        Paragraph("<b>SỐ LƯỢNG THEO TỶ LỆ (Pcs)</b>", style_center_bold), "", "", "",
        Paragraph("<b>ĐƠN GIÁ<br/>(Vnd/Pcs)</b>", style_center_bold),
        Paragraph("<b>THÀNH TIỀN<br/>(Vnd)</b>", style_center_bold),
    ]
    row_2 = [
        "", "", "", "", "", "",
        Paragraph("Size S", style_center),
        Paragraph("Size M", style_center),
        Paragraph("Size L", style_center),
        Paragraph("Size XL", style_center),
        "", ""
    ]
    table_data = [row_1, row_2]
    
    for i, it in enumerate(data.items or []):
        qty = int(it.quantity or 0)
        price_val = float(it.unit_price or 0)
        amount_val = float(it.subtotal_revenue or 0)
        
        prod = it.product or Product()
        sizes = parse_sizes(it.size_summary or "")
        
        table_data.append([
            Paragraph(str(i+1), style_center_bold),
            Paragraph(prod.season or "", style_center),
            Paragraph(prod.product_code or "", style_center),
            "", # HÌNH ẢNH để trống
            Paragraph(prod.color or "", style_center),
            Paragraph(f"{qty:,.0f}".replace(",", ".") if qty else "0", style_center),
            Paragraph(sizes['S'], style_center),
            Paragraph(sizes['M'], style_center),
            Paragraph(sizes['L'], style_center),
            Paragraph(sizes['XL'], style_center),
            Paragraph(f"{price_val:,.0f}".replace(",", ".") if price_val else "0", style_center),
            Paragraph(f"{amount_val:,.0f}".replace(",", ".") if amount_val else "0", style_center),
        ])
    
    total_rev = float(data.total_revenue or 0)
    vat_amt = float(data.vat_amount or 0)
    total_tax = float(data.total_after_tax or 0)
    vat_pct = float(data.vat_rate or 0.08) * 100
    
    table_data.append([
        Paragraph("<b>TỔNG CỘNG TRƯỚC THUẾ</b>", style_center_bold),
        "", "", "", "", "", "", "", "", "", "",
        Paragraph(f"<b>{total_rev:,.0f}</b>".replace(",", "."), style_center_bold)
    ])
    table_data.append([
        Paragraph(f"<b>THUẾ VAT {vat_pct:g}%</b>", style_center_bold),
        "", "", "", "", "", "", "", "", "", "",
        Paragraph(f"<b>{vat_amt:,.0f}</b>".replace(",", "."), style_center_bold)
    ])
    table_data.append([
        Paragraph("<b>TỔNG CỘNG SAU THUẾ</b>", style_center_bold),
        "", "", "", "", "", "", "", "", "", "",
        Paragraph(f"<b>{total_tax:,.0f}</b>".replace(",", "."), style_center_bold)
    ])
    
    col_widths = [0.8*cm, 1.5*cm, 2.0*cm, 2.0*cm, 1.8*cm, 1.6*cm, 1.3*cm, 1.3*cm, 1.3*cm, 1.3*cm, 1.8*cm, 2.3*cm]
    t_items = Table(table_data, colWidths=col_widths, repeatRows=2)
    
    ts = TableStyle([
        ('BACKGROUND', (0,0), (-1,1), colors.HexColor("#dae3f3")), # light blue shade like excel
        ('TEXTCOLOR', (0,0), (-1,-1), colors.black),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        
        # Header Spacing
        ('SPAN', (0,0), (0,1)),
        ('SPAN', (1,0), (1,1)),
        ('SPAN', (2,0), (2,1)),
        ('SPAN', (3,0), (3,1)),
        ('SPAN', (4,0), (4,1)),
        ('SPAN', (5,0), (5,1)),
        ('SPAN', (6,0), (9,0)), # SỐ LƯỢNG THEO TỶ LỆ spans S,M,L,XL
        ('SPAN', (10,0), (10,1)),
        ('SPAN', (11,0), (11,1)),
        
        # Footer Spacing
        ('SPAN', (0, -3), (10, -3)), # Total before tax
        ('SPAN', (0, -2), (10, -2)), # VAT
        ('SPAN', (0, -1), (10, -1)), # Total after tax
    ])
    t_items.setStyle(ts)
    elements.append(t_items)
    elements.append(Spacer(1, 0.2*cm))
    
    elements.append(Paragraph("*Đơn giá chưa bao gồm VAT.", style_normal))
    
    # Word representation
    words = number_to_words_vn(int(total_tax)).replace(' không trăm đồng', ' đồng').replace(' mươi không', ' mươi')
    if words.endswith("lẻ đồng"): words = words.replace("lẻ đồng", "đồng")
    elements.append(Paragraph(f"<b>Thành tiền bằng chữ: {words}.</b>", style_bold))
    
    if data.delivery_date:
        try:
            d = datetime.strptime(data.delivery_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        except:
            d = data.delivery_date
    else:
        d = "................"
    elements.append(Paragraph(f"<b>Ngày giao hàng: {d}</b>", style_bold))
    elements.append(Spacer(1, 0.2*cm))
    
    # --- TERMS SECTION ---
    elements.append(Paragraph("<b>II. BAO BÌ, ĐÓNG GÓI:</b>", style_bold))
    elements.append(Paragraph("- Đóng trong túi bóng thành kiện ( Dán tem giá, treo thẻ bài trên từng sản phẩm)", style_normal))
    elements.append(Paragraph("- Tỷ lệ đóng gói: đơn size, đơn màu, cột 5 cái/ bó.", style_normal))
    elements.append(Spacer(1, 0.2*cm))
    
    elements.append(Paragraph("<b>III. THANH TOÁN:</b>", style_bold))
    elements.append(Paragraph("Dựa theo thỏa thuận:", style_normal))
    
    adv_pct = 0.3
    adv_amt = total_tax * adv_pct
    
    elements.append(Paragraph(f"+ Ứng trước 30% khi chốt PO. Tương đương số tiền: {adv_amt:,.0f} VND".replace(",", "."), style_normal))
    elements.append(Paragraph("+ Thanh toán đợt 2: 30% có VAT sau khi giao hàng 45 ngày.", style_normal))
    elements.append(Paragraph("+ Thanh toán đợt 3: 40% còn lại có VAT sau 45 ngày thanh toán đợt 2.", style_normal))
    
    elements.append(Spacer(1, 0.2*cm))
    elements.append(Paragraph("CÔNG TY TNHH NK FLEXIBLE", style_normal))
    elements.append(Paragraph("Số TK : 9668796789", style_normal))
    elements.append(Paragraph("Ngân Hàng: Ngân Hàng Quân Đội - MB Bank", style_normal))
    elements.append(Spacer(1, 0.2*cm))
    
    elements.append(Paragraph("<b>IV. ĐIỀU KHOẢN CHUNG:</b>", style_bold))
    elements.append(Paragraph(f"Đơn đặt hàng này không thể tách rời hợp đồng.", style_normal))
    elements.append(Paragraph("Đơn đặt hàng được lập thành hai (02) bản có giá trị kể từ ngày ký, mỗi bên giữ một (01) bản có giá trị pháp lý như nhau.", style_normal))
    elements.append(Spacer(1, 0.5*cm))
    
    # --- SIGNATURES ---
    sig_data = [
        [
            Paragraph("<b>ĐẠI DIỆN BÊN BÁN</b>", style_center_bold),
            Paragraph("<b>ĐẠI DIỆN BÊN MUA</b>", style_center_bold)
        ]
    ]
    t_sigs = Table(sig_data, colWidths=[9.5*cm, 9.5*cm])
    elements.append(t_sigs)
    
    doc.build(elements)
    buffer.seek(0)
    return buffer.read()

@router.post("")
async def export_pdf(data: PDFApiRequest):
    try:
        pdf_bytes = build_pdf_document(data)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        headers = {
            'Content-Disposition': f'attachment; filename="Order_export_{timestamp}.pdf"',
            'Access-Control-Expose-Headers': 'Content-Disposition',
            'Content-Length': str(len(pdf_bytes))
        }
        return Response(
            content=pdf_bytes, 
            media_type="application/pdf", 
            headers=headers
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
