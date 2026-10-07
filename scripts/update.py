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


TEST_SYMBOLS = [
    {"name": "فولاد", "id": 453},
    {"name": "غچین", "id": 35},
    {"name": "فسرب", "id": 253},
    {"name": "کیسون", "id": 505},
    {"name": "فاما", "id": 147}
]


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

    req = urllib.request.Request(
        url,
        headers=HEADERS
    )

    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(
            r.read().decode("utf-8")
        )


def load_old(asset_id):

    path = f"{RAW_DIR}/{asset_id}.json"

    if not os.path.exists(path):
        return []

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


def save_data(asset_id, data):

    path = f"{RAW_DIR}/{asset_id}.json"

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False
        )


def update_symbol(symbol):

    asset_id = symbol["id"]

    print("\nUpdating:", symbol["name"])

    old = load_old(asset_id)

    print("Old candles:", len(old))


    result = get_bars(asset_id)

    if "data" not in result:
        print("No data")
        return


    new = result["data"]

    print("Downloaded:", len(new))


    old_times = set()

    for candle in old:
        old_times.add(candle["time"])


    added = 0

    for candle in new:

        if candle["time"] not in old_times:
            old.append(candle)
            added += 1


    old.sort(
        key=lambda x: x["time"]
    )


    save_data(
        asset_id,
        old
    )


    print("Added:", added)
    print("Final:", len(old))


def main():

    print("=== DAILY UPDATE TEST ===")


    for symbol in TEST_SYMBOLS:

        try:
            update_symbol(symbol)

        except Exception as e:
            print(
                "ERROR:",
                symbol["name"],
                e
            )

        time.sleep(1)


    print("\n=== FINISHED ===")


if __name__ == "__main__":
    main()
