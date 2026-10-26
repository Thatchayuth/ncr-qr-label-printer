"""Phase 0 - AX discovery (READ-ONLY).

Connects to the AX SQL Server with SQL Authentication, lists the columns of the
approved table (default AssetTable) and shows a few ASSETID values per company.
Executes only SELECT statements. Nothing is written to AX.

Usage (from the project folder):
    .venv\\Scripts\\python scripts\\poc_ax_discover.py --server AXSQL01 --database AXDB --user qr_reader
    (the password is asked interactively and never printed)

Options:
    --driver "ODBC Driver 17 for SQL Server"   ODBC driver name
    --table AssetTable                         table to inspect
    --company dat                              only sample this DATAAREAID
    --encrypt                                  use an encrypted connection
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qrlabel.domain.errors import AppError  # noqa: E402
from qrlabel.infrastructure.ax.sql_server import SqlServerDataSource  # noqa: E402
from qrlabel.services.query_builder import quote_ident  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", required=True)
    ap.add_argument("--database", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--driver", default="ODBC Driver 17 for SQL Server")
    ap.add_argument("--table", default="AssetTable")
    ap.add_argument("--company", default="")
    ap.add_argument("--encrypt", action="store_true")
    args = ap.parse_args()

    password = getpass.getpass(f"Password for {args.user}: ")
    settings = {
        "server": args.server, "database": args.database, "driver": args.driver, "auth": "sql",
        "username": args.user, "encrypt": args.encrypt, "trust_server_certificate": True,
        "connect_timeout": 10, "query_timeout": 30,
    }
    src = SqlServerDataSource(settings, lambda: password, [args.table])
    try:
        print(src.test_connection())
        cols = src.list_columns(args.table)
        print(f"\n{args.table}: {len(cols)} columns")
        for name, dtype in cols:
            print(f"  {name:<30} {dtype}")

        names = {c.upper() for c, _ in cols}
        if "ASSETID" not in names:
            print("\n!! ASSETID column not found - check the table name / column name with the AX team.")
            return 2

        table = f"[dbo].{quote_ident(args.table)}"
        with src._connect() as conn:
            cur = conn.cursor()
            if "DATAAREAID" in names:
                cur.execute(f"SELECT DATAAREAID, COUNT(*) FROM {table} GROUP BY DATAAREAID ORDER BY DATAAREAID")
                print("\nRows per company (DATAAREAID):")
                for company, count in cur.fetchall():
                    print(f"  {company:<8} {count}")
                where, params = ("WHERE DATAAREAID = ?", [args.company]) if args.company else ("", [])
            else:
                where, params = "", []
            cur.execute(
                f"SELECT TOP (10) ASSETID, LEN(ASSETID) FROM {table} {where} ORDER BY ASSETID", *params
            )
            print("\nSample ASSETID values:")
            for asset_id, length in cur.fetchall():
                print(f"  {asset_id!r:<30} length={length}")
            cur.execute(f"SELECT MAX(LEN(ASSETID)) FROM {table}")
            print(f"\nLongest ASSETID: {cur.fetchone()[0]} characters (needed to size the label text)")
    except AppError as e:
        print(f"\nERROR: {e.message}\n{e.detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
