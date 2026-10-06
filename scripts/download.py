import urllib.request
import json
import os
import time

TOKEN = os.environ.get("RV_TOKEN", "")
API = "https://rahavard365.com/api/v2"

HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
}

# IDهای مستقیم نمادها
SYMBOLS = [
    {"name": "خساپا", "id": 172},
    {"name": "خودرو", "id": 167},
    {"name": "فولاد", "id": 453},
    {"name": "شپنا", "id": 484},
]

def fj(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))

def get_bars(symbol_id):
    url = (API + "/chart/bars?countback=5000"
           "&symbol=exchange.asset:" + str(symbol_id) + ":real_close:type0"
           "&resolution=D"
           "&from=2000-01-01T00:00:00Z"
           "&to=2030-01-01T00:00:00Z")
    return fj(url)

def main():
    os.makedirs("data", exist_ok=True)
    symbols_out = []
    for s in SYMBOLS:
        name = s["name"]
        sid = s["id"]
        print(f"→ {name} (ID: {sid})")
        try:
            res = get_bars(sid)
            if "data" in res and res["data"]:
                bars = res["data"]
                print(f"  ✓ {len(bars)} کندل")
                with open(f"data/{sid}.json", "w", encoding="utf-8") as f:
                    json.dump(bars, f, ensure_ascii=False)
                symbols_out.append({"name": name, "file": f"data/{sid}.json", "id": sid})
            else:
                print(f"  ✗ داده خالی")
                print(f"  کلیدها: {list(res.keys())}")
        except Exception as e:
            print(f"  ✗ خطا: {e}")
        time.sleep(1)
    
    with open("data/symbols.json", "w", encoding="utf-8") as f:
        json.dump(symbols_out, f, ensure_ascii=False, indent=2)
    print("تمام!")

if __name__ == "__main__":
    main()
