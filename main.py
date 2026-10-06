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

def fetch_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/api/test")
def test():
    try:
        d = fetch_json("https://api.codebazan.ir/bours/?type=تاریخی&symbol=" + urllib.parse.quote("شیراز"))
        return {"ok": True, "sample": str(d)[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/search/{symbol}")
def search(symbol: str):
    try:
        return fetch_json("https://api.codebazan.ir/bours/?type=تاریخی&symbol=" + urllib.parse.quote(symbol))
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/ratio/{s1}/{s2}")
def ratio(s1: str, s2: str):
    try:
        d1 = fetch_json("https://api.codebazan.ir/bours/?type=تاریخی&symbol=" + urllib.parse.quote(s1))
        d2 = fetch_json("https://api.codebazan.ir/bours/?type=تاریخی&symbol=" + urllib.parse.quote(s2))
        return {"s1": s1, "s2": s2, "d1": d1, "d2": d2}
    except Exception as e:
        return {"error": str(e)}
