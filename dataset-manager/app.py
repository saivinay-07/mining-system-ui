"""Local Smart Vehicle Dataset Manager API and static application server."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from flask import Flask, jsonify, request, send_from_directory
from PIL import Image, ImageFile, UnidentifiedImageError

BASE = Path(__file__).resolve().parent
DATASET = Path(os.getenv("DATASET_ROOT", str(BASE.parent / "dataset"))).resolve()
DB = Path(os.getenv("DATASET_DB_PATH", str(BASE.parent / "dataset_manager.sqlite3"))).resolve()
WEB = BASE / "web"
MAX_BYTES = int(os.getenv("DATASET_MAX_IMAGE_BYTES", 15 * 1024 * 1024))
TIMEOUT = (5, 15)
Image.MAX_IMAGE_PIXELS = 40_000_000
ImageFile.LOAD_TRUNCATED_IMAGES = False

VEHICLE_VIEWS = {"front": "front", "rear": "rear", "side": "side", "diagonal": "diagonal", "multiple_vehicles": "multi_vehicles"}
VEHICLE_CONDITIONS = {"blurred", "bright_sunlight", "clear", "cloudy", "dust_haze", "far_distance", "medium_distance", "near", "night", "rain"}
PLATE_CONDITIONS = {"bright_sunlight", "clear", "cloudy", "dirty", "dust_haze", "far_distance", "medium_distance", "night", "rain", "slightly_blurred"}
LOCK = threading.RLock()
app = Flask(__name__, static_folder=None)


def connect():
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init():
    DB.parent.mkdir(parents=True, exist_ok=True)
    for path in allowed_folders().values():
        path.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS images (
          id INTEGER PRIMARY KEY, original_url TEXT NOT NULL, normalized_url TEXT NOT NULL UNIQUE,
          filename TEXT NOT NULL, stored_path TEXT NOT NULL UNIQUE, dataset_type TEXT NOT NULL,
          vehicle_view TEXT, condition TEXT, sha256 TEXT NOT NULL UNIQUE, phash TEXT NOT NULL,
          width INTEGER NOT NULL, height INTEGER NOT NULL, file_size INTEGER NOT NULL,
          image_format TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS images_phash_idx ON images(phash);
        CREATE INDEX IF NOT EXISTS images_created_idx ON images(created_at);
        CREATE TABLE IF NOT EXISTS duplicate_attempts (
          id INTEGER PRIMARY KEY, submitted_url TEXT NOT NULL, matched_image_id INTEGER NOT NULL,
          detection_method TEXT NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(matched_image_id) REFERENCES images(id) ON DELETE CASCADE
        );
        """)


def allowed_folders():
    out = {}
    for condition in sorted(PLATE_CONDITIONS):
        out[f"number_plates/{condition}"] = DATASET / "number_plates" / condition
    out["others/not_lorry"] = DATASET / "others" / "not_lorry"
    for view in VEHICLE_VIEWS.values():
        for condition in sorted(VEHICLE_CONDITIONS):
            out[f"vehicles/{view}/{condition}"] = DATASET / "vehicles" / view / condition
    return out


def normalize_url(url: str) -> str:
    p = urlsplit(url.strip())
    if p.scheme.lower() not in {"http", "https"} or not p.hostname or p.username or p.password:
        raise ValueError("Enter a valid direct HTTP or HTTPS image URL.")
    host = p.hostname.lower().rstrip(".")
    port = p.port
    netloc = f"{host}:{port}" if port and not ((p.scheme.lower() == "http" and port == 80) or (p.scheme.lower() == "https" and port == 443)) else host
    return urlunsplit((p.scheme.lower(), netloc, p.path or "/", p.query, ""))


def validate_public_host(url: str):
    p = urlsplit(url)
    host = p.hostname
    if not host or p.scheme not in ("http", "https"):
        raise ValueError("Only public HTTP and HTTPS image URLs are supported.")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)]
        except (OSError, ValueError):
            raise ValueError("The image host could not be resolved.")
    if not addresses or any(not ip.is_global for ip in addresses):
        raise ValueError("Private and local network addresses are not allowed.")


