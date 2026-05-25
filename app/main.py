import time
import uuid

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.auth.routes import router as auth_router
from app.config import settings

logger = structlog.get_logger()


def create_app() -> FastAPI:
    """
    App factory pattern — creates and configures the FastAPI application.

    Using a factory function (rather than a module-level `app = FastAPI()`) makes
    testing easier: tests can call create_app() with different settings without
    importing a shared global that's already configured.
    """
    app = FastAPI(
        title="JobTrack Core API",
        description="AI-Powered Job Application Tracker — Core Backend",
        version="0.1.0",
        docs_url="/docs",       # Swagger UI
        redoc_url="/redoc",     # ReDoc UI
    )

    # --- CORS ---
    # Cross-Origin Resource Sharing: allows browsers to call this API from a
    # different domain (e.g. a React frontend on localhost:3000 calling localhost:8000).
    # In production, replace allow_origins=["*"] with your actual frontend domain.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Correlation ID middleware ---
    # Every HTTP request gets a unique ID (UUID). This ID is:
    # 1. Read from the incoming X-Correlation-ID header (if the caller sent one)
    # 2. Generated fresh if the header is absent
    # 3. Bound to structlog's context — every log line for this request includes it
    # 4. Returned in the response X-Correlation-ID header
    #
    # In production, this lets you search logs for a specific request:
    #   grep "correlation_id=abc-123" /var/log/app.log
    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))

        # bind_contextvars attaches key-value pairs to structlog for this async context
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        start = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        response.headers["X-Correlation-ID"] = correlation_id
        return response

    # --- Routers ---
    app.include_router(auth_router)

    # --- Routes ---
    @app.get("/health", tags=["ops"], summary="Health check")
    async def health() -> dict:
        """
        Returns 200 if the service is up.

        Used by Docker Compose (healthcheck), Kubernetes (liveness/readiness probes),
        and load balancers to decide whether to route traffic to this instance.

        Note: this checks that the *process* is alive, not that the DB is reachable.
        A separate /ready endpoint (added later) will check DB + Redis connectivity.
        """
        return {"status": "ok", "version": "0.1.0", "environment": settings.environment}

    return app


# Module-level app instance — Uvicorn imports this.
app = create_app()
