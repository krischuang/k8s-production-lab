import os
import time

from fastapi import FastAPI, HTTPException, Response

app = FastAPI(title="inventory-api")

START_TIME = time.time()

# Toggled via env var to simulate a broken deployment (see scripts/simulate-bad-release.sh)
FAIL_READINESS = os.getenv("FAIL_READINESS", "false").lower() == "true"

# Minimum uptime before the pod reports ready, mirrors a real warm-up/DB-connect delay
READINESS_DELAY_SECONDS = int(os.getenv("READINESS_DELAY_SECONDS", "5"))

DATABASE_URL = os.getenv("DATABASE_URL", "")
APP_ENV = os.getenv("APP_ENV", "development")

ITEMS = [
    {"id": 1, "name": "widget", "quantity": 42},
    {"id": 2, "name": "gadget", "quantity": 17},
    {"id": 3, "name": "sprocket", "quantity": 8},
]


@app.get("/health/live")
def liveness() -> dict:
    """Process is up and able to serve requests at all. Kubernetes restarts the
    pod if this fails, so it must not depend on external services."""
    return {"status": "alive"}


@app.get("/health/ready")
def readiness(response: Response) -> dict:
    """Pod is ready to receive traffic. Depends on warm-up and, in a real
    deployment, DB connectivity. Kubernetes removes the pod from Service
    endpoints (but does not restart it) while this fails."""
    if FAIL_READINESS:
        response.status_code = 503
        raise HTTPException(status_code=503, detail="readiness check failed")

    uptime = time.time() - START_TIME
    if uptime < READINESS_DELAY_SECONDS:
        response.status_code = 503
        raise HTTPException(status_code=503, detail="warming up")

    return {"status": "ready", "env": APP_ENV, "uptime_seconds": round(uptime, 2)}


@app.get("/api/items")
def list_items() -> dict:
    return {"items": ITEMS, "count": len(ITEMS)}


@app.get("/")
def root() -> dict:
    return {"service": "inventory-api", "env": APP_ENV}