def fetch_image(url: str) -> tuple[bytes, str]:
    current = url
    for _ in range(4):
        validate_public_host(current)
        try:
            with requests.get(current, stream=True, timeout=TIMEOUT, allow_redirects=False, headers={"User-Agent": "SmartVehicleDatasetManager/1.0"}) as response:
                if response.is_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError("The image host returned an invalid redirect.")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                length = response.headers.get("Content-Length")
                if length and int(length) > MAX_BYTES:
                    raise ValueError(f"Image exceeds the {MAX_BYTES // (1024 * 1024)} MB limit.")
                chunks, size = [], 0
                for chunk in response.iter_content(64 * 1024):
                    if chunk:
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError(f"Image exceeds the {MAX_BYTES // (1024 * 1024)} MB limit.")
                        chunks.append(chunk)
                payload = b"".join(chunks)
                if not payload:
                    raise ValueError("The URL returned an empty file.")
                return payload, current
        except requests.RequestException as exc:
            raise ValueError(f"Could not retrieve this image: {exc.__class__.__name__}.") from exc
    raise ValueError("The image URL redirected too many times.")


def inspect_image(payload: bytes):
    try:
        import io
        with Image.open(io.BytesIO(payload)) as image:
            image.verify()
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            fmt = (image.format or "").upper()
            if fmt not in {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF"}:
                raise ValueError("This image format is not supported.")
            width, height = image.size
            phash = perceptual_hash(image)
        return width, height, fmt, phash
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("The URL did not return a valid supported image.") from exc


def perceptual_hash(image: Image.Image) -> str:
    # 8x8 average hash provides a dependency-free visual duplicate signal.
    pixels = list(image.convert("L").resize((8, 8), Image.Resampling.LANCZOS).getdata())
    average = sum(pixels) / len(pixels)
    return "".join("1" if px >= average else "0" for px in pixels)


def hamming(a, b):
    return sum(x != y for x, y in zip(a, b))


def image_record(row):
    data = dict(row)
    data["destination"] = "dataset/" + data.pop("stored_path")
    data["preview"] = "/api/images/" + str(data["id"]) + "/file"
    return data


def duplicate_match(db, url, digest, phash):
    row = db.execute("SELECT * FROM images WHERE normalized_url=?", (normalize_url(url),)).fetchone()
    if row:
        return row, "URL"
    row = db.execute("SELECT * FROM images WHERE sha256=?", (digest,)).fetchone()
    if row:
        return row, "SHA-256"
    # Hamming distance <= 3/64 is a conservative visual match; wider similarities are not blocked.
    rows = db.execute("SELECT * FROM images").fetchall()
    matches = [(hamming(phash, r["phash"]), r) for r in rows]
    matches = [(distance, r) for distance, r in matches if distance <= 3]
    if matches:
        _, match = min(matches, key=lambda item: item[0])
        return match, "Perceptual hash"
    return None, None


def record_duplicate(db, url, match, method):
    db.execute("INSERT INTO duplicate_attempts(submitted_url,matched_image_id,detection_method,created_at) VALUES(?,?,?,?)",
               (url, match["id"], method, datetime.now(timezone.utc).isoformat()))


@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/<path:path>")
def assets(path):
    return send_from_directory(WEB, path)


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "dataset_root": "dataset", "max_bytes": MAX_BYTES})


@app.post("/api/preview")
def preview():
    body = request.get_json(silent=True) or {}
    url = str(body.get("url", "")).strip()
    try:
        normalized = normalize_url(url)
        payload, final_url = fetch_image(url)
        width, height, fmt, phash = inspect_image(payload)
        digest = hashlib.sha256(payload).hexdigest()
        with connect() as db:
            match, method = duplicate_match(db, url, digest, phash)
            if match:
                record_duplicate(db, url, match, method)
                db.commit()
                return jsonify({"duplicate": True, "method": method, "existing": image_record(match), "width": width, "height": height, "format": fmt, "size": len(payload)}), 409
        import base64
        return jsonify({"duplicate": False, "url": url, "normalized_url": normalized, "final_url": final_url,
                        "width": width, "height": height, "format": fmt, "size": len(payload),
                        "sha256": digest, "preview_data": "data:image/" + fmt.lower() + ";base64," + base64.b64encode(payload).decode("ascii")})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


