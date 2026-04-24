import os
from typing import List, Optional, Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, model_validator
import httpx

NOCOBASE_URL = os.environ.get("NOCOBASE_URL", "http://nocobase-app-bom42v27enb1jlxwlyg960ay:13000")

DONHANG_PAGE_UID = "2l8aly8b88r"
ORDER_EDIT_UID = "4y06tmon726"


class Product(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    color: Optional[str] = None
    selling_price: Optional[Any] = None
    final_cost_value: Optional[Any] = None
    status: Optional[str] = None


class CreateOrderFromProductsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: List[Product] = []

    @model_validator(mode="before")
    @classmethod
    def extract(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        if "data" in values:
            inner = values["data"]
            if isinstance(inner, list):
                return {"data": inner}
            if isinstance(inner, dict):
                for k in ("$nSelectedRecord", "selectedRecords", "records"):
                    if isinstance(inner.get(k), list):
                        return {"data": inner[k]}
                if "data" in inner and isinstance(inner["data"], list):
                    return {"data": inner["data"]}
        for k in ("$nSelectedRecord", "selectedRecords", "records"):
            if isinstance(values.get(k), list):
                return {"data": values[k]}
        return values


router = APIRouter(prefix="/create-order-from-products", tags=["namkhoi"])


def _currency(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        return None


@router.post("")
async def create_order_from_products(data: CreateOrderFromProductsRequest, request: Request):
    products = data.data or []
    if not products:
        return {"message": "⚠️ Vui lòng chọn ít nhất 1 sản phẩm trước khi tạo đơn hàng.", "redirect_url": ""}

    rejected = [p for p in products if (p.status or "") != "customer_approval"]
    if rejected:
        codes = ", ".join((p.product_code or f"#{p.id}") for p in rejected)
        return {
            "message": (
                f"⚠️ Không thể tạo đơn hàng. Chỉ SP đã KH Duyệt mới được tạo đơn hàng.\n"
                f"SP chưa KH duyệt ({len(rejected)}): {codes}"
            ),
            "redirect_url": "",
        }

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
        resp = await client.post(
            "/api/orders:create",
            json={
                "status": "draft",
                "order_type": "manufacturing",
                "vat_rate": 0.08,
                "notes": f"Auto-tạo từ {len(products)} SP KH đã duyệt",
            },
        )
        if resp.status_code >= 300:
            raise HTTPException(
                status_code=500,
                detail=f"Tạo đơn hàng thất bại ({resp.status_code}): {resp.text[:500]}",
            )
        order = (resp.json() or {}).get("data") or {}
        order_id = order.get("id")
        order_number = order.get("order_number_auto") or order.get("order_number")
        if not order_id:
            raise HTTPException(status_code=500, detail="NocoBase không trả về order.id")

        failures: List[str] = []
        for p in products:
            payload = {
                "order_id": order_id,
                "product_id": p.id,
                "quantity": 1,
                "color": p.color,
                "unit_price": _currency(p.selling_price),
                "unit_cost": _currency(p.final_cost_value),
                "item_notes": f"{p.product_code or ''} {p.product_name or ''}".strip() or None,
            }
            r2 = await client.post("/api/order_items:create", json=payload)
            if r2.status_code >= 300:
                failures.append(f"{p.product_code or p.id}: {r2.status_code}")

        if failures:
            detail = (
                f"Đã tạo đơn hàng #{order_number} nhưng {len(failures)} SP lỗi: "
                + ", ".join(failures[:5])
            )
            raise HTTPException(status_code=207, detail=detail)

    redirect_url = f"/admin/{DONHANG_PAGE_UID}/popups/{ORDER_EDIT_UID}/filterbytk/{order_id}"
    return {
        "order_id": order_id,
        "order_number": order_number,
        "redirect_url": redirect_url,
        "message": f"✅ Đã tạo Đơn Hàng #{order_number} với {len(products)} SP",
    }
