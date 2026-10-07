"""
Rahavard365 Data Update - V5
با تعدیل خودکار (بدون گپ)
"""

import urllib.request
import urllib.error
import json
import os
import time
import shutil
import sys
from datetime import datetime

API = "https://rahavard365.com/api/v2"
TOKEN = os.environ.get("RV_TOKEN", "")

HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
}

RAW_DIR = "data/raw"
BACKUP_DIR = "data/backup"
SYMBOL_FILE = "data/symbols.json"
ERROR_FILE = "data/update_errors.json"
REPORT_FILE = "data/update_report.json"
STATUS_FILE = "data/symbol_status.json"
LOCK_FILE = "data/.update.lock"

TEST_MODE = True
TEST_SYMBOLS = ["فولاد", "غچین", "فسرب", "کیسون", "فاما"]

MAX_RETRY = 4
REQUEST_TIMEOUT = 60
SLEEP_BETWEEN = 1.0
SLEEP_RETRY = 3.0

MIN_CANDLES = 10
SUSPICIOUS_RATIO = 0.5
MAX_DATA_AGE_HOURS = 6

# ===== تعدیل =====
ADJUST_GAPS = True
THRESHOLD_HIGH = 1.4
THRESHOLD_LOW = 0.7


def acquire_lock():
    os.makedirs("data", exist_ok=True)
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                info = json.load(f)
            lock_time = datetime.fromisoformat(info.get("time", ""))
            age = (datetime.now() - lock_time).total_seconds() / 3600
            if age < MAX_DATA_AGE_HOURS:
                print("LOCK exists. Another update running.")
                sys.exit(1)
            else:
                os.remove(LOCK_FILE)
        except Exception:
            os.remove(LOCK_FILE)
    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        json.dump({"time": datetime.now().isoformat(), "pid": os.getpid()}, f)


def release_lock():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)


def request_json(url):
    last = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 401:
                raise Exception("TOKEN_EXPIRED: 401")
            if e.code == 404:
                raise Exception("SYMBOL_NOT_FOUND: 404")
            if e.code == 422:
                raise Exception("BAD_PARAMS: 422")
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(SLEEP_RETRY * attempt)
                continue
            raise Exception("HTTP_ERROR: " + str(e.code))
        except Exception as e:
            last = e
            time.sleep(SLEEP_RETRY * attempt)
    raise Exception("MAX_RETRY: " + str(last)[:100])


def get_bars(asset_id):
    url = (API + "/chart/bars?countback=5000"
           + "&symbol=exchange.asset:" + str(asset_id) + ":real_close:type0"
           + "&resolution=D"
           + "&from=2000-01-01T00:00:00Z"
           + "&to=2030-01-01T00:00:00Z")
    return request_json(url)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else []


def save_safe(path, data):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    with open(temp, "r", encoding="utf-8") as f:
        json.load(f)
    os.replace(temp, path)


def backup_file(path):
    if not os.path.exists(path):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(BACKUP_DIR, os.path.basename(path) + "." + stamp + ".bak")
    shutil.copy2(path, backup)
    return backup


def rollback(path, backup):
    if backup and os.path.exists(backup):
        shutil.copy2(backup, path)


def validate_candle(c):
    if not isinstance(c, dict):
        return False
    if "time" not in c:
        return False
    if not isinstance(c["time"], (int, float)):
        return False
    close = c.get("close")
    if close is None:
        return False
    try:
        if float(close) <= 0:
            return False
    except Exception:
        return False
    return True


def validate_data(data):
    if not data or not isinstance(data, list):
        return False
    if len(data) < MIN_CANDLES:
        return False
    for c in data:
        if not validate_candle(c):
            return False
    return True


def clean_data(data):
    seen = set()
    out = []
    for c in data:
        t = c.get("time")
        if t in seen:
            continue
        seen.add(t)
        out.append(c)
    out.sort(key=lambda x: x["time"])
    return out


def find_gaps(bars):
    gaps = []
    for i in range(1, len(bars)):
        p = bars[i-1].get("close", 0)
        c = bars[i].get("close", 0)
        if p and c and p > 0 and c > 0:
            r = c / p
            if r > THRESHOLD_HIGH or r < THRESHOLD_LOW:
                gaps.append({"idx": i, "ratio": r})
    return gaps


def adjust_bars(bars):
    adjusted = [dict(b) for b in bars]
    gaps = find_gaps(adjusted)
    for gap in reversed(gaps):
        idx = gap["idx"]
        r = gap["ratio"]
        for j in range(idx):
            for key in ["open", "high", "low", "close"]:
                v = adjusted[j].get(key)
                if v is not None:
                    adjusted[j][key] = round(v * r, 6)
    return adjusted


