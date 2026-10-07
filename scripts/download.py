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

SYMBOLS = [
    {"name": "خساپا", "id": 172},
    {"name": "خودرو", "id": 167},
    {"name": "فولاد", "id": 453},
    {"name": "شپنا", "id": 484},
]

PRICE_TYPES = ["adjusted", "adjusted_close", "real_adjusted", "real_close"]

def fj(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))

def get_bars(symbol_id, price_type):
    url = (API + "/chart/bars?countback=5000"
           "&symbol=exchange.asset:" + str(symbol_id) + ":" + price_type + ":type0"
           "&resolution=D"
           "&from=2000-01-01T00:00:00Z"
           "&to=2030-01-01T00:00:00Z")
    return fj(url)

def count_gaps(bars):
    n = 0
    for i in range(1, len(bars)):
        p = bars[i-1].get('close', 0)
        c = bars[i].get('close', 0)
        if p > 0 and c > 0:
            r = c / p
            if r > 1.3 or r < 0.7:
                n += 1
    return n

def main():
    os.makedirs("data", exist_ok=True)

    print("=== STEP 1: TEST PRICE TYPES ===")
    best_type = None
    best_gaps = 999999
    for pt in PRICE_TYPES:
        try:
            print("Testing: " + pt + "...")
            res = get_bars(SYMBOLS[0]["id"], pt)
            if "data" in res and res["data"]:
                bars = res["data"]
                gaps = count_gaps(bars)
                print("  bars: " + str(len(bars)) + " | gaps: " + str(gaps))
                if gaps < best_gaps:
                    best_gaps = gaps
                    best_type = pt
                if gaps == 0:
                    print("  >>> FOUND PERFECT: " + pt)
                    break
            else:
                print("  empty")
        except Exception as e:
            print("  error: " + str(e))

    if not best_type:
        print("ERROR: no price type worked")
        return

    print("")
    print("=== STEP 2: DOWNLOAD WITH " + best_type + " ===")

    symbols_out = []
    for s in SYMBOLS:
        name = s["name"]
        sid = s["id"]
        print("Downloading: " + name + " (ID: " + str(sid) + ")")
        try:
            res = get_bars(sid, best_type)
            if "data" in res and res["data"]:
                bars = res["data"]
                gaps = count_gaps(bars)
                print("  bars: " + str(len(bars)) + " | gaps: " + str(gaps))
                with open("data/" + str(sid) + ".json", "w", encoding="utf-8") as f:
                    json.dump(bars, f, ensure_ascii=False)
                symbols_out.append({"name": name, "file": "data/" + str(sid) + ".json", "id": sid})
            else:
                print("  empty")
        except Exception as e:
            print("  error: " + str(e))
        time.sleep(1)

    with open("data/symbols.json", "w", encoding="utf-8") as f:
        json.dump(symbols_out, f, ensure_ascii=False, indent=2)

    print("")
    print("=== DONE ===")
    print("Price type used: " + best_type)

if __name__ == "__main__":
    main()
