from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from oxtapus import Rahavard365
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

USER = os.environ.get("RV_USER", "")
PASS = os.environ.get("RV_PASS", "")

client = Rahavard365(username=USER, password=PASS)

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/api/history/{symbol}")
def history(symbol: str):
    try:
        # دریافت داده تاریخی از رهاورد ۳۶۵
        data = client.get_history(symbol=symbol)
        return {"symbol": symbol, "data": data}
    except Exception as e:
        return {"error": str(e)}
