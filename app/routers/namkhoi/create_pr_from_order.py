import os
from typing import List, Optional, Any, Dict
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, model_validator
import httpx

NOCOBASE_URL = os.environ.get("NOCOBASE_URL", "http://nocobase-app-bom42v27enb1jlxwlyg960ay:13000")

PR_PAGE_UID = "dfwnp1x0sxi"
PR_VIEW_POPUP_UID = "z3s0qr58l9v"


class Order(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Optional[int] = None
    order_number_auto: Optional[str] = None
    createdById: Optional[int] = None


class CreatePrFromOrderRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: Order = Order()

    @model_validator(mode="before")
    @classmethod
    def extract(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        # CustomRequestAction row-level → data.data is a single record object
        inner = values.get("data")
        if isinstance(inner, dict):
            # Sometimes wrapped: {"data": {"data": {...order...}}}
            if "data" in inner and isinstance(inner["data"], dict):
                return {"data": inner["data"]}
            return {"data": inner}
        # Fallback: flat order passed at top-level
        if "id" in values:
            return {"data": values}
        return values


router = APIRouter(prefix="/create-pr-from-order", tags=["namkhoi"])


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        return None


@router.post("")
async def create_pr_from_order(data: CreatePrFromOrderRequest, request: Request):
    order = data.data
    if not order.id:
        return {
            "message": "⚠️ Không xác định được đơn hàng. Hãy thử click trực tiếp vào button Tạo PR trên row.",
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

    async with httpx.AsyncClient(base_url=NOCOBASE_URL, headers=fwd_headers, timeout=120) as client:
        # 1) QUERY order_items của đơn
        r = await client.get(
            "/api/order_items:list",
            params={
                "filter": '{"order_id":{"$eq":' + str(order.id) + '}}',
                "pageSize": 500,
            },
        )
        if r.status_code >= 300:
            raise HTTPException(500, f"Query order_items failed ({r.status_code}): {r.text[:300]}")
        order_items = (r.json() or {}).get("data") or []
        if not order_items:
            return {
                "message": f"⚠️ Đơn hàng #{order.order_number_auto or order.id} không có order_items nào.",
                "redirect_url": "",
            }

        # 2) CREATE PR header
        pr_payload = {
            "status": "draft",
            "notes": f"Auto-tạo từ đơn hàng {order.order_number_auto or ('#' + str(order.id))}",
        }
        if order.createdById:
            pr_payload["buyer_id"] = order.createdById
        r = await client.post("/api/purchase_requests:create", json=pr_payload)
        if r.status_code >= 300:
            raise HTTPException(500, f"Create PR failed ({r.status_code}): {r.text[:300]}")
        pr = (r.json() or {}).get("data") or {}
        pr_id = pr.get("id")
        pr_number = pr.get("pr_number_auto")
        if not pr_id:
            raise HTTPException(500, "NocoBase không trả về purchase_request.id")

        # 3) Aggregate materials + trimmings across all order_items
        # Key = ('material', nvl_catalog_id, supplier_id) or ('trimming', standard_trimming_id, supplier_id)
        # Value = { snapshot fields, total_quantity, allocations: [(order_item_id, qty)] }
        agg: Dict[tuple, Dict[str, Any]] = {}

        material_failures: List[str] = []
        for oi in order_items:
            oi_id = oi.get("id")
            qty_order = _num(oi.get("quantity")) or 0
            product_id = oi.get("product_id")
            if not product_id or qty_order <= 0:
                continue

            # Fetch product_materials for this product
            pm = await client.get(
                "/api/product_materials:list",
                params={
                    "filter": (
                        '{"$and":['
                        f'{{"product_id":{{"$eq":{product_id}}}}},'
                        '{"nvl_catalog_id":{"$notEmpty":true}},'
                        '{"purchase_price":{"$gt":0}},'
                        '{"amount_per_product_calc":{"$gt":0}}'
                        ']}'
                    ),
                    "pageSize": 200,
                    "appends": "nvl_catalog,supplier",
                },
            )
            if pm.status_code >= 300:
                material_failures.append(f"product {product_id}: {pm.status_code}")
                continue
            mats = (pm.json() or {}).get("data") or []
            for m in mats:
                nvl_id = m.get("nvl_catalog_id")
                sup_id = m.get("supplier_id")
                price = _num(m.get("purchase_price")) or 0
                amt_per = _num(m.get("amount_per_product_calc")) or 0
                if not nvl_id or price <= 0 or amt_per <= 0:
                    continue
                # qty = amt_per / price * qty_order  (matching workflow formula)
                qty = (amt_per / price) * qty_order if price else 0
                key = ("material", nvl_id, sup_id)
                node = agg.setdefault(
                    key,
                    {
                        "source_type": "material",
                        "nvl_catalog_id": nvl_id,
                        "supplier_id": sup_id,
                        "unit": m.get("unit"),
                        "item_name_snapshot": m.get("material_name_snapshot"),
                        "unit_price": price,
                        "total_quantity": 0.0,
                        "allocations": [],
                    },
                )
                node["total_quantity"] += qty
                node["allocations"].append((oi_id, qty))

            # Fetch product_trimmings for this product
            pt = await client.get(
                "/api/product_trimmings:list",
                params={
                    "filter": (
                        '{"$and":['
                        f'{{"product_id":{{"$eq":{product_id}}}}},'
                        '{"standard_trimming_id":{"$notEmpty":true}},'
                        '{"amount_per_product":{"$gt":0}}'
                        ']}'
                    ),
                    "pageSize": 200,
                    "appends": "standard_trimming",
                },
            )
            if pt.status_code >= 300:
                material_failures.append(f"product {product_id} trimmings: {pt.status_code}")
                continue
            trims = (pt.json() or {}).get("data") or []
            for t in trims:
                std_id = t.get("standard_trimming_id")
                sup_id = t.get("supplier_id")
                amt_per = _num(t.get("amount_per_product")) or 0
                price = _num(t.get("price_snapshot"))
                if not std_id or amt_per <= 0:
                    continue
                qty = amt_per * qty_order
                key = ("trimming", std_id, sup_id)
                node = agg.setdefault(
                    key,
                    {
                        "source_type": "trimming",
                        "standard_trimming_id": std_id,
                        "supplier_id": sup_id,
                        "unit": t.get("unit"),
                        "item_name_snapshot": t.get("trimming_name_snapshot"),
                        "unit_price": price,
                        "total_quantity": 0.0,
                        "allocations": [],
                    },
                )
                node["total_quantity"] += qty
                node["allocations"].append((oi_id, qty))

        if not agg:
            return {
                "message": (
                    f"⚠️ Đơn #{order.order_number_auto or order.id} chưa có NVL/phụ liệu định mức hợp lệ "
                    f"(cần product_materials.nvl_catalog_id + purchase_price + amount_per_product_calc > 0)."
                ),
                "redirect_url": "",
            }

        # 4) For each aggregated node → create pr_item + allocations
        item_count = 0
        alloc_count = 0
        create_failures: List[str] = []
        for key, node in agg.items():
            qty = node["total_quantity"]
            price = node.get("unit_price")
            subtotal = qty * price if (qty and price) else None

            item_payload: Dict[str, Any] = {
                "purchase_request_id": pr_id,
                "source_type": node["source_type"],
                "item_name_snapshot": node.get("item_name_snapshot"),
                "unit": node.get("unit"),
                "total_quantity": qty,
                "unit_price": price,
                "subtotal": subtotal,
                "supplier_id": node.get("supplier_id"),
                "lead_days": 0,
            }
            if node["source_type"] == "material":
                item_payload["nvl_catalog_id"] = node.get("nvl_catalog_id")
            else:
                item_payload["standard_trimming_id"] = node.get("standard_trimming_id")

            r2 = await client.post("/api/purchase_request_items:create", json=item_payload)
            if r2.status_code >= 300:
                create_failures.append(f"{node.get('item_name_snapshot') or key[1]}: {r2.status_code}")
                continue
            pri = (r2.json() or {}).get("data") or {}
            pri_id = pri.get("id")
            item_count += 1

            # Create allocations
            for (oi_id, alloc_qty) in node["allocations"]:
                if not pri_id or not oi_id:
                    continue
                r3 = await client.post(
                    "/api/purchase_request_item_orders:create",
                    json={
                        "purchase_request_item_id": pri_id,
                        "order_item_id": oi_id,
                        "allocated_qty": alloc_qty,
                    },
                )
                if r3.status_code < 300:
                    alloc_count += 1
                else:
                    create_failures.append(
                        f"alloc item={pri_id}→OI{oi_id}: {r3.status_code}"
                    )

    redirect_url = f"/admin/{PR_PAGE_UID}/popups/{PR_VIEW_POPUP_UID}/filterbytk/{pr_id}"

    if create_failures:
        return {
            "pr_id": pr_id,
            "pr_number_auto": pr_number,
            "redirect_url": redirect_url,
            "message": (
                f"⚠️ Đã tạo PR #{pr_number} ({item_count} items, {alloc_count} allocations) "
                f"nhưng {len(create_failures)} lỗi: " + ", ".join(create_failures[:5])
            ),
        }

    return {
        "pr_id": pr_id,
        "pr_number_auto": pr_number,
        "redirect_url": redirect_url,
        "message": (
            f"✅ Đã tạo PR #{pr_number} từ đơn #{order.order_number_auto or order.id} — "
            f"{item_count} items, {alloc_count} allocations"
        ),
    }
