# Copyright (c) 2026 Oracle and/or its affiliates.
# Connect to Oracle AI Database 26ai with python-oracledb (thin mode, no client libs).
#   pip install oracledb
import oracledb

conn = oracledb.connect(
    user="{{USER}}",
    password="{{PASSWORD}}",
    dsn="{{HOST}}:{{PORT}}/{{SERVICE}}",
)
with conn.cursor() as cur:
    cur.execute("SELECT banner FROM v$version WHERE ROWNUM = 1")
    print(cur.fetchone()[0])
conn.close()