def update_symbol(symbol):
    asset_id = symbol["id"]
    name = symbol["name"]
    path = os.path.join(RAW_DIR, str(asset_id) + ".json")

    old = load_json(path, default=[])
    old_count = len(old)

    result = get_bars(asset_id)
    if "data" not in result:
        raise Exception("NO_DATA")

    new_raw = result["data"]

    if not validate_data(new_raw):
        raise Exception("INVALID_DATA: " + str(len(new_raw)))

    new_raw = clean_data(new_raw)

    if old_count > 0 and len(new_raw) < old_count * SUSPICIOUS_RATIO:
        raise Exception("SUSPICIOUS_REDUCTION")

    # ★★★ تعدیل خودکار ★★★
    if ADJUST_GAPS:
        new_raw = adjust_bars(new_raw)
        # وقتی تعدیل روشنه، کل داده از نو جایگزین می‌شه
        merged = list(new_raw)
        added = len(new_raw)
    else:
        old_times = set()
        for c in old:
            if "time" in c:
                old_times.add(c["time"])
        added = 0
        merged = list(old)
        for candle in new_raw:
            if candle["time"] not in old_times:
                merged.append(candle)
                old_times.add(candle["time"])
                added += 1

    merged = clean_data(merged)

    backup = backup_file(path) if old_count > 0 else None

    try:
        save_safe(path, merged)
    except Exception as e:
        rollback(path, backup)
        raise Exception("SAVE_FAILED: " + str(e))

    final = load_json(path, default=[])
    if len(final) != len(merged):
        rollback(path, backup)
        raise Exception("VERIFY_FAILED")

    gaps_final = len(find_gaps(merged)) if ADJUST_GAPS else -1

    return {
        "name": name,
        "id": asset_id,
        "old": old_count,
        "downloaded": len(new_raw),
        "added": added,
        "final": len(merged),
        "gaps": gaps_final
    }


def main():
    start = datetime.now()
    print("=" * 60)
    print("RAHAVARD UPDATE V5 - with Adjust")
    print("=" * 60)
    print("Test mode: " + str(TEST_MODE))
    print("Adjust gaps: " + str(ADJUST_GAPS))
    print("")

    acquire_lock()
    try:
        os.makedirs(RAW_DIR, exist_ok=True)
        os.makedirs(BACKUP_DIR, exist_ok=True)

        symbols = load_json(SYMBOL_FILE, default=[])
        if not symbols:
            print("symbols.json empty")
            return

        if TEST_MODE:
            symbols = [s for s in symbols if s["name"] in TEST_SYMBOLS]
            print("TEST MODE: " + str(len(symbols)))
        else:
            print("FULL MODE: " + str(len(symbols)))

        print("")

        errors = []
        results = []
        total_added = 0
        success = 0

        for i, symbol in enumerate(symbols, start=1):
            print("[" + str(i) + "/" + str(len(symbols)) + "] " + symbol["name"])
            try:
                r = update_symbol(symbol)
                print("     Downloaded: " + str(r["downloaded"]))
                print("     Added:      " + str(r["added"]))
                print("     Final:      " + str(r["final"]))
                if r["gaps"] >= 0:
                    print("     Gaps:       " + str(r["gaps"]))
                print("     Status:     OK")
                total_added += r["added"]
                success += 1
                results.append(r)
            except Exception as e:
                print("     Status:     ERROR")
                print("     Reason:     " + str(e)[:120])
                errors.append({
                    "name": symbol["name"],
                    "id": symbol["id"],
                    "error": str(e),
                    "time": datetime.now().isoformat()
                })
            time.sleep(SLEEP_BETWEEN)

        save_safe(ERROR_FILE, errors)

        status = load_json(STATUS_FILE, default={})
        if not isinstance(status, dict):
            status = {}
        now = datetime.now().isoformat()
        for r in results:
            status[str(r["id"])] = {
                "name": r["name"],
                "last_update": now,
                "candles": r["final"],
                "status": "ok"
            }
        for e in errors:
            status[str(e["id"])] = {
                "name": e["name"],
                "last_update": now,
                "status": "error",
                "error": e["error"]
            }
        save_safe(STATUS_FILE, status)

        report = {
            "start_time": start.isoformat(),
            "end_time": datetime.now().isoformat(),
            "duration_seconds": round((datetime.now() - start).total_seconds(), 2),
            "total_symbols": len(symbols),
            "success": success,
            "errors": len(errors),
            "new_candles": total_added,
            "test_mode": TEST_MODE
        }
        save_safe(REPORT_FILE, report)

        print("")
        print("=" * 60)
        print("SUCCESS:     " + str(success))
        print("ERRORS:      " + str(len(errors)))
        print("NEW CANDLES: " + str(total_added))
        print("DURATION:    " + str(report["duration_seconds"]) + "s")
        print("=" * 60)

    finally:
        release_lock()


if __name__ == "__main__":
    main()
