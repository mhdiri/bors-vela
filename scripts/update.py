import os
import json
import urllib.request

TOKEN = os.environ.get("RV_TOKEN", "")

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


def load_old(symbol_id):

    path = f"{RAW_DIR}/{symbol_id}.json"

    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_last_time(data):

    if len(data) == 0:
        return 0

    return data[-1]["time"]


def update_symbol(item):

    old = load_old(item["id"])

    last_time = get_last_time(old)

    print("\nSymbol:", item["name"])
    print("Old candles:", len(old))
    print("Last time:", last_time)

    # مرحله بعد:
    # درخواست API جدید اینجا اضافه می‌شود


def main():

    print("=== UPDATE START ===")

    for item in TEST_SYMBOLS:
        update_symbol(item)

    print("\n=== UPDATE FINISHED ===")


if __name__ == "__main__":
    main()
