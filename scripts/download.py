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

    print("=== RAHAVARD FULL DOWNLOAD ===")

    with open(
        "data/symbols.json",
        "r",
        encoding="utf-8"
    ) as f:
        symbols = json.load(f)


    print("Total symbols:", len(symbols))


    os.makedirs(
        "data/raw",
        exist_ok=True
    )


    errors = []
    success = 0


    for index, s in enumerate(symbols, start=1):

        name = s["name"]
        asset_id = s["id"]

        print(
            f"[{index}/{len(symbols)}] {name} ({asset_id})"
        )

        try:

            result = get_bars(asset_id)


            if "data" not in result or not result["data"]:

                print("  NO DATA")

                errors.append({
                    "name": name,
                    "id": asset_id,
                    "error": "no data"
                })

                continue


            bars = result["data"]


            with open(
                f"data/raw/{asset_id}.json",
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    bars,
                    f,
                    ensure_ascii=False
                )


            success += 1

            print(
                "  candles:",
                len(bars)
            )


        except Exception as e:

            print(
                "  ERROR:",
                e
            )

            errors.append({
                "name": name,
                "id": asset_id,
                "error": str(e)
            })


        time.sleep(1)



    with open(
        "data/errors.json",
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            errors,
            f,
            ensure_ascii=False,
            indent=2
        )


    print("")
    print("======================")
    print("SUCCESS:", success)
    print("ERRORS:", len(errors))
    print("======================")


if __name__ == "__main__":
    main()
