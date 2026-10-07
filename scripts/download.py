import urllib.request
import json
import os

API = "https://rahavard365.com/api/v2"

TOKEN = os.environ.get("RV_TOKEN", "")

HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0"
}


def get_stocks():
    url = API + "/market-data/stocks?last_trade=last_trading_day"

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
    print("=== GET RAHAVARD STOCK LIST ===")

    result = get_stocks()

    if "data" not in result:
        print("ERROR: data not found")
        print(result)
        return

    stocks = result["data"]

    print("Total records:", len(stocks))

    symbols = []

    for item in stocks:
        name = item.get("name")
        asset_id = item.get("asset_id")

        if not name or not asset_id:
            continue

        symbols.append({
            "name": name,
            "id": int(asset_id)
        })

    os.makedirs("data", exist_ok=True)

    with open(
        "data/symbols.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            symbols,
            f,
            ensure_ascii=False,
            indent=2
        )

    print("Saved symbols:", len(symbols))
    print("File: data/symbols.json")


if __name__ == "__main__":
    main()
