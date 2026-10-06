from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import urllib.request
import urllib.parse
import json

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

API = "https://cdn.tsetmc.com"

def fj(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/api/search/{symbol}")
def search(symbol: str):
    try:
        return fj(API + "/api/Instrument/GetInstrumentSearch/" + urllib.parse.quote(symbol, encoding='utf-8'))
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/history/{code}")
def history(code: str):
    try:
        return fj(API + "/api/ClosingPrice/GetClosingPriceDailyList/" + code + "/0")
    except Exception as e:
        return {"error": str(e)}
