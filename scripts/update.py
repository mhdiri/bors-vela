import urllib.request
import json
import os
import time
from datetime import datetime


API = "https://rahavard365.com/api/v2"

TOKEN = os.environ.get("RV_TOKEN", "")

HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0"
}


RAW_DIR = "data/raw"

SYMBOL_FILE = "data/symbols.json"

ERROR_FILE = "data/update_errors.json"

REPORT_FILE = "data/update_report.json"


# فقط برای تست اولیه
# بعد از موفقیت تغییر بده به False
TEST_MODE = True


TEST_SYMBOLS = [
    "فولاد",
    "غچین",
    "فسرب",
    "کیسون",
    "فاما"
]


MAX_RETRY = 3

REQUEST_TIMEOUT = 60

SLEEP_TIME = 1



def request_json(url):

    last_error = None

    for attempt in range(1, MAX_RETRY + 1):

        try:

            req = urllib.request.Request(
                url,
                headers=HEADERS
            )

            with urllib.request.urlopen(
                req,
                timeout=REQUEST_TIMEOUT
            ) as r:

                return json.loads(
                    r.read().decode("utf-8")
                )


        except Exception as e:

            last_error = e

            if attempt < MAX_RETRY:
                time.sleep(attempt * 3)


    raise last_error



def get_bars(asset_id):

    url = (
        API
        + "/chart/bars?countback=5000"
        + "&symbol=exchange.asset:"
        + str(asset_id)
        + ":real_close:type0"
        + "&resolution=D"
        + "&from=2000-01-01T00:00:00Z"
        + "&to=2030-01-01T00:00:00Z"
    )

    return request_json(url)



def load_json(path):

    if not os.path.exists(path):

        return []


    try:

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)


    except Exception:

        return []



def save_safe(path, data):

    folder = os.path.dirname(path)

    if folder:

        os.makedirs(
            folder,
            exist_ok=True
        )


    temp = path + ".tmp"


    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False
        )


    os.replace(
        temp,
        path
    )



def validate_candle(c):

    required = [
        "time"
    ]

    for r in required:

        if r not in c:

            return False


    return True



def validate_data(data):

    if not data:

        return False


    for c in data:

        if not validate_candle(c):

            return False


    return True



def update_symbol(symbol):

    asset_id = symbol["id"]

    name = symbol["name"]


    path = f"{RAW_DIR}/{asset_id}.json"


    old = load_json(path)


    result = get_bars(asset_id)


    if "data" not in result:

        raise Exception(
            "No data"
        )


    new = result["data"]


    if not validate_data(new):

        raise Exception(
            "Invalid candle data"
        )


    if old and len(new) < len(old) * 0.5:

        raise Exception(
            "Suspicious data reduction"
        )



    old_times = set()


    for c in old:

        if "time" in c:

            old_times.add(
                c["time"]
            )



    added = 0



    for candle in new:

        if candle["time"] not in old_times:

            old.append(candle)

            added += 1



    old.sort(
        key=lambda x: x["time"]
    )



    save_safe(
        path,
        old
    )



    return {

        "name": name,

        "id": asset_id,

        "old": len(old) - added,

        "downloaded": len(new),

        "added": added,

        "final": len(old)

    }



def main():

    start = time.time()


    print(
        "=== DAILY UPDATE START ==="
    )


    symbols = load_json(
        SYMBOL_FILE
    )


    if TEST_MODE:

        symbols = [

            s for s in symbols

            if s["name"] in TEST_SYMBOLS

        ]


        print(
            "TEST MODE:",
            len(symbols),
            "symbols"
        )



    errors = []

    success = 0

    total_added = 0



    print(
        "TOTAL:",
        len(symbols)
    )



    for index, symbol in enumerate(
        symbols,
        start=1
    ):


        try:


            print(
                f"[{index}/{len(symbols)}]",
                symbol["name"]
            )



            result = update_symbol(
                symbol
            )


            print(
                "Added:",
                result["added"]
            )


            total_added += result["added"]

            success += 1



        except Exception as e:


            print(
                "ERROR:",
                symbol["name"],
                e
            )


            errors.append(

                {

                    "name": symbol["name"],

                    "id": symbol["id"],

                    "error": str(e),

                    "time": datetime.now().isoformat()

                }

            )



        time.sleep(
            SLEEP_TIME
        )



    save_safe(
        ERROR_FILE,
        errors
    )



    report = {

        "time": datetime.now().isoformat(),

        "symbols": len(symbols),

        "success": success,

        "errors": len(errors),

        "new_candles": total_added,

        "duration_seconds": round(
            time.time() - start,
            2
        )

    }



    save_safe(
        REPORT_FILE,
        report
    )



    print("")

    print("======================")

    print(
        "SUCCESS:",
        success
    )

    print(
        "ERRORS:",
        len(errors)
    )

    print(
        "NEW CANDLES:",
        total_added
    )

    print("======================")



if __name__ == "__main__":

    main()
