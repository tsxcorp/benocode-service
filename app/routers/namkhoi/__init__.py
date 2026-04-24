from fastapi import APIRouter
from . import order
from . import quote
from . import purchase_request
from . import create_quote_from_products
from . import create_order_from_products
from . import create_pr_from_nvl
from . import create_pr_from_order

router = APIRouter()

router.include_router(order.router)
router.include_router(quote.router)
router.include_router(purchase_request.router)
router.include_router(create_quote_from_products.router)
router.include_router(create_order_from_products.router)
router.include_router(create_pr_from_nvl.router)
router.include_router(create_pr_from_order.router)
