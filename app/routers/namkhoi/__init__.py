from fastapi import APIRouter
from . import order

router = APIRouter()

# Đăng ký các template router con
router.include_router(order.router)
