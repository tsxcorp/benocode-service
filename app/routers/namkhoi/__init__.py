from fastapi import APIRouter
from . import order
from . import quote

router = APIRouter()

# Đăng ký các template router con
router.include_router(order.router)
router.include_router(quote.router)
