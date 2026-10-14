#!/usr/bin/env python3
"""要望メモ CLI（VPS: /apps/kanpo_pediatric/venv/bin/python /apps/kanpo_pediatric/tools/requests_cli.py ...）"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parent.parent / "instance" / "requests.db"
DB_PATH = Path(os.environ["REQUESTS_DB_PATH"]) if __import__("os").environ.get("REQUESTS_DB_PATH") else _DEFAULT


def connect():
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_list(args):
    conn = connect()
    if args.status == "all":
        rows = conn.execute(
            "SELECT * FROM request_memos ORDER BY created_at DESC, id DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM request_memos WHERE status = ? ORDER BY created_at DESC, id DESC",
            (args.status,),
        ).fetchall()
    conn.close()
    data = [dict(r) for r in rows]
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        if not data:
            print("(none)")
            return
        for r in data:
            print(
                f"#{r['id']} [{r['status']}] {r['kind']} {r['created_at']}\n"
                f"  {r['content']}\n"
                f"  detail={r['detail']!r} resolution={r['resolution']!r}"
            )


def cmd_show(args):
    conn = connect()
    row = conn.execute(
        "SELECT * FROM request_memos WHERE id = ?",
        (args.id,),
    ).fetchone()
    conn.close()
    if not row:
        print(f"not found: id={args.id}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(dict(row), ensure_ascii=False, indent=2))


def cmd_resolve(args):
    if args.status not in ("done", "skipped"):
        print("--status must be done or skipped", file=sys.stderr)
        sys.exit(1)
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
    cur = conn.execute(
        """
        UPDATE request_memos
        SET status = ?, resolution = ?, resolved_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (args.status, args.note or "", now, now, args.id),
    )
    if cur.rowcount == 0:
        conn.close()
        print(f"not found: id={args.id}", file=sys.stderr)
        sys.exit(1)
    conn.commit()
    row = conn.execute(
        "SELECT * FROM request_memos WHERE id = ?",
        (args.id,),
    ).fetchone()
    conn.close()
    print(json.dumps(dict(row), ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="要望メモ CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="一覧")
    p_list.add_argument("--status", default="open", choices=["open", "all", "done", "skipped"])
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="詳細")
    p_show.add_argument("id", type=int)
    p_show.set_defaults(func=cmd_show)

    p_resolve = sub.add_parser("resolve", help="対応済み/見送り")
    p_resolve.add_argument("id", type=int)
    p_resolve.add_argument("--status", required=True, choices=["done", "skipped"])
    p_resolve.add_argument("--note", default="")
    p_resolve.set_defaults(func=cmd_resolve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