def destination(body):
    kind = body.get("dataset_type")
    view, condition = body.get("vehicle_view"), body.get("condition")
    if kind == "vehicles" and view in VEHICLE_VIEWS and condition in VEHICLE_CONDITIONS:
        return f"vehicles/{VEHICLE_VIEWS[view]}/{condition}", view, condition
    if kind == "number_plates" and condition in PLATE_CONDITIONS:
        return f"number_plates/{condition}", None, condition
    if kind == "others":
        return "others/not_lorry", None, None
    raise ValueError("Choose a valid dataset type and its required category values.")


@app.post("/api/images")
def save_image():
    body = request.get_json(silent=True) or {}
    url = str(body.get("url", "")).strip()
    try:
        folder, view, condition = destination(body)
        normalized = normalize_url(url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    path = allowed_folders().get(folder)
    if path is None:
        return jsonify({"error": "Invalid destination."}), 400
    with LOCK:
        try:
            payload, _ = fetch_image(url)
            width, height, fmt, phash = inspect_image(payload)
            digest = hashlib.sha256(payload).hexdigest()
            with connect() as db:
                match, method = duplicate_match(db, url, digest, phash)
                if match:
                    record_duplicate(db, url, match, method)
                    db.commit()
                    return jsonify({"error": "Duplicate image detected. Upload blocked.", "duplicate": True,
                                    "method": method, "existing": image_record(match)}), 409
                ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif", "BMP": ".bmp", "TIFF": ".tiff"}[fmt]
                filename = f"{uuid.uuid4().hex}{ext}"
                target = path / filename
                try:
                    target.write_bytes(payload)
                    relpath = target.relative_to(DATASET).as_posix()
                    cursor = db.execute("""INSERT INTO images(original_url,normalized_url,filename,stored_path,dataset_type,vehicle_view,condition,sha256,phash,width,height,file_size,image_format,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (url, normalized, filename, relpath, body["dataset_type"], view, condition, digest, phash, width, height, len(payload), fmt, datetime.now(timezone.utc).isoformat()))
                    db.commit()
                    row = db.execute("SELECT * FROM images WHERE id=?", (cursor.lastrowid,)).fetchone()
                    return jsonify({"image": image_record(row)}), 201
                except sqlite3.IntegrityError:
                    if target.exists():
                        target.unlink()
                    match, method = duplicate_match(db, url, digest, phash)
                    if match:
                        record_duplicate(db, url, match, method)
                        db.commit()
                        return jsonify({"error": "Duplicate image detected. Upload blocked.", "duplicate": True,
                                        "method": method, "existing": image_record(match)}), 409
                    raise
                except Exception:
                    if target.exists():
                        target.unlink()
                    raise
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:
            app.logger.exception("Saving dataset image failed")
            return jsonify({"error": "Could not save the image. Please retry."}), 500


@app.get("/api/images")
def list_images():
    query = request.args.get("q", "").strip()
    kind = request.args.get("type", "")
    view, condition = request.args.get("view", ""), request.args.get("condition", "")
    order = "ASC" if request.args.get("sort") == "oldest" else "DESC"
    page, per_page = max(1, request.args.get("page", 1, type=int)), 24
    where, params = [], []
    if query:
        where.append("(filename LIKE ? OR original_url LIKE ? OR stored_path LIKE ?)")
        params.extend([f"%{query}%"] * 3)
    if kind:
        where.append("dataset_type=?"); params.append(kind)
    if view:
        where.append("vehicle_view=?"); params.append(view)
    if condition:
        where.append("condition=?"); params.append(condition)
    folder = request.args.get("folder", "")
    if folder:
        if folder not in allowed_folders():
            return jsonify({"error": "Invalid dataset folder."}), 400
        where.append("stored_path LIKE ?"); params.append(folder + "/%")
    clause = " WHERE " + " AND ".join(where) if where else ""
    with connect() as db:
        total = db.execute("SELECT COUNT(*) FROM images" + clause, params).fetchone()[0]
        rows = db.execute(f"SELECT * FROM images{clause} ORDER BY created_at {order}, id {order} LIMIT ? OFFSET ?", (*params, per_page, (page-1)*per_page)).fetchall()
    return jsonify({"items": [image_record(r) for r in rows], "total": total, "page": page, "pages": (total+per_page-1)//per_page})


@app.get("/api/images/<int:image_id>/file")
def image_file(image_id):
    with connect() as db:
        row = db.execute("SELECT stored_path,filename FROM images WHERE id=?", (image_id,)).fetchone()
    if not row:
        return jsonify({"error": "Image not found."}), 404
    path = (DATASET / row["stored_path"]).resolve()
    if not path.is_relative_to(DATASET.resolve()) or not path.is_file():
        return jsonify({"error": "Image file is missing."}), 404
    return send_from_directory(path.parent, path.name, conditional=True)


@app.delete("/api/images/<int:image_id>")
def delete_image(image_id):
    with LOCK, connect() as db:
        row = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        if not row:
            return jsonify({"error": "Image not found."}), 404
        path = (DATASET / row["stored_path"]).resolve()
        if not path.is_relative_to(DATASET.resolve()):
            return jsonify({"error": "Invalid stored path."}), 400
        try:
            if path.exists():
                path.unlink()
            db.execute("DELETE FROM images WHERE id=?", (image_id,))
            db.commit()
        except OSError:
            return jsonify({"error": "Could not remove the image file."}), 500
    return jsonify({"ok": True})


@app.get("/api/stats")
def stats():
    start, end = request.args.get("start"), request.args.get("end")
    where, params = [], []
    if start:
        where.append("date(created_at)>=date(?)"); params.append(start)
    if end:
        where.append("date(created_at)<=date(?)"); params.append(end)
    clause = " WHERE " + " AND ".join(where) if where else ""
    with connect() as db:
        rows = db.execute("SELECT * FROM images" + clause, params).fetchall()
        blocked = db.execute("SELECT COUNT(*) FROM duplicate_attempts").fetchone()[0]
        today = db.execute("SELECT COUNT(*) FROM images WHERE date(created_at)=date('now')").fetchone()[0]
        daily = db.execute("SELECT date(created_at) day,COUNT(*) count FROM images" + clause + " GROUP BY day ORDER BY day", params).fetchall()
    counts = {"total": len(rows), "vehicles": 0, "number_plates": 0, "others": 0,
              "today": today, "duplicates_blocked": blocked, "views": {}, "conditions": {}, "plates": {}, "daily": [dict(r) for r in daily]}
    for row in rows:
        counts[row["dataset_type"]] += 1
        if row["vehicle_view"]:
            counts["views"][row["vehicle_view"]] = counts["views"].get(row["vehicle_view"], 0) + 1
        if row["condition"]:
            target = counts["plates"] if row["dataset_type"] == "number_plates" else counts["conditions"]
            target[row["condition"]] = target.get(row["condition"], 0) + 1
    return jsonify(counts)


@app.get("/api/structure")
def structure():
    with connect() as db:
        rows = db.execute("SELECT stored_path,COUNT(*) count FROM images GROUP BY stored_path").fetchall()
    counts = {r["stored_path"]: r["count"] for r in rows}
    tree = []
    for rel, path in allowed_folders().items():
        tree.append({"path": rel, "count": counts.get(rel, 0), "exists": path.is_dir()})
    return jsonify({"folders": tree, "total": sum(item["count"] for item in tree)})


@app.get("/api/duplicates")
def duplicates():
    with connect() as db:
        rows = db.execute("SELECT d.*,i.filename,i.stored_path FROM duplicate_attempts d JOIN images i ON i.id=d.matched_image_id ORDER BY d.created_at DESC LIMIT 200").fetchall()
    return jsonify({"items": [{**dict(row), "destination": "dataset/" + row["stored_path"]} for row in rows]})


@app.get("/api/settings")
def settings():
    with connect() as db:
        count = db.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    return jsonify({"dataset_root": str(DATASET), "max_image_bytes": MAX_BYTES, "similarity_threshold_bits": 3,
                    "storage_exists": DATASET.is_dir(), "database": str(DB), "image_count": count})


if __name__ == "__main__":
    init()
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")), debug=False, threaded=True)
