from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import urllib.request
import urllib.parse
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "https://cdn.tsetmc.com"

def fetch_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/api/search/{symbol}")
def search(symbol: str):
    try:
        url = API + "/api/Instrument/GetInstrumentSearch/" + urllib.parse.quote(symbol)
        return fetch_json(url)
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/history/{code}")
def history(code: str):
    try:
        url = API + "/api/ClosingPrice/GetClosingPriceDailyList/" + code + "/0"
        return fetch_json(url)
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/ratio/{s1}/{s2}")
def ratio(s1: str, s2: str):
    try:
        d1 = fetch_json(API + "/api/Instrument/GetInstrumentSearch/" + urllib.parse.quote(s1))
        d2 = fetch_json(API + "/api/Instrument/GetInstrumentSearch/" + urllib.parse.quote(s2))
        c1 = d1["instrumentSearch"][0]["insCode"]
        c2 = d2["instrumentSearch"][0]["insCode"]
        h1 = fetch_json(API + "/api/ClosingPrice/GetClosingPriceDailyList/" + c1 + "/0")
        h2 = fetch_json(API + "/api/ClosingPrice/GetClosingPriceDailyList/" + c2 + "/0")
        return {"s1": s1, "s2": s2, "c1": c1, "c2": c2,
                "h1": h1.get("closingPriceDaily", []),
                "h2": h2.get("closingPriceDaily", [])}
    except Exception as e:
        return {"error": str(e)}
