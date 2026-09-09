from fastapi import FastAPI

from portmetrics.config import settings

app = FastAPI(title="PortMetrics", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}


@app.get("/api/health")
def api_health() -> dict[str, str]:
    return health()
