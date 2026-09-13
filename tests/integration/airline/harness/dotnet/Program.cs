using System;
using System.Collections.Generic;
using System.Text.Json;
using Oracle.ManagedDataAccess.Client;

class Program {
    static List<List<object>> Read(OracleDataReader r) {
        var rows = new List<List<object>>();
        while (r.Read()) {
            var row = new List<object>();
            for (int i = 0; i < r.FieldCount; i++) {
                object v = r.GetValue(i);
                if (v is DBNull) row.Add(null);
                else if (v is DateTime dt) row.Add(dt.ToString("o"));
                else if (v is decimal dec) row.Add(dec);
                else row.Add(v);
            }
            rows.Add(row);
        }
        r.Close();
        return rows;
    }
    static void Main() {
        using var conn = Repository.Connect();
        var outp = new Dictionary<string, List<List<object>>> {
            ["get_reservation"]        = Read(Repository.GetReservation(conn, 1500m)),
            ["passenger_reservations"] = Read(Repository.PassengerReservations(conn, 5m)),
            ["reservations_by_status"] = Read(Repository.ReservationsByStatus(conn, "CONFIRMED")),
            ["reservation_passenger"]  = Read(Repository.ReservationPassenger(conn, 1500m)),
        };
        Console.Write(JsonSerializer.Serialize(outp));
    }
}
