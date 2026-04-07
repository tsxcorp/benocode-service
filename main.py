"""
nexpo-services — FastAPI application entry point.

All endpoint logic lives in app/routers/. Shared helpers in app/services/.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import qr, namkhoi


app = FastAPI(title="Nexpo Services API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://app.nexpo.vn",
        "http://app.nexpo.vn",
        "https://admin.nexpo.vn",
        "https://portal.nexpo.vn",
        "https://insights.nexpo.vn",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "https://cms.nexpo.vn",
        "https://namkhoi.nexpo.vn"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(qr.router)
app.include_router(namkhoi.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
