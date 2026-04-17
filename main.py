from fastapi import FastAPI
from bot.webhook import router as webhook_router
from database import init_db

app = FastAPI(title="Moodi")

# אתחול DB בהפעלה
@app.on_event("startup")
async def startup():
    init_db()
    print("Moodi is running 🚀")

# חיבור ה-webhook router
app.include_router(webhook_router)

@app.get("/")
async def root():
    return {"status": "Moodi is alive"}