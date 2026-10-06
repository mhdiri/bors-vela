import urllib.request
import urllib.parse
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

SYMBOLS = ["خساپا", "خودرو", "فولاد", "شپنا", "شبندر"]

def fj(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))

def search(name):
    url = API + "/search?keyword=" + urllib.parse.quote(name)
    return fj(url)

def get_bars(symbol_id):
    url = API + "/chart/bars?countback=5000&symbol=exchange.asset:" + str(symbol_id) + ":real_close:type0&resolution=D&from=2015-01-01T00:00:00Z&to=2030-01-01T00:00:00Z"
    return fj(url)

def main():
    os.makedirs("data", exist_ok=True)
    symbols_out = []
    for name in SYMBOLS:
        print(f"جستجوی {name}...")
        try:
            res = search(name)
            if not res or "data" not in res:
                print(f"  یافت نشد")
                continue
            items = res["data"] if isinstance(res["data"], list) else [res["data"]]
            for item in items[:3]:
                if item.get("symbol") == name or item.get("name") == name:
                    sid = item.get("id")
                    if not sid: continue
                    print(f"  ID: {sid}")
                    bars = get_bars(sid)
                    if "data" in bars:
                        bars_list = bars["data"]
                        print(f"  {len(bars_list)} کندل")
                        with open(f"data/{name}.json", "w", encoding="utf-8") as f:
                            json.dump(bars_list, f, ensure_ascii=False)
                        symbols_out.append({"name": name, "file": f"data/{name}.json"})
                    break
        except Exception as e:
            print(f"  خطا: {e}")
        time.sleep(1)
    
    with open("data/symbols.json", "w", encoding="utf-8") as f:
        json.dump(symbols_out, f, ensure_ascii=False)
    print("تمام!")

if __name__ == "__main__":
    main()
