from pydantic import BaseModel
from typing import Optional, List


# ── QR ────────────────────────────────────────────────────────────────────────

class QRCodeRequest(BaseModel):
    text: str

class QRCodeResponse(BaseModel):
    qr_code_base64: str
    file_name: str
    success: bool
    message: str



