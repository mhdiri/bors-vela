"""
RAHAVARD365 CHART DATA SYNC ENGINE — V7.0 PRODUCTION

Architecture
------------
Rahavard365 API -> incremental sync -> data/raw/*.json (RAW SOURCE OF TRUTH)
                                      -> chart layer handles future adjustment separately

Rules
-----
1. RAW files are never adjusted by this script.
2. Existing symbols use incremental synchronization only.
3. A symbol with no RAW file gets an initial historical backfill, paginated as needed.
4. Recent overlap is intentionally downloaded so provider corrections can be captured.
5. One bad API candle is skipped; it never destroys healthy history.
6. Existing RAW data is not rejected for vendor-specific OHLC quirks.
7. Atomic write + transient rollback + read-back validation are used for every change.
8. A lock prevents concurrent runs from changing the same dataset.
9. Retries/backoff handle timeout, connection, rate-limit and 5xx failures.
10. 401/403/404/422 fail clearly without wasting retries.
11. Reports and per-symbol status are written atomically.
12. TEST_MODE=True updates only the five verification symbols.
13. TEST_MODE=False updates every symbol in data/symbols.json.

Important
---------
This script does NOT perform price-gap adjustment.
Adjustment belongs to the chart/display layer so it can change without
downloading or rewriting all RAW histories.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import socket
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# ============================================================
# CONFIG
# ============================================================
API = "https://rahavard365.com/api/v2"
TOKEN = os.environ.get("RV_TOKEN", "").strip()

HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    ),
}

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"
SYMBOL_FILE = DATA_DIR / "symbols.json"
ERROR_FILE = DATA_DIR / "update_errors.json"
REPORT_FILE = DATA_DIR / "update_report.json"
STATUS_FILE = DATA_DIR / "symbol_status.json"
LOCK_FILE = DATA_DIR / ".update.lock"

ROLLBACK_DIR = Path(tempfile.gettempdir()) / "bors_vela_rollback"


# ============================================================
# PRODUCTION MODE
# ============================================================
# IMPORTANT:
# False = ALL symbols in data/symbols.json
# True  = ONLY the five verification symbols
TEST_MODE = False

TEST_SYMBOLS = {"فولاد", "غچین", "فسرب", "کیسون", "فاما"}


# ============================================================
# INITIAL HISTORY
# ============================================================
FULL_FROM_ISO = "2000-01-01T00:00:00Z"
FULL_TO_ISO = "2030-01-01T00:00:00Z"

FULL_COUNTBACK = 5000
MAX_INITIAL_PAGES = 30


# ============================================================
# INCREMENTAL SYNC
# ============================================================
INCREMENTAL_LOOKBACK_DAYS = 30
INCREMENTAL_COUNTBACK = 500


# ============================================================
# NETWORK SAFETY
# ============================================================
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
RETRY_BASE_SECONDS = 2.0
MAX_RETRY_DELAY_SECONDS = 30.0

SLEEP_BETWEEN_SYMBOLS_SECONDS = 0.35


# ============================================================
# LOCK SAFETY
# ============================================================
LOCK_STALE_SECONDS = 3 * 60 * 60


# ============================================================
# VALIDATION
# ============================================================
MAX_RESPONSE_BYTES = 25 * 1024 * 1024
MIN_INITIAL_CANDLES = 1
MAX_ERROR_TEXT = 400

RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}
PERMANENT_HTTP = {401, 403, 404, 422}


# ============================================================
# EXCEPTIONS
# ============================================================
class SyncError(Exception):
    pass


class LockError(SyncError):
    pass


class ValidationError(SyncError):
    pass


class HTTPStatusError(SyncError):
    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(message)


# ============================================================
# GENERIC HELPERS
# ============================================================
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def compact_error(exc: Exception | str) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:MAX_ERROR_TEXT] if text else "UNKNOWN_ERROR"


def finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def as_time_ms(value: Any) -> int | None:
    if not finite_number(value):
        return None

    result = int(float(value))

    if result <= 0:
        return None

    return result


def epoch_ms_to_iso(value: int | float) -> str:
    return datetime.fromtimestamp(
        float(value) / 1000.0,
        tz=timezone.utc,
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def subtract_days_iso(time_ms: int | float, days: int) -> str:
    dt = datetime.fromtimestamp(
        float(time_ms) / 1000.0,
        tz=timezone.utc,
    )

    dt -= timedelta(days=days)

    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_to_epoch_ms(value: str) -> int:
    dt = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    return int(dt.timestamp() * 1000)


# ============================================================
# JSON / ATOMIC STORAGE
# ============================================================
def load_json(
    path: Path,
    default: Any = None,
    *,
    strict: bool = False,
) -> Any:

    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    except Exception as exc:

        if strict:
            raise SyncError(
                f"INVALID_JSON: {path}: {compact_error(exc)}"
            ) from exc

        return default


def verify_json(path: Path) -> Any:

    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    except Exception as exc:
        raise SyncError(
            f"JSON_VERIFY_FAILED: {path}: {compact_error(exc)}"
        ) from exc


def write_json_atomic(path: Path, data: Any) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )

    tmp_path = Path(tmp_name)

    try:

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as fh:

            json.dump(
                data,
                fh,
                ensure_ascii=False,
                separators=(",", ":"),
            )

            fh.flush()
            os.fsync(fh.fileno())

        verify_json(tmp_path)

        os.replace(
            tmp_path,
            path,
        )

        verify_json(path)

    except Exception:

        try:
            tmp_path.unlink(
                missing_ok=True
            )
        except Exception:
            pass

        raise


# ============================================================
# LOCK
# ============================================================
def acquire_lock() -> None:

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if LOCK_FILE.exists():

        stale = False

        try:

            stat = LOCK_FILE.stat()

            age = (
                time.time()
                - stat.st_mtime
            )

            stale = age >= LOCK_STALE_SECONDS

        except FileNotFoundError:
            stale = False

        if not stale:
            raise LockError(
                "LOCK_EXISTS: another update is active"
            )

        try:
            LOCK_FILE.unlink()

        except FileNotFoundError:
            pass

    payload = {
        "time": utc_now_iso(),
        "pid": os.getpid(),
        "host": socket.gethostname(),
    }

    try:

        fd = os.open(
            str(LOCK_FILE),
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY,
        )

    except FileExistsError as exc:

        raise LockError(
            "LOCK_EXISTS: another update acquired the lock"
        ) from exc

    try:

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as fh:

            json.dump(
                payload,
                fh,
                ensure_ascii=False,
            )

            fh.flush()
            os.fsync(fh.fileno())

    except Exception:

        try:
            LOCK_FILE.unlink(
                missing_ok=True
            )
        except Exception:
            pass

        raise


def release_lock() -> None:

    try:
        LOCK_FILE.unlink(
            missing_ok=True
        )

    except Exception:
        pass


# ============================================================
# NETWORK
# ============================================================
def build_bars_url(
    asset_id: int,
    *,
    countback: int,
    from_iso: str,
    to_iso: str,
) -> str:

    params = {
        "countback": str(countback),
        "symbol": (
            f"exchange.asset:{asset_id}:real_close:type0"
        ),
        "resolution": "D",
        "from": from_iso,
        "to": to_iso,
    }

    return (
        API
        + "/chart/bars?"
        + urllib.parse.urlencode(params)
    )


def http_get_json(url: str) -> dict[str, Any]:

    if not TOKEN:
        raise SyncError(
            "TOKEN_MISSING: RV_TOKEN is not set"
        )

    last_error: Exception | None = None

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        try:

            request = urllib.request.Request(
                url,
                headers=HEADERS,
                method="GET",
            )

            with urllib.request.urlopen(
                request,
                timeout=REQUEST_TIMEOUT_SECONDS,
            ) as response:

                status = int(
                    getattr(
                        response,
                        "status",
                        200,
                    )
                )

                if status < 200 or status >= 300:
                    raise HTTPStatusError(
                        status,
                        f"HTTP_ERROR: {status}",
                    )

                body = response.read(
                    MAX_RESPONSE_BYTES + 1
                )

                if len(body) > MAX_RESPONSE_BYTES:
                    raise SyncError(
                        "API_RESPONSE_TOO_LARGE"
                    )

                try:

                    payload = json.loads(
                        body.decode("utf-8")
                    )

                except UnicodeDecodeError as exc:

                    raise SyncError(
                        "API_RESPONSE_NOT_UTF8"
                    ) from exc

                except json.JSONDecodeError as exc:

                    last_error = exc

                    raise SyncError(
                        f"API_INVALID_JSON: "
                        f"{compact_error(exc)}"
                    ) from exc

                if not isinstance(
                    payload,
                    dict,
                ):

                    raise SyncError(
                        "API_INVALID_JSON_ROOT"
                    )

                return payload

        except urllib.error.HTTPError as exc:

            if exc.code == 401:

                raise HTTPStatusError(
                    401,
                    "TOKEN_EXPIRED_OR_INVALID: HTTP 401",
                ) from exc

            if exc.code == 403:

                raise HTTPStatusError(
                    403,
                    "FORBIDDEN: HTTP 403",
                ) from exc

            if exc.code == 404:

                raise HTTPStatusError(
                    404,
                    "SYMBOL_NOT_FOUND: HTTP 404",
                ) from exc

            if exc.code == 422:

                raise HTTPStatusError(
                    422,
                    "BAD_PARAMS: HTTP 422",
                ) from exc

            last_error = exc

            if exc.code not in RETRYABLE_HTTP:

                raise HTTPStatusError(
                    exc.code,
                    f"HTTP_ERROR: {exc.code}",
                ) from exc

        except HTTPStatusError:
            raise

        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            ConnectionError,
        ) as exc:

            last_error = exc

        except SyncError as exc:

            last_error = exc

            if not str(exc).startswith(
                "API_INVALID_JSON:"
            ):
                raise

        except Exception as exc:

            last_error = exc

        if attempt < MAX_RETRIES:

            delay = min(
                RETRY_BASE_SECONDS
                * (2 ** (attempt - 1)),
                MAX_RETRY_DELAY_SECONDS,
            )

            time.sleep(delay)

    raise SyncError(
        "MAX_RETRIES_EXCEEDED: "
        + compact_error(
            last_error or "unknown"
        )
    )


# ============================================================
# API RESPONSE / CANDLE VALIDATION
# ============================================================
def extract_api_rows(
    payload: dict[str, Any],
) -> list[Any]:

    candidates = [
        payload.get("data"),
        payload.get("result"),
        payload.get("bars"),
    ]

    for candidate in candidates:

        if isinstance(
            candidate,
            list,
        ):
            return candidate

        if isinstance(
            candidate,
            dict,
        ):

            nested = (
                candidate.get("data")
                or candidate.get("bars")
            )

            if isinstance(
                nested,
                list,
            ):
                return nested

    raise ValidationError(
        "API_DATA_ARRAY_NOT_FOUND"
    )


def candle_is_usable_for_sync(
    candle: Any,
) -> bool:

    if not isinstance(
        candle,
        dict,
    ):
        return False

    t = as_time_ms(
        candle.get("time")
    )

    if t is None:
        return False

    close = candle.get("close")

    if close is None:
        return False

    if not finite_number(close):
        return False

    if float(close) <= 0:
        return False

    for key in (
        "open",
        "high",
        "low",
    ):

        if (
            key in candle
            and candle[key] is not None
            and not finite_number(
                candle[key]
            )
        ):
            return False

    if (
        "volume" in candle
        and candle["volume"] is not None
    ):

        if not finite_number(
            candle["volume"]
        ):
            return False

    return True


def normalize_new_rows(
    rows: list[Any],
) -> tuple[list[dict[str, Any]], int]:

    by_time: dict[
        int,
        dict[str, Any],
    ] = {}

    skipped = 0

    for candle in rows:

        if not candle_is_usable_for_sync(
            candle
        ):

            skipped += 1
            continue

        t = as_time_ms(
            candle["time"]
        )

        assert t is not None

        by_time[t] = candle

    clean = sorted(
        by_time.values(),
        key=lambda item: int(
            item["time"]
        ),
    )

    return clean, skipped


def load_existing_raw(
    path: Path,
) -> list[dict[str, Any]]:

    data = load_json(
        path,
        [],
        strict=True,
    )

    if not isinstance(
        data,
        list,
    ):
        raise ValidationError(
            "EXISTING_DATA_NOT_ARRAY"
        )

    result: list[
        dict[str, Any]
    ] = []

    for index, candle in enumerate(
        data
    ):

        if not isinstance(
            candle,
            dict,
        ):

            raise ValidationError(
                "EXISTING_ROW_NOT_OBJECT: "
                f"index={index}"
            )

        if as_time_ms(
            candle.get("time")
        ) is None:

            raise ValidationError(
                "EXISTING_TIME_INVALID: "
                f"index={index}"
            )

        result.append(candle)

    return result


def history_last_time(
    candles: list[dict[str, Any]],
) -> int | None:

    if not candles:
        return None

    return max(
        int(c["time"])
        for c in candles
    )


# ============================================================
# MERGE
# ============================================================
def merge_incremental(
    old: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    int,
    int,
    bool,
]:

    existing_positions: dict[
        int,
        list[int],
    ] = {}

    for index, candle in enumerate(
        old
    ):

        existing_positions.setdefault(
            int(candle["time"]),
            [],
        ).append(index)

    merged = list(old)

    added = 0
    updated = 0

    for candle in new:

        t = int(
            candle["time"]
        )

        positions = (
            existing_positions.get(t)
        )

        if positions:

            index = positions[-1]

            if merged[index] != candle:

                merged[index] = candle
                updated += 1

        else:

            existing_positions[t] = [
                len(merged)
            ]

            merged.append(candle)
            added += 1

    changed = (
        added > 0
        or updated > 0
    )

    if changed:

        merged.sort(
            key=lambda item: int(
                item["time"]
            )
        )

    return (
        merged,
        added,
        updated,
        changed,
    )


# ============================================================
# ROLLBACK / SAFE RAW WRITE
# ============================================================
def create_rollback_copy(
    path: Path,
) -> Path | None:

    if not path.exists():
        return None

    ROLLBACK_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    fd, name = tempfile.mkstemp(
        prefix=f"{path.stem}.",
        suffix=".bak",
        dir=str(
            ROLLBACK_DIR
        ),
    )

    os.close(fd)

    backup = Path(name)

    shutil.copy2(
        path,
        backup,
    )

    return backup


def safe_replace_raw(
    path: Path,
    new_data: list[
        dict[str, Any]
    ],
) -> None:

    backup = create_rollback_copy(
        path
    )

    try:

        write_json_atomic(
            path,
            new_data,
        )

        verified = load_existing_raw(
            path
        )

        if len(verified) != len(
            new_data
        ):

            raise SyncError(
                "POST_WRITE_COUNT_MISMATCH"
            )

        timestamps = [
            int(c["time"])
            for c in verified
        ]

        if timestamps != sorted(
            timestamps
        ):

            raise SyncError(
                "POST_WRITE_ORDER_INVALID"
            )

        if len(timestamps) != len(
            set(timestamps)
        ):
            pass

    except Exception as exc:

        if (
            backup
            and backup.exists()
        ):

            try:

                os.replace(
                    backup,
                    path,
                )

                backup = None

            except Exception as rollback_exc:

                raise SyncError(
                    "WRITE_FAILED_AND_ROLLBACK_FAILED: "
                    f"{compact_error(exc)} | "
                    f"rollback="
                    f"{compact_error(rollback_exc)}"
                ) from exc

        else:

            try:
                path.unlink(
                    missing_ok=True
                )
            except Exception:
                pass

        raise SyncError(
            "RAW_WRITE_ROLLED_BACK: "
            + compact_error(exc)
        ) from exc

    finally:

        if backup:

            try:

                backup.unlink(
                    missing_ok=True
                )

            except Exception:
                pass


# ============================================================
# DOWNLOAD
# ============================================================
def fetch_bars(
    asset_id: int,
    *,
    countback: int,
    from_iso: str,
    to_iso: str,
) -> tuple[
    list[dict[str, Any]],
    int,
]:

    url = build_bars_url(
        asset_id,
        countback=countback,
        from_iso=from_iso,
        to_iso=to_iso,
    )

    payload = http_get_json(
        url
    )

    rows = extract_api_rows(
        payload
    )

    return normalize_new_rows(
        rows
    )


def initial_full_download(
    asset_id: int,
) -> tuple[
    list[dict[str, Any]],
    int,
    int,
]:

    all_by_time: dict[
        int,
        dict[str, Any],
    ] = {}

    skipped_total = 0

    to_iso = FULL_TO_ISO

    previous_earliest: int | None = None

    page = 0

    for page in range(
        1,
        MAX_INITIAL_PAGES + 1,
    ):

        rows, skipped = fetch_bars(
            asset_id,
            countback=FULL_COUNTBACK,
            from_iso=FULL_FROM_ISO,
            to_iso=to_iso,
        )

        skipped_total += skipped

        if not rows:
            break

        for candle in rows:

            all_by_time[
                int(candle["time"])
            ] = candle

        earliest = min(
            int(c["time"])
            for c in rows
        )

        if earliest <= iso_to_epoch_ms(
            FULL_FROM_ISO
        ):
            break

        if (
            previous_earliest is not None
            and earliest
            >= previous_earliest
        ):
            break

        previous_earliest = earliest

        to_iso = epoch_ms_to_iso(
            earliest - 1
        )

        if len(rows) < FULL_COUNTBACK:
            break

    clean = sorted(
        all_by_time.values(),
        key=lambda item: int(
            item["time"]
        ),
    )

    return (
        clean,
        skipped_total,
        page,
    )


def incremental_download(
    asset_id: int,
    last_time: int,
) -> tuple[
    list[dict[str, Any]],
    int,
]:

    from_iso = subtract_days_iso(
        last_time,
        INCREMENTAL_LOOKBACK_DAYS,
    )

    to_iso = epoch_ms_to_iso(
        int(time.time() * 1000)
        + 86_400_000
    )

    rows, skipped = fetch_bars(
        asset_id,
        countback=INCREMENTAL_COUNTBACK,
        from_iso=from_iso,
        to_iso=to_iso,
    )

    return rows, skipped


# ============================================================
# SYMBOL UPDATE
# ============================================================
def update_symbol(
    symbol: dict[str, Any],
) -> dict[str, Any]:

    try:

        asset_id = int(
            symbol["id"]
        )

        name = str(
            symbol["name"]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:

        raise SyncError(
            "INVALID_SYMBOL_FIELDS"
        ) from exc

    path = (
        RAW_DIR
        / f"{asset_id}.json"
    )

    if path.exists():

        try:

            old = load_existing_raw(
                path
            )

        except Exception as exc:

            raise ValidationError(
                f"EXISTING_DATA_INVALID: "
                f"{path.name}: "
                f"{compact_error(exc)}"
            ) from exc

    else:

        old = []

    last_time = history_last_time(
        old
    )

    # --------------------------------------------------------
    # INITIAL
    # --------------------------------------------------------
    if last_time is None:

        new, skipped, pages = (
            initial_full_download(
                asset_id
            )
        )

        if len(new) < MIN_INITIAL_CANDLES:

            raise ValidationError(
                f"INITIAL_DOWNLOAD_TOO_FEW: "
                f"{len(new)}"
            )

        safe_replace_raw(
            path,
            new,
        )

        return {
            "id": asset_id,
            "name": name,
            "mode": "initial",
            "downloaded": len(new),
            "added": len(new),
            "updated": 0,
            "final": len(new),
            "changed": True,
            "skipped_invalid": skipped,
            "pages": pages,
            "last_time": int(
                new[-1]["time"]
            ),
        }

    # --------------------------------------------------------
    # INCREMENTAL
    # --------------------------------------------------------
    new, skipped = incremental_download(
        asset_id,
        last_time,
    )

    (
        merged,
        added,
        updated,
        changed,
    ) = merge_incremental(
        old,
        new,
    )

    if changed:

        safe_replace_raw(
            path,
            merged,
        )

    return {
        "id": asset_id,
        "name": name,
        "mode": "incremental",
        "downloaded": len(new),
        "added": added,
        "updated": updated,
        "final": len(merged),
        "changed": changed,
        "skipped_invalid": skipped,
        "pages": 1,
        "last_time": int(
            merged[-1]["time"]
        ),
    }


# ============================================================
# SYMBOL FILE
# ============================================================
def load_symbols() -> list[
    dict[str, Any]
]:

    data = load_json(
        SYMBOL_FILE,
        None,
        strict=True,
    )

    if (
        not isinstance(data, list)
        or not data
    ):

        raise SyncError(
            "SYMBOL_FILE_EMPTY_OR_INVALID"
        )

    result: list[
        dict[str, Any]
    ] = []

    seen_ids: set[int] = set()

    for item in data:

        if not isinstance(
            item,
            dict,
        ):

            raise SyncError(
                "INVALID_SYMBOLS_JSON_RECORD"
            )

        if (
            "id" not in item
            or "name" not in item
        ):

            raise SyncError(
                "INVALID_SYMBOLS_JSON_FIELDS"
            )

        try:

            asset_id = int(
                item["id"]
            )

        except (
            TypeError,
            ValueError,
        ) as exc:

            raise SyncError(
                f"INVALID_SYMBOL_ID: "
                f"{item.get('id')}"
            ) from exc

        if asset_id <= 0:

            raise SyncError(
                f"INVALID_SYMBOL_ID: "
                f"{asset_id}"
            )

        if asset_id in seen_ids:

            raise SyncError(
                f"DUPLICATE_SYMBOL_ID: "
                f"{asset_id}"
            )

        seen_ids.add(
            asset_id
        )

        result.append(
            {
                "id": asset_id,
                "name": str(
                    item["name"]
                ),
            }
        )

    return result


def find_orphan_raw_files(
    symbols: list[
        dict[str, Any]
    ],
) -> list[str]:

    active = {
        str(s["id"])
        for s in symbols
    }

    if not RAW_DIR.exists():
        return []

    return sorted(
        path.stem
        for path in RAW_DIR.glob(
            "*.json"
        )
        if path.stem not in active
    )


# ============================================================
# REPORT / STATUS
# ============================================================
def load_object(
    path: Path,
) -> dict[str, Any]:

    data = load_json(
        path,
        {},
        strict=False,
    )

    return (
        data
        if isinstance(data, dict)
        else {}
    )


def save_status_best_effort(
    status: dict[str, Any],
) -> None:

    try:

        write_json_atomic(
            STATUS_FILE,
            status,
        )

    except Exception as exc:

        print(
            "     WARNING: "
            "STATUS_WRITE_FAILED: "
            + compact_error(exc)
        )


def save_report_best_effort(
    report: dict[str, Any],
) -> None:

    try:

        write_json_atomic(
            REPORT_FILE,
            report,
        )

    except Exception as exc:

        print(
            "WARNING: "
            "REPORT_WRITE_FAILED: "
            + compact_error(exc)
        )


def save_errors_best_effort(
    errors: list[
        dict[str, Any]
    ],
) -> None:

    try:

        write_json_atomic(
            ERROR_FILE,
            errors,
        )

    except Exception as exc:

        print(
            "WARNING: "
            "ERROR_REPORT_WRITE_FAILED: "
            + compact_error(exc)
        )


# ============================================================
# MAIN
# ============================================================
def main() -> int:

    start_clock = time.time()

    start_iso = utc_now_iso()

    print("=" * 60)
    print(
        "RAHAVARD365 CHART DATA SYNC V7.0 PRODUCTION"
    )
    print("=" * 60)

    print(
        f"Test mode: {TEST_MODE}"
    )

    print(
        "Adjustment in raw files: False"
    )

    print(
        "Existing RAW: incremental only"
    )

    print(
        "New RAW: full historical backfill"
    )

    print("")

    if not TOKEN:

        print(
            "FATAL: TOKEN_MISSING: "
            "RV_TOKEN is not set"
        )

        return 1

    acquire_lock()

    errors: list[
        dict[str, Any]
    ] = []

    results: list[
        dict[str, Any]
    ] = []

    status = load_object(
        STATUS_FILE
    )

    try:

        RAW_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        symbols_all = load_symbols()

        if TEST_MODE:

            wanted = set(
                TEST_SYMBOLS
            )

            symbols = [
                s
                for s in symbols_all
                if s["name"] in wanted
            ]

            missing = sorted(
                wanted
                - {
                    s["name"]
                    for s in symbols
                }
            )

            if missing:

                raise SyncError(
                    "TEST_SYMBOLS_MISSING: "
                    + ", ".join(missing)
                )

            print(
                f"TEST MODE: {len(symbols)}"
            )

        else:

            symbols = symbols_all

            print(
                f"FULL MODE: {len(symbols)}"
            )

        print("")

        total_added = 0
        total_updated = 0
        total_skipped = 0

        success = 0
        no_change = 0

        initial_count = 0
        incremental_count = 0

        run_stamp = utc_now_iso()

        for index, symbol in enumerate(
            symbols,
            start=1,
        ):

            name = symbol["name"]

            symbol_start = time.time()

            print(
                f"[{index}/{len(symbols)}] "
                f"{name}"
            )

            try:

                row = update_symbol(
                    symbol
                )

                results.append(
                    row
                )

                success += 1

                total_added += (
                    row["added"]
                )

                total_updated += (
                    row["updated"]
                )

                total_skipped += (
                    row[
                        "skipped_invalid"
                    ]
                )

                if not row["changed"]:
                    no_change += 1

                if row["mode"] == "initial":
                    initial_count += 1
                else:
                    incremental_count += 1

                status[
                    str(row["id"])
                ] = {

                    "name": row["name"],
                    "last_update": run_stamp,
                    "status": "ok",
                    "mode": row["mode"],
                    "candles": row["final"],
                    "last_time": row["last_time"],
                    "downloaded": row["downloaded"],
                    "added": row["added"],
                    "updated": row["updated"],
                    "skipped_invalid": row[
                        "skipped_invalid"
                    ],
                }

                save_status_best_effort(
                    status
                )

                print(
                    f"     Mode:        "
                    f"{row['mode']}"
                )

                print(
                    f"     Downloaded:  "
                    f"{row['downloaded']}"
                )

                print(
                    f"     Added:       "
                    f"{row['added']}"
                )

                print(
                    f"     Updated:     "
                    f"{row['updated']}"
                )

                print(
                    f"     Final:       "
                    f"{row['final']}"
                )

                print(
                    f"     Skipped:     "
                    f"{row['skipped_invalid']}"
                )

                print(
                    "     Status:      "
                    + (
                        "UPDATED"
                        if row["changed"]
                        else "NO_CHANGE"
                    )
                )

                print(
                    f"     Duration:    "
                    f"{round(time.time() - symbol_start, 2)}s"
                )

            except Exception as exc:

                message = compact_error(
                    exc
                )

                errors.append(
                    {
                        "id": symbol.get("id"),
                        "name": symbol.get("name"),
                        "time": utc_now_iso(),
                        "error": message,
                    }
                )

                status[
                    str(symbol.get("id"))
                ] = {

                    "name": symbol.get(
                        "name"
                    ),

                    "last_update": run_stamp,

                    "status": "error",

                    "error": message,
                }

                save_status_best_effort(
                    status
                )

                print(
                    "     Status:      ERROR"
                )

                print(
                    f"     Reason:      "
                    f"{message}"
                )

            time.sleep(
                SLEEP_BETWEEN_SYMBOLS_SECONDS
            )

        orphans = (
            find_orphan_raw_files(
                symbols_all
            )
        )

        if orphans:

            print("")

            print(
                "ORPHAN RAW FILES PRESERVED: "
                f"{len(orphans)}"
            )

        duration = round(
            time.time()
            - start_clock,
            2,
        )

        end_iso = utc_now_iso()

        report = {

            "version": "V7.0-PRODUCTION",

            "start_time": start_iso,

            "end_time": end_iso,

            "duration_seconds": duration,

            "test_mode": TEST_MODE,

            "adjusted_raw": False,

            "incremental_lookback_days":
                INCREMENTAL_LOOKBACK_DAYS,

            "incremental_countback":
                INCREMENTAL_COUNTBACK,

            "initial_countback":
                FULL_COUNTBACK,

            "total_symbols":
                len(symbols),

            "success":
                success,

            "errors":
                len(errors),

            "new_candles":
                total_added,

            "updated_candles":
                total_updated,

            "skipped_invalid_api_rows":
                total_skipped,

            "no_change":
                no_change,

            "initial_downloads":
                initial_count,

            "incremental_updates":
                incremental_count,

            "orphans_preserved":
                len(orphans),

            "orphans":
                orphans,

            "results":
                results,
        }

        save_errors_best_effort(
            errors
        )

        save_report_best_effort(
            report
        )

        print("")

        print("=" * 60)

        print(
            f"SUCCESS:        "
            f"{success}"
        )

        print(
            f"ERRORS:         "
            f"{len(errors)}"
        )

        print(
            f"NEW CANDLES:    "
            f"{total_added}"
        )

        print(
            f"UPDATED CANDLES:"
            f"{total_updated}"
        )

        print(
            f"NO CHANGE:      "
            f"{no_change}"
        )

        print(
            f"DURATION:       "
            f"{duration}s"
        )

        print("=" * 60)

        return (
            0
            if not errors
            else 2
        )

    finally:

        release_lock()

        try:

            if ROLLBACK_DIR.exists():

                shutil.rmtree(
                    ROLLBACK_DIR,
                    ignore_errors=True,
                )

        except Exception:
            pass


if __name__ == "__main__":

    try:

        raise SystemExit(
            main()
        )

    except LockError as exc:

        print(
            f"FATAL: "
            f"{compact_error(exc)}"
        )

        raise SystemExit(1)

    except KeyboardInterrupt:

        release_lock()

        print(
            "FATAL: INTERRUPTED"
        )

        raise SystemExit(130)

    except Exception as exc:

        release_lock()

        print(
            f"FATAL: "
            f"{compact_error(exc)}"
        )

        raise SystemExit(1)
