import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, analytics, chat, connections, health, scope, users, persistence, profiles
from app.config import settings
from app.db.connection_manager import connection_manager
from app.db.insight_db import insight_db


# Root logger config — without this, every `logger.info(...)` in the app
# (including the [api-tool] URL traces and [agent] scope traces) is
# silently dropped because Python's default root level is WARNING and
# uvicorn only configures its own loggers. Override via LOG_LEVEL env.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup: initialize DataLens persistence DB
    insight_db.initialize()

    # Restore saved database connections so they survive server restarts
    await connection_manager.restore_connections()

    yield
    # Shutdown: nothing to clean up


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins if settings.cors_origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(chat.router, tags=["chat"])
app.include_router(connections.router, tags=["connections"])
app.include_router(users.router, tags=["auth"])
app.include_router(persistence.router, tags=["persistence"])
app.include_router(profiles.router, tags=["profiles"])
app.include_router(scope.router, tags=["scope"])
app.include_router(admin.router, tags=["admin"])
app.include_router(analytics.router, tags=["analytics"])
