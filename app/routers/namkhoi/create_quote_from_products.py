import os
from typing import List, Optional, Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, model_validator
import httpx

# Internal URL (bypasses Traefik on same docker network)
NOCOBASE_URL = os.environ.get("NOCOBASE_URL", "http://nocobase-app-bom42v27enb1jlxwlyg960ay:13000")

# Deep-link to the new quote's view drawer on Danh Sách Báo Giá page
BAOGIA_PAGE_UID = "elqdtfmhgor"
VIEW_POPUP_UID = "4y0ap1h8fzo"


class Product(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    color: Optional[str] = None
    selling_price: Optional[Any] = None
    final_cost_value: Optional[Any] = None
    status: Optional[str] = None


class CreateQuoteFromProductsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: List[Product] = []

    @model_validator(mode="before")
    @classmethod
    def extract(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        # CustomRequestAction sends {data: {$nSelectedRecord: [...]}} or {data: [...]}
        # Sometimes the shape nests further — unwrap safely
        if "data" in values:
            inner = values["data"]
            if isinstance(inner, list):
                return {"data": inner}
            if isinstance(inner, dict):
                # Maybe wrapped one more level (currentRecord etc.)
                for k in ("$nSelectedRecord", "selectedRecords", "records"):
                    if isinstance(inner.get(k), list):
                        return {"data": inner[k]}
                if "data" in inner and isinstance(inner["data"], list):
                    return {"data": inner["data"]}
        # $nSelectedRecord at top-level (bulk action may send this directly)
        for k in ("$nSelectedRecord", "selectedRecords", "records"):
            if isinstance(values.get(k), list):
                return {"data": values[k]}
        return values


router = APIRouter(prefix="/create-quote-from-products", tags=["namkhoi"])


def _currency(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        return None


@router.post("")
async def create_quote_from_products(data: CreateQuoteFromProductsRequest, request: Request):
    products = data.data or []
    if not products:
        return {"message": "⚠️ Vui lòng chọn ít nhất 1 sản phẩm trước khi tạo báo giá.", "redirect_url": ""}

    rejected = [p for p in products if (p.status or "") not in ("approved", "customer_approval")]
    if rejected:
        codes = ", ".join((p.product_code or f"#{p.id}") for p in rejected)
        return {
            "message": (
                f"⚠️ Không thể tạo báo giá. Chỉ SP đã GD Duyệt hoặc KH Duyệt mới được tạo báo giá.\n"
                f"SP không hợp lệ ({len(rejected)}): {codes}"
            ),
            "redirect_url": "",
        }

    # Forward the caller's JWT + role so creates happen AS that user
    auth_header = request.headers.get("authorization") or ""
    role_header = request.headers.get("x-role") or ""
    if not auth_header:
        raise HTTPException(status_code=401, detail="Thiếu Authorization header.")

    fwd_headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json",
    }
    if role_header:
        fwd_headers["X-Role"] = role_header

    async with httpx.AsyncClient(base_url=NOCOBASE_URL, headers=fwd_headers, timeout=60) as client:
        # 1) Create quote header
        resp = await client.post(
            "/api/quotes:create",
            json={
                "status": "draft",
                "vat_rate": 0.08,
                "notes": f"Auto-tạo từ {len(products)} SP đã chọn",
            },
        )
        if resp.status_code >= 300:
            raise HTTPException(
                status_code=500,
                detail=f"Tạo báo giá thất bại ({resp.status_code}): {resp.text[:500]}",
            )
        quote = (resp.json() or {}).get("data") or {}
        quote_id = quote.get("id")
        quote_number = quote.get("quote_number_auto")
        if not quote_id:
            raise HTTPException(status_code=500, detail="NocoBase không trả về quote.id")

        # 2) Create quote_items in parallel (bounded concurrency)
        failures: List[str] = []
        for p in products:
            payload = {
                "quote_id": quote_id,
                "product_id": p.id,
                "product_code_snapshot": p.product_code,
                "product_name_snapshot": p.product_name,
                "color": p.color,
                "quoted_price": _currency(p.selling_price),
                "original_price": _currency(p.selling_price),
                "unit_cost": _currency(p.final_cost_value),
                "item_status": "pending",
            }
            r2 = await client.post("/api/quote_items:create", json=payload)
            if r2.status_code >= 300:
                failures.append(f"{p.product_code or p.id}: {r2.status_code}")

        if failures:
            # Best-effort: leave the quote but report partial failure
            detail = (
                f"Đã tạo báo giá #{quote_number} nhưng {len(failures)} SP lỗi: "
                + ", ".join(failures[:5])
            )
            raise HTTPException(status_code=207, detail=detail)

    redirect_url = f"/admin/{BAOGIA_PAGE_UID}/popups/{VIEW_POPUP_UID}/filterbytk/{quote_id}"
    return {
        "quote_id": quote_id,
        "quote_number_auto": quote_number,
        "redirect_url": redirect_url,
        "message": f"✅ Đã tạo Báo Giá #{quote_number} với {len(products)} SP",
    }
