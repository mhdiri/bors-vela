import urllib.request
import json
import os
import time
from datetime import datetime, timezone

TOKEN = os.environ.get("RV_TOKEN", "")
API = "https://rahavard365.com/api/v2"

HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0"
}

RAW_DIR = "data/raw"
SYMBOL_FILE = "data/symbols.json"

def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def get_bars(symbol_id, countback=5000):
    url = (
        API +
        "/chart/bars?countback=" + str(countback) +
        "&symbol=exchange.asset:" +
        str(symbol_id) +
        ":real_close:type0" +
        "&resolution=D"
    )

    return get_json(url)


def load_old(symbol_id):
    path = f"{RAW_DIR}/{symbol_id}.json"

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    return []


def save(symbol_id, data):
    os.makedirs(RAW_DIR, exist_ok=True)

    with open(
        f"{RAW_DIR}/{symbol_id}.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(data, f, ensure_ascii=False)


def update_symbol(name, symbol_id):

    old = load_old(symbol_id)

    new = get_bars(symbol_id)

    if "data" not in new or not new["data"]:
        print("EMPTY:", name)
        return False

    candles = new["data"]

    # حذف تکراری‌ها بر اساس زمان
    merged = {}

    for c in old:
        merged[c["time"]] = c

    for c in candles:
        merged[c["time"]] = c

    result = sorted(
        merged.values(),
        key=lambda x: x["time"]
    )

    save(symbol_id, result)

    print(
        name,
        "| old:",
        len(old),
        "| new:",
        len(result)
    )

    return True


def main():

    with open(
        SYMBOL_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        symbols = json.load(f)


    success = 0
    errors = 0

    print("======================")
    print("RAHAVARD DAILY UPDATE")
    print("TOTAL:", len(symbols))
    print("======================")


    for i, s in enumerate(symbols, 1):

        try:

            print(
                f"[{i}/{len(symbols)}]",
                s["name"],
                s["id"]
            )

            if update_symbol(
                s["name"],
                s["id"]
            ):
                success += 1

        except Exception as e:

            errors += 1
            print(
                "ERROR:",
                s["name"],
                e
            )

        time.sleep(0.5)


    print("======================")
    print("SUCCESS:", success)
    print("ERRORS:", errors)
    print("======================")


if __name__ == "__main__":
    main()
