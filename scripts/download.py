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
        headers=HEADERS,
        method="GET"
    )

    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


def main():
    print("=== STEP 2: TEST HISTORICAL DATA ===")

    with open(
        "data/symbols.json",
        "r",
        encoding="utf-8"
    ) as f:
        symbols = json.load(f)

    print("Total symbols:", len(symbols))
    print("Testing first 10 symbols...")
    print("")

    os.makedirs("data/test", exist_ok=True)

    success = 0

    for item in symbols[:10]:

        name = item["name"]
        asset_id = item["id"]

        print(
            "Testing:",
            name,
            "| ID:",
            asset_id
        )

        try:
            result = get_bars(asset_id)

            if "data" not in result or not result["data"]:
                print("  ERROR: no data")
                continue

            bars = result["data"]

            print(
                "  candles:",
                len(bars)
            )

            print(
                "  first:",
                bars[0]
            )

            print(
                "  last:",
                bars[-1]
            )

            with open(
                "data/test/" + str(asset_id) + ".json",
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
            print(
                "  ERROR:",
                str(e)
            )

        time.sleep(1)

    print("")
    print("=== TEST COMPLETE ===")
    print("Successful:", success)
    print("Test files: data/test/")


if __name__ == "__main__":
    main()
