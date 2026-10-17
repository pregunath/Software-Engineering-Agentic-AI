from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db, initialize_database
from app.ollama import OllamaClient
from app.inspection_api import router as inspection_router
from app.plans import router as plans_router
from app.recovery import recover_interrupted_tasks
from app.tasks import router as tasks_router
from app.workspace_api import router as workspace_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    recover_interrupted_tasks()
    yield


app = FastAPI(title="Local AI Software Engineer Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)
app.include_router(tasks_router)
app.include_router(plans_router)
app.include_router(inspection_router)
app.include_router(workspace_router)


@app.get("/health")
async def health(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    ollama = await OllamaClient(settings).health()
    return {
        "status": "ok",
        "ollama": {
            "available": ollama.available,
            "version": ollama.version,
            "detail": ollama.detail,
            "base_url": settings.ollama_base_url,
            "model": settings.ollama_model,
        },
    }


@app.get("/health/database")
def database_health(_: Session = Depends(get_db)) -> dict[str, str]:
    return {"status": "ok"}
