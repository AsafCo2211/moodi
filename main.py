import warnings
import logging
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from bot.webhook import router as webhook_router
from auth.webview import router as auth_router
from auth.dashboard import router as dashboard_router
from database import init_db
from notifications.scheduler import start_scheduler, stop_scheduler
from utils.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(title="Moodi")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup():
    init_db()
    start_scheduler()
    logger.info("Moodi is running 🚀")


@app.on_event("shutdown")
async def shutdown():
    stop_scheduler()


app.include_router(webhook_router)
app.include_router(auth_router)
app.include_router(dashboard_router)


@app.get("/")
async def root():
    return {"status": "Moodi is alive"}
