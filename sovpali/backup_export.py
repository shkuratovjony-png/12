from __future__ import annotations

import gzip
import json
import os
import tempfile
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    return str(value)


def create_backup_file():
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        raise RuntimeError("DATABASE_URL is not configured")

    stamp = datetime.now(timezone.utc)
    tmp = tempfile.NamedTemporaryFile(
        prefix="sovpali-backup-", suffix=".json.gz", delete=False
    )
    path = tmp.name
    tmp.close()

    try:
        with psycopg.connect(db_url, row_factory=dict_row, connect_timeout=15) as conn:
            tables = conn.execute(
                """SELECT table_name
                   FROM information_schema.tables
                   WHERE table_schema='public' AND table_type='BASE TABLE'
                   ORDER BY table_name"""
            ).fetchall()
            names = [row["table_name"] for row in tables]

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

        filename = f"sovpali-backup-{stamp:%Y%m%d-%H%M%SZ}.json.gz"
        return path, filename
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
