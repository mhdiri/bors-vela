import urllib.request
import json
import os
import time


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


def request_json(url, retry=3):

    for attempt in range(retry):

        try:

            req = urllib.request.Request(
                url,
                headers=HEADERS
            )

            with urllib.request.urlopen(
                req,
                timeout=60
            ) as r:

                return json.loads(
                    r.read().decode("utf-8")
                )


        except Exception as e:

            if attempt == retry - 1:
                raise e

            time.sleep(3)



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

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)



def save_safe(path, data):

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


    old_times = set()

    for c in old:
        old_times.add(c["time"])


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
        "old": len(old)-added,
        "downloaded": len(new),
        "added": added,
        "final": len(old)
    }



def main():


    print("=== DAILY UPDATE START ===")


    symbols = load_json(
        SYMBOL_FILE
    )


    errors = []

    success = 0

    total_added = 0


    print(
        "TOTAL SYMBOLS:",
        len(symbols)
    )


    for index, symbol in enumerate(
        symbols,
        start=1
    ):


        try:

            print(
                f"\n[{index}/{len(symbols)}]",
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
                    "error": str(e)
                }
            )


        time.sleep(1)



    save_safe(
        ERROR_FILE,
        errors
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
