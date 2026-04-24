import os
from typing import List, Optional, Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, model_validator
import httpx

NOCOBASE_URL = os.environ.get("NOCOBASE_URL", "http://nocobase-app-bom42v27enb1jlxwlyg960ay:13000")

PR_PAGE_UID = "dfwnp1x0sxi"
PR_VIEW_POPUP_UID = "z3s0qr58l9v"


class NvlRow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Optional[int] = None
    source_type: Optional[str] = None
    source_ref_id: Optional[int] = None
    nvl_catalog_id: Optional[int] = None
    standard_trimming_id: Optional[int] = None
    supplier_id: Optional[int] = None
    item_name: Optional[str] = None
    item_code: Optional[str] = None
    unit: Optional[str] = None
    total_qty: Optional[Any] = None
    avg_unit_price: Optional[Any] = None
    total_value: Optional[Any] = None
    order_item_ids: Optional[str] = None


class CreatePrFromNvlRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: List[NvlRow] = []

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


router = APIRouter(prefix="/create-pr-from-nvl", tags=["namkhoi"])


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        return None


def _parse_ids(s: Optional[str]) -> List[int]:
    if not s:
        return []
    out: List[int] = []
    for tok in str(s).split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return out


@router.post("")
async def create_pr_from_nvl(data: CreatePrFromNvlRequest, request: Request):
    rows = data.data or []
    if not rows:
        return {
            "message": "⚠️ Vui lòng chọn ít nhất 1 NVL/phụ liệu trước khi tạo PR.",
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
        # 1) Create PR header (status=draft, buyer=currentUser set by frontend default)
        resp = await client.post(
            "/api/purchase_requests:create",
            json={
                "status": "draft",
                "notes": f"Auto-tạo từ {len(rows)} NVL/phụ liệu đã chọn",
            },
        )
        if resp.status_code >= 300:
            raise HTTPException(
                status_code=500,
                detail=f"Tạo PR thất bại ({resp.status_code}): {resp.text[:500]}",
            )
        pr = (resp.json() or {}).get("data") or {}
        pr_id = pr.get("id")
        pr_number = pr.get("pr_number_auto")
        if not pr_id:
            raise HTTPException(status_code=500, detail="NocoBase không trả về purchase_request.id")

        # 2) Create PR items + allocations per row
        failures: List[str] = []
        item_count = 0
        allocation_count = 0
        for r in rows:
            qty = _num(r.total_qty)
            price = _num(r.avg_unit_price)
            subtotal = _num(r.total_value)
            if subtotal is None and qty is not None and price is not None:
                subtotal = qty * price

            item_payload: dict = {
                "purchase_request_id": pr_id,
                "source_type": r.source_type,
                "item_name_snapshot": r.item_name,
                "unit": r.unit,
                "total_quantity": qty,
                "unit_price": price,
                "subtotal": subtotal,
                "supplier_id": r.supplier_id,
            }
            if r.nvl_catalog_id:
                item_payload["nvl_catalog_id"] = r.nvl_catalog_id
            if r.standard_trimming_id:
                item_payload["standard_trimming_id"] = r.standard_trimming_id

            r2 = await client.post("/api/purchase_request_items:create", json=item_payload)
            if r2.status_code >= 300:
                failures.append(f"{r.item_code or r.item_name or '?'}: {r2.status_code}")
                continue
            pri = (r2.json() or {}).get("data") or {}
            pri_id = pri.get("id")
            item_count += 1

            # 3) Link allocations for each order_item_id
            order_item_ids = _parse_ids(r.order_item_ids)
            if pri_id and order_item_ids:
                # Equal-split qty across order_items (user can rebalance later)
                if qty is not None and order_item_ids:
                    split_qty = qty / len(order_item_ids)
                else:
                    split_qty = None
                for oid in order_item_ids:
                    alloc = {
                        "purchase_request_item_id": pri_id,
                        "order_item_id": oid,
                        "allocated_qty": split_qty,
                    }
                    r3 = await client.post(
                        "/api/purchase_request_item_orders:create", json=alloc
                    )
                    if r3.status_code >= 300:
                        failures.append(
                            f"Alloc {r.item_code}→OI{oid}: {r3.status_code}"
                        )
                    else:
                        allocation_count += 1

        if failures:
            msg_warn = (
                f"⚠️ Đã tạo PR #{pr_number} ({item_count} items, {allocation_count} allocations) "
                f"nhưng {len(failures)} lỗi: " + ", ".join(failures[:5])
            )
            # Still redirect — partial success
            redirect_url = f"/admin/{PR_PAGE_UID}/popups/{PR_VIEW_POPUP_UID}/filterbytk/{pr_id}"
            return {
                "pr_id": pr_id,
                "pr_number_auto": pr_number,
                "redirect_url": redirect_url,
                "message": msg_warn,
            }

    redirect_url = f"/admin/{PR_PAGE_UID}/popups/{PR_VIEW_POPUP_UID}/filterbytk/{pr_id}"
    return {
        "pr_id": pr_id,
        "pr_number_auto": pr_number,
        "redirect_url": redirect_url,
        "message": (
            f"✅ Đã tạo PR #{pr_number} — {item_count} items, "
            f"{allocation_count} allocations"
        ),
    }
