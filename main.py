import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from app.db import engine
from app.logging_config import configure_logging, correlation_id_var
from app.models import Base
from app.routers import admin, invoices, reviews

configure_logging()
log = structlog.get_logger()


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        token = correlation_id_var.set(correlation_id)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            correlation_id_var.reset(token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        Base.metadata.create_all(bind=engine)
        log.info("database_ready", detail="tables_created")
    except Exception as e:
        log.warning("database initialisation skipped", error=str(e))
    yield


app = FastAPI(
    title="AI Invoice Exception Review System",
    description="Reviews carrier invoices against contracts and shipment records.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(CorrelationMiddleware)

app.include_router(invoices.router)
app.include_router(reviews.router)
app.include_router(admin.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "version": "1.0.0"}
