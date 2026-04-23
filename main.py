from fastapi import FastAPI
from bot.webhook import router as webhook_router
from database import init_db
from notifications.scheduler import start_scheduler, stop_scheduler

app = FastAPI(title="Moodi")


@app.on_event("startup")
async def startup():
    init_db()
    start_scheduler()
    print("Moodi is running 🚀")


@app.on_event("shutdown")
async def shutdown():
    stop_scheduler()


app.include_router(webhook_router)


@app.get("/")
async def root():
    return {"status": "Moodi is alive"}
