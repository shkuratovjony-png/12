from __future__ import annotations

import gzip
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta

import boto3
import psycopg
from psycopg.rows import dict_row

CHECK_INTERVAL_SECONDS = 60 * 60
BACKUP_INTERVAL_HOURS = 24
DAILY_RETENTION_DAYS = 35
MONTHLY_RETENTION = 12
PREFIX = "sovpali"


def _env_ready():
    required = [
        "DATABASE_URL",
        "B2_ENDPOINT_URL",
        "B2_KEY_ID",
        "B2_APPLICATION_KEY",
        "B2_BUCKET",
    ]
    return all(os.getenv(k, "").strip() for k in required)


def _client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["B2_ENDPOINT_URL"].strip(),
        aws_access_key_id=os.environ["B2_KEY_ID"].strip(),
        aws_secret_access_key=os.environ["B2_APPLICATION_KEY"].strip(),
    )


def _json_default(value):
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    return str(value)


def _last_success(conn):
    row = conn.execute(
        "SELECT value FROM settings WHERE key=%s", ("backup_last_success_at",)
    ).fetchone()
    if not row:
        return None
    try:
        dt = datetime.fromisoformat(row["value"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _mark_success(conn, stamp):
    conn.execute(
        """INSERT INTO settings(key,value) VALUES(%s,%s)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        ("backup_last_success_at", stamp.isoformat()),
    )
    conn.commit()


def _due(conn, now_utc):
    last = _last_success(conn)
    return last is None or now_utc - last >= timedelta(hours=BACKUP_INTERVAL_HOURS)


def _write_streaming_backup(conn, path, stamp):
    tables = conn.execute(
        """SELECT table_name
           FROM information_schema.tables
           WHERE table_schema='public' AND table_type='BASE TABLE'
           ORDER BY table_name"""
    ).fetchall()
    names = [r["table_name"] for r in tables]

    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as out:
        out.write('{"format":1,"project":"sovpali","created_at":')
        out.write(json.dumps(stamp.isoformat(), ensure_ascii=False))
        out.write(',"tables":{')
        first_table = True
        for table in names:
            if not table.replace("_", "").isalnum():
                continue
            if not first_table:
                out.write(",")
            first_table = False
            out.write(json.dumps(table))
            out.write(":{")

            cols = conn.execute(
                """SELECT column_name, data_type, is_nullable, column_default
                   FROM information_schema.columns
                   WHERE table_schema='public' AND table_name=%s
                   ORDER BY ordinal_position""",
                (table,),
            ).fetchall()
            out.write('"columns":')
            out.write(json.dumps(cols, ensure_ascii=False, default=_json_default))
            out.write(',"rows":[')

            cur = conn.cursor(row_factory=dict_row)
            cur.execute(f'SELECT * FROM "{table}"')
            first_row = True
            for row in cur:
                if not first_row:
                    out.write(",")
                first_row = False
                out.write(json.dumps(row, ensure_ascii=False, default=_json_default))
            cur.close()
            out.write("]}")
        out.write("}}")


def _prune(client, bucket, now_utc):
    daily_cutoff = now_utc - timedelta(days=DAILY_RETENTION_DAYS)
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{PREFIX}/daily/"):
        for obj in page.get("Contents", []):
            lm = obj.get("LastModified")
            if lm and lm.astimezone(timezone.utc) < daily_cutoff:
                client.delete_object(Bucket=bucket, Key=obj["Key"])

    monthly = []
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{PREFIX}/monthly/"):
        monthly.extend(page.get("Contents", []))
    monthly.sort(key=lambda x: x.get("LastModified"), reverse=True)
    for obj in monthly[MONTHLY_RETENTION:]:
        client.delete_object(Bucket=bucket, Key=obj["Key"])


def perform_backup(force=False):
    if not _env_ready():
        print("[backup] disabled: Backblaze B2 credentials are not configured", flush=True)
        return False

    now_utc = datetime.now(timezone.utc)
    db_url = os.environ["DATABASE_URL"].strip()
    bucket = os.environ["B2_BUCKET"].strip()

    with psycopg.connect(db_url, row_factory=dict_row, connect_timeout=15) as conn:
        if not force and not _due(conn, now_utc):
            return False

        tmp = tempfile.NamedTemporaryFile(prefix="sovpali-backup-", suffix=".json.gz", delete=False)
        tmp_path = tmp.name
        tmp.close()
        try:
            _write_streaming_backup(conn, tmp_path, now_utc)
            client = _client()
            daily_key = f"{PREFIX}/daily/{now_utc:%Y/%m}/sovpali-{now_utc:%Y%m%d-%H%M%SZ}.json.gz"
            monthly_key = f"{PREFIX}/monthly/sovpali-{now_utc:%Y-%m}.json.gz"
            client.upload_file(tmp_path, bucket, daily_key)
            client.upload_file(tmp_path, bucket, monthly_key)
            _mark_success(conn, now_utc)
            try:
                _prune(client, bucket, now_utc)
            except Exception as exc:
                print(f"[backup] retention cleanup warning: {exc}", flush=True)
            size = os.path.getsize(tmp_path)
            print(f"[backup] success: {daily_key}; {size} bytes", flush=True)
            return True
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _worker():
    time.sleep(20)
    while True:
        try:
            perform_backup(force=False)
        except Exception as exc:
            print(f"[backup] failed: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(CHECK_INTERVAL_SECONDS)


def start_backup_worker():
    t = threading.Thread(target=_worker, name="sovpali-b2-backup", daemon=True)
    t.start()
    print("[backup] worker started", flush=True)
    return t
