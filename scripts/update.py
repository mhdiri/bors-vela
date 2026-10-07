import os
import json

RAW_DIR = "data/raw"

TEST_SYMBOLS = [
    "453",
    "484",
    "35",
    "253",
    "505"
]


def check_data():

    print("=== UPDATE TEST ===")

    for symbol in TEST_SYMBOLS:

        file_path = os.path.join(
            RAW_DIR,
            f"{symbol}.json"
        )

        if os.path.exists(file_path):

            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(
                symbol,
                "candles:",
                len(data)
            )

        else:
            print(
                symbol,
                "NOT FOUND"
            )

    print("===================")


if __name__ == "__main__":
    check_data()
