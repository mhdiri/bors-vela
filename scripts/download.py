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


def main():

    print("=== RAHAVARD DATA TEST ===")

    with open(
        "data/symbols.json",
        "r",
        encoding="utf-8"
    ) as f:
        symbols = json.load(f)

    print("Total symbols:", len(symbols))

    os.makedirs("data/test", exist_ok=True)

    success = 0

    # فعلا فقط 10 نماد اول برای تست
    for s in symbols[:10]:

        name = s["name"]
        asset_id = s["id"]

        print("")
        print("Downloading:", name, asset_id)

        try:

            result = get_bars(asset_id)

            if "data" not in result:
                print("NO DATA")
                continue

            bars = result["data"]

            print("Candles:", len(bars))

            with open(
                f"data/test/{asset_id}.json",
                "w",
                encoding="utf-8"
            ) as f:
                json.dump(
                    bars,
                    f,
                    ensure_ascii=False
                )

            success += 1

        except Exception as e:
            print("ERROR:", e)

        time.sleep(1)


    print("")
    print("====================")
    print("Successful:", success)
    print("====================")


if __name__ == "__main__":
    main()
