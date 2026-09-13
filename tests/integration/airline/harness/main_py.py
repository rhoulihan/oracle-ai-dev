# Python harness: run each generated datalayer method, emit positional rows as JSON.
import json, sys, datetime, decimal
import repository as repo

def norm(v):
    if isinstance(v, decimal.Decimal):
        f = float(v); return int(f) if f.is_integer() else f
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    return v

def rows_to_arrays(rows):
    # rows are dicts keyed by column name (SELECT order preserved in cx cursor)
    return [[norm(v) for v in r.values()] for r in rows]

conn = repo.connect()
out = {
    "get_reservation":        rows_to_arrays(repo.get_reservation(conn, b0=1500)),
    "passenger_reservations": rows_to_arrays(repo.passenger_reservations(conn, b0=5)),
    "reservations_by_status": rows_to_arrays(repo.reservations_by_status(conn, b0="CONFIRMED")),
    "reservation_passenger":  rows_to_arrays(repo.reservation_passenger(conn, b0=1500)),
}
conn.close()
json.dump(out, sys.stdout, sort_keys=True)
