import os
import json
import urllib.request

TOKEN = os.environ.get("RV_TOKEN", "")

API = "https://rahavard365.com/api/v2"

HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0"
}

RAW_DIR = "data/raw"

TEST_SYMBOLS = [
    {"name": "فولاد", "id": "453"},
    {"name": "غچین", "id": "35"},
    {"name": "فسرب", "id": "253"},
    {"name": "کیسون", "id": "505"}
]


def get_json(url):

    req = urllib.request.Request(
        url,
        headers=HEADERS
    )

    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(
            r.read().decode("utf-8")
        )


def load_old(symbol_id):

    path = f"{RAW_DIR}/{symbol_id}.json"

    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_last_time(data):

    if not data:
        return 0

    return data[-1]["time"]


def update_symbol(item):

    old = load_old(item["id"])

    last_time = get_last_time(old)

    print("\nSymbol:", item["name"])
    print("Old candles:", len(old))
    print("Last time:", last_time)

    # درخواست تست API
    url = f"{API}/market-data/stocks/{item['id']}/history"

    try:

        new_data = get_json(url)

        print("API response received")

        if isinstance(new_data, dict):
            print("Keys:", list(new_data.keys()))

        else:
            print("Records:", len(new_data))


    except Exception as e:

        print("API ERROR:", e)


def main():

    print("=== UPDATE API TEST ===")

    for item in TEST_SYMBOLS:
        update_symbol(item)

    print("\n=== FINISHED ===")


if __name__ == "__main__":
    main()
