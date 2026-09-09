import asyncio
import os
import time

import asyncpg
from fastapi import FastAPI, HTTPException, Response

app = FastAPI(title="inventory-api")

START_TIME = time.time()

# Toggled via env var to simulate a broken deployment (see scripts/simulate-bad-release.sh)
FAIL_READINESS = os.getenv("FAIL_READINESS", "false").lower() == "true"

# Minimum uptime before the pod reports ready, mirrors a real warm-up delay
READINESS_DELAY_SECONDS = int(os.getenv("READINESS_DELAY_SECONDS", "5"))

DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_CONNECT_TIMEOUT_SECONDS = float(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "2"))
APP_ENV = os.getenv("APP_ENV", "development")
APP_VERSION = os.getenv("APP_VERSION", "dev")

# Populated via the Downward API (see k8s/deployment.yaml) rather than the app
# querying the Kubernetes API to discover its own identity -- the pod already
# knows this about itself, so asking the API server for it would just be an
# unnecessary RBAC surface.
POD_NAME = os.getenv("POD_NAME", "unknown")
NODE_NAME = os.getenv("NODE_NAME", "unknown")
POD_NAMESPACE = os.getenv("POD_NAMESPACE", "unknown")

ITEMS = [
    {"id": 1, "name": "widget", "quantity": 42},
    {"id": 2, "name": "gadget", "quantity": 17},
    {"id": 3, "name": "sprocket", "quantity": 8},
]


async def check_database() -> bool:
    """Empty DATABASE_URL means no DB is configured (unit tests, local dev
    without Postgres) so the check is a no-op rather than a failure."""
    if not DATABASE_URL:
        return True
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(DATABASE_URL), timeout=DB_CONNECT_TIMEOUT_SECONDS
        )
        await conn.close()
        return True
    except Exception:
        return False


@app.get("/health/live")
def liveness() -> dict:
    """Process is up and able to serve requests at all. Kubernetes restarts the
    pod if this fails, so it must not depend on external services."""
    return {"status": "alive"}


@app.get("/health/ready")
async def readiness(response: Response) -> dict:
    """Pod is ready to receive traffic. Depends on warm-up and database
    connectivity. Kubernetes removes the pod from Service endpoints (but does
    not restart it) while this fails."""
    if FAIL_READINESS:
        response.status_code = 503
        raise HTTPException(status_code=503, detail="readiness check failed")

    uptime = time.time() - START_TIME
    if uptime < READINESS_DELAY_SECONDS:
        response.status_code = 503
        raise HTTPException(status_code=503, detail="warming up")

    if not await check_database():
        response.status_code = 503
        raise HTTPException(status_code=503, detail="database unavailable")

    return {"status": "ready", "env": APP_ENV, "uptime_seconds": round(uptime, 2)}


@app.get("/api/items")
def list_items() -> dict:
    return {"items": ITEMS, "count": len(ITEMS)}


@app.get("/api/whoami")
def whoami() -> dict:
    """Identifies which pod actually handled this request. Used by the demo
    dashboard's "Send Request" button to make Service load balancing across
    replicas visible instead of just asserted."""
    return {
        "pod": POD_NAME,
        "node": NODE_NAME,
        "namespace": POD_NAMESPACE,
        "version": APP_VERSION,
    }


@app.get("/")
def root() -> dict:
    return {"service": "inventory-api", "env": APP_ENV}
