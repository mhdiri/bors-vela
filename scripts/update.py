"""
Rahavard365 Chart Data Sync Engine - V6.1
تعدیل‌شده برای سازگاری با فایل‌های قدیمی

Design goals:
- Keep data/raw as source-of-truth raw OHLCV.
- Never adjust or rewrite raw history for chart-gap removal.
- Full download always (safe mode).
- Safe atomic writes, transient rollback backups, validation, retry/backoff, lock, reports.
- TEST_MODE allows a 5-symbol verification without editing symbols.json.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


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

BACKUP_DIR = Path(tempfile.gettempdir()) / "bors_vela_update_backups"

# ---------- Operating mode ----------
TEST_MODE = True
TEST_SYMBOLS = {"فولاد", "غچین", "فسرب", "کیسون", "فاما"}

# ---------- Sync policy ----------
FULL_FROM = "2000-01-01T00:00:00Z"
FULL_TO = "2030-01-01T00:00:00Z"
FULL_COUNTBACK = 5000

MIN_CANDLES = 10
SUSPICIOUS_REDUCTION_RATIO = 0.50

# ---------- Reliability ----------
MAX_RETRY = 5
REQUEST_TIMEOUT = 60
RETRY_BASE_SECONDS = 3.0
SLEEP_BETWEEN_SYMBOLS = 0.50
LOCK_STALE_HOURS = 3

TRANSIENT_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}


class UpdateError(Exception):
    """Expected, reportable update error."""


class LockError(UpdateError):
    """Another update process is active."""


class ValidationError(UpdateError):
    """Downloaded or stored data failed validation."""


class HTTPStatusError(UpdateError):
    """HTTP error with a stable machine-readable message."""

    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(message)


# ---------- Time helpers ----------
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def epoch_ms_to_iso(epoch_ms: int | float) -> str:
    dt = datetime.fromtimestamp(float(epoch_ms) / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- JSON I/O ----------
def load_json(path: Path, default: Any = None, *, strict: bool = False) -> Any:
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        if strict:
            raise UpdateError(f"INVALID_JSON: {path}: {exc}") from exc
        return default


def validate_json_file(path: Path) -> None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            json.load(fh)
    except Exception as exc:
        raise UpdateError(f"JSON_VERIFY_FAILED: {path}: {exc}") from exc


def save_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(
                data,
                fh,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            fh.flush()
            os.fsync(fh.fileno())

        validate_json_file(temp_path)
        os.replace(temp_path, path)
        validate_json_file(path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


# ---------- Lock ----------
def acquire_lock() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if LOCK_FILE.exists():
        try:
            info = load_json(LOCK_FILE, {}, strict=True)
            raw_time = info.get("time")
            if raw_time:
                lock_dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                age_hours = (
                    datetime.now(timezone.utc) - lock_dt.astimezone(timezone.utc)
                ).total_seconds() / 3600.0
                if age_hours < LOCK_STALE_HOURS:
                    raise LockError(
                        f"LOCK_EXISTS: active lock age={age_hours:.2f}h"
                    )
        except LockError:
            raise
        except Exception:
            pass

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
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise LockError("LOCK_EXISTS: another process acquired the lock") from exc

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except Exception:
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ---------- HTTP ----------
def request_json(url: str) -> dict[str, Any]:
    if not TOKEN:
        raise UpdateError("TOKEN_MISSING: RV_TOKEN is not set")

    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRY + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS, method="GET")
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
                status = getattr(response, "status", 200)
                if status < 200 or status >= 300:
                    raise HTTPStatusError(status, f"HTTP_ERROR: {status}")

                payload = response.read().decode("utf-8")
                data = json.loads(payload)
                if not isinstance(data, dict):
                    raise UpdateError("API_INVALID_JSON_ROOT")
                return data

        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 401:
                raise HTTPStatusError(401, "TOKEN_EXPIRED: 401") from exc
            if exc.code == 403:
                raise HTTPStatusError(403, "FORBIDDEN: 403") from exc
            if exc.code == 404:
                raise HTTPStatusError(404, "SYMBOL_NOT_FOUND: 404") from exc
            if exc.code == 422:
                raise HTTPStatusError(422, "BAD_PARAMS: 422") from exc
            if exc.code not in TRANSIENT_HTTP_CODES:
                raise HTTPStatusError(exc.code, f"HTTP_ERROR: {exc.code}") from exc

        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            last_error = exc

        except json.JSONDecodeError as exc:
            last_error = exc

        except UpdateError:
            raise

        except Exception as exc:
            last_error = exc

        if attempt < MAX_RETRY:
            delay = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            time.sleep(delay)

    detail = str(last_error)[:200] if last_error else "unknown"
    raise UpdateError(f"MAX_RETRY: {detail}")


# ---------- API ----------
def get_bars(asset_id: int) -> dict[str, Any]:
    """همیشه full download (safe mode)"""
    url = (
        API
        + f"/chart/bars?countback={FULL_COUNTBACK}"
        + "&symbol=exchange.asset:"
        + str(asset_id)
        + ":real_close:type0"
        + "&resolution=D"
        + f"&from={FULL_FROM}"
        + f"&to={FULL_TO}"
    )
    return request_json(url)


# ---------- Data quality ----------
def finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def valid_candle(candle: Any) -> bool:
    if not isinstance(candle, dict):
        return False

    for key in ("time", "open", "high", "low", "close"):
        if key not in candle or not finite_number(candle[key]):
            return False

    time_value = float(candle["time"])
    if time_value <= 0:
        return False

    open_v = float(candle["open"])
    high_v = float(candle["high"])
    low_v = float(candle["low"])
    close_v = float(candle["close"])

    if min(open_v, high_v, low_v, close_v) < 0:
        return False
    if high_v < max(open_v, low_v, close_v):
        return False
    if low_v > min(open_v, high_v, close_v):
        return False

    if "volume" in candle and candle["volume"] is not None:
        if not finite_number(candle["volume"]):
            return False
        if float(candle["volume"]) < 0:
            return False

    return True


def clean_candles(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise ValidationError("INVALID_DATA_ROOT")

    dedup: dict[int, dict[str, Any]] = {}
    for candle in data:
        if not valid_candle(candle):
            raise ValidationError("INVALID_CANDLE")
        key = int(candle["time"])
        dedup[key] = candle

    out = sorted(dedup.values(), key=lambda item: int(item["time"]))
    if len(out) < MIN_CANDLES:
        raise ValidationError(f"TOO_FEW_CANDLES: {len(out)}")

    for idx in range(1, len(out)):
        if int(out[idx]["time"]) <= int(out[idx - 1]["time"]):
            raise ValidationError("TIME_ORDER_ERROR")

    return out


def load_existing_candles(path: Path) -> list[dict[str, Any]]:
    """اگه فایل قدیمی خراب بود، نادیده بگیر و از نو دانلود کن"""
    if not path.exists():
        return []

    data = load_json(path, None, strict=False)
    if data is None:
        print(f"     WARNING: {path.name} unreadable, will re-download")
        return []

    try:
        return clean_candles(data)
    except ValidationError as exc:
        print(f"     WARNING: {path.name} invalid ({exc}), will re-download")
        return []


def merge_candles(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, bool]:
    by_time = {int(c["time"]): c for c in old}
    before = dict(by_time)

    for candle in new:
        by_time[int(candle["time"])] = candle

    merged = sorted(by_time.values(), key=lambda item: int(item["time"]))
    added = sum(1 for key in by_time if key not in before)
    changed = merged != old
    return merged, added, changed


# ---------- Safe per-symbol persistence ----------
def backup_for_rollback(path: Path) -> Path | None:
    if not path.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"{path.name}.{os.getpid()}.bak"
    shutil.copy2(path, backup)
    return backup


def rollback_file(path: Path, backup: Path | None) -> None:
    try:
        if backup and backup.exists():
            shutil.copy2(backup, path)
    except Exception as exc:
        print(f"     ROLLBACK_FAILED: {exc}")


def cleanup_backup(backup: Path | None) -> None:
    if not backup:
        return
    try:
        backup.unlink(missing_ok=True)
    except Exception:
        pass


# ---------- Single symbol ----------
def update_symbol(symbol: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(symbol, dict):
        raise UpdateError("INVALID_SYMBOL_RECORD")

    try:
        asset_id = int(symbol["id"])
        name = str(symbol["name"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UpdateError("INVALID_SYMBOL_FIELDS") from exc

    path = RAW_DIR / f"{asset_id}.json"
    old = load_existing_candles(path)
    old_count = len(old)
    is_new_symbol = old_count == 0

    result = get_bars(asset_id)
    raw = result.get("data")
    new = clean_candles(raw)

    # اگه داده خیلی کمتر شد، هشدار بده ولی ادامه بده
    if old_count and len(new) < max(MIN_CANDLES, int(old_count * SUSPICIOUS_REDUCTION_RATIO)):
        print(f"     WARNING: SUSPICIOUS_REDUCTION old={old_count} new={len(new)} - overriding with new")

    merged, added, changed = merge_candles(old, new)

    # Final structural validation
    merged = clean_candles(merged)

    if changed:
        backup = backup_for_rollback(path)
        try:
            save_atomic(path, merged)
            verified = load_existing_candles(path)
            if len(verified) != len(merged):
                raise UpdateError("POST_WRITE_VERIFY_FAILED")
        except Exception as exc:
            rollback_file(path, backup)
            raise UpdateError(f"SAVE_ROLLBACK: {exc}") from exc
        finally:
            cleanup_backup(backup)
    else:
        backup = None

    return {
        "name": name,
        "id": asset_id,
        "mode": "initial" if is_new_symbol else "incremental",
        "downloaded": len(new),
        "added": added,
        "final": len(merged),
        "changed": changed,
        "last_time": int(merged[-1]["time"]) if merged else None,
    }


# ---------- Reporting ----------
def load_status() -> dict[str, Any]:
    data = load_json(STATUS_FILE, {}, strict=False)
    return data if isinstance(data, dict) else {}


def scan_orphans(symbols: list[dict[str, Any]]) -> list[str]:
    known_ids = set()
    for symbol in symbols:
        try:
            known_ids.add(str(int(symbol["id"])))
        except Exception:
            continue

    if not RAW_DIR.exists():
        return []

    orphans = []
    for path in RAW_DIR.glob("*.json"):
        if path.stem not in known_ids:
            orphans.append(path.stem)
    return sorted(orphans)


# ---------- Main ----------
def main() -> int:
    started = time.time()
    start_iso = utc_now_iso()
    errors: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    total_added = 0
    success = 0
    no_change = 0

    print("=" * 60)
    print("RAHAVARD CHART DATA SYNC V6.1")
    print("=" * 60)
    print(f"Test mode: {TEST_MODE}")
    print("Adjustment in raw files: False")
    print("")

    if not TOKEN:
        print("FATAL: RV_TOKEN is missing")
        return 1

    acquire_lock()
    try:
        RAW_DIR.mkdir(parents=True, exist_ok=True)

        symbols = load_json(SYMBOL_FILE, [], strict=True)
        if not isinstance(symbols, list) or not symbols:
            raise UpdateError("SYMBOL_FILE_EMPTY_OR_INVALID")

        normalized_symbols: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for symbol in symbols:
            if not isinstance(symbol, dict) or "id" not in symbol or "name" not in symbol:
                raise UpdateError("INVALID_SYMBOLS_JSON_RECORD")
            asset_id = int(symbol["id"])
            if asset_id in seen_ids:
                raise UpdateError(f"DUPLICATE_SYMBOL_ID: {asset_id}")
            seen_ids.add(asset_id)
            normalized_symbols.append({"id": asset_id, "name": str(symbol["name"])})

        if TEST_MODE:
            symbols = [s for s in normalized_symbols if s["name"] in TEST_SYMBOLS]
            missing = sorted(TEST_SYMBOLS - {s["name"] for s in symbols})
            if missing:
                raise UpdateError("TEST_SYMBOLS_MISSING: " + ", ".join(missing))
            print(f"TEST MODE: {len(symbols)}")
        else:
            symbols = normalized_symbols
            print(f"FULL MODE: {len(symbols)}")

        print("")

        status = load_status()
        run_stamp = utc_now_iso()

        for index, symbol in enumerate(symbols, start=1):
            label = symbol["name"]
            print(f"[{index}/{len(symbols)}] {label}")
            item_started = time.time()

            try:
                row = update_symbol(symbol)
                total_added += row["added"]
                success += 1
                if not row["changed"]:
                    no_change += 1

                status[str(row["id"])] = {
                    "name": row["name"],
                    "last_update": run_stamp,
                    "candles": row["final"],
                    "last_time": row["last_time"],
                    "mode": row["mode"],
                    "status": "ok",
                }

                print(f"     Mode:       {row['mode']}")
                print(f"     Downloaded: {row['downloaded']}")
                print(f"     Added:      {row['added']}")
                print(f"     Final:      {row['final']}")
                print(f"     Changed:    {row['changed']}")
                print(f"     Duration:   {round(time.time() - item_started, 2)}s")
                print("     Status:     OK")

                results.append(row)

            except Exception as exc:
                message = str(exc)[:300]
                success_name = str(symbol.get("name", "?"))
                success_id = symbol.get("id")
                print("     Status:     ERROR")
                print(f"     Reason:     {message}")

                error_row = {
                    "name": success_name,
                    "id": success_id,
                    "error": message,
                    "time": utc_now_iso(),
                }
                errors.append(error_row)

                status[str(success_id)] = {
                    "name": success_name,
                    "last_update": run_stamp,
                    "status": "error",
                    "error": message,
                }

                # اگه توکن منقضی شد، متوقف شو
                if "TOKEN_EXPIRED" in message:
                    print("!! TOKEN EXPIRED - stopping")
                    break

            time.sleep(SLEEP_BETWEEN_SYMBOLS)

        orphans = scan_orphans(normalized_symbols)
        if orphans:
            print("")
            print(f"ORPHAN RAW FILES PRESERVED: {len(orphans)}")

        save_atomic(ERROR_FILE, errors)
        save_atomic(STATUS_FILE, status)

        ended_iso = utc_now_iso()
        duration = round(time.time() - started, 2)
        report = {
            "version": "V6.1",
            "start_time": start_iso,
            "end_time": ended_iso,
            "duration_seconds": duration,
            "total_symbols": len(symbols),
            "success": success,
            "errors": len(errors),
            "new_candles": total_added,
            "no_change": no_change,
            "test_mode": TEST_MODE,
            "adjusted_raw": False,
            "orphans_preserved": len(orphans),
        }
        save_atomic(REPORT_FILE, report)

        print("")
        print("=" * 60)
        print(f"SUCCESS:     {success}")
        print(f"ERRORS:      {len(errors)}")
        print(f"NEW CANDLES: {total_added}")
        print(f"NO CHANGE:   {no_change}")
        print(f"DURATION:    {duration}s")
        print("=" * 60)

        return 0 if not errors else 2

    finally:
        release_lock()
        try:
            if BACKUP_DIR.exists():
                shutil.rmtree(BACKUP_DIR, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LockError as exc:
        print(f"FATAL: {exc}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("FATAL: INTERRUPTED")
        raise SystemExit(130)
    except Exception as exc:
        print(f"FATAL: {str(exc)[:300]}")
        raise SystemExit(1)
