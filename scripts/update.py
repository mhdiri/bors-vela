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

    path = os.path.join(
        RAW_DIR,
        symbol_id + ".json"
    )

    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(symbol_id, data):

    path = os.path.join(
        RAW_DIR,
        symbol_id + ".json"
    )

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


def get_last_time(data):

    if not data:
        return 0

    return data[-1]["time"]


def update_symbol(item):

    symbol_id = item["id"]

    old = load_old(symbol_id)

    last_time = get_last_time(old)

    print("\nUpdating", item["name"])
    print("Old:", len(old))
    print("Last time:", last_time)

    # مرحله اتصال API جدید اینجا قرار می‌گیرد
    # فعلاً فقط تست تشخیص آخرین کندل

    return True


def main():

    print("=== UPDATE START ===")

    for item in TEST_SYMBOLS:
        update_symbol(item)

    print("\n=== UPDATE FINISHED ===")


if __name__ == "__main__":
    main()
