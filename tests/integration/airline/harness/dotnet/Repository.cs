// Generated data-access layer (ODP.NET managed). BindByName; reads the
// connection from DB_USER / DB_PASSWORD / DB_DSN.
using System;
using Oracle.ManagedDataAccess.Client;

public static class Repository {
  public static OracleConnection Connect() {
    // read into locals first — nested quotes inside an interpolated string are invalid C#
    var u = Environment.GetEnvironmentVariable("DB_USER");
    var p = Environment.GetEnvironmentVariable("DB_PASSWORD");
    var d = Environment.GetEnvironmentVariable("DB_DSN");
    var c = new OracleConnection($"User Id={u};Password={p};Data Source={d}");
    c.Open(); return c;
  }
  const string SqlGetReservation = @"SELECT itineraryreservation.reservation_id, itineraryreservation.reservation_status_code, itineraryreservation.ticket_type_code, itineraryreservation.travel_class_code, itineraryreservation.number_in_party
FROM itinerary_reservations itineraryreservation
WHERE itineraryreservation.reservation_id = :b0";
  // get_reservation — relational shape
  public static OracleDataReader GetReservation(OracleConnection conn, object b0) {
    var cmd = new OracleCommand(SqlGetReservation, conn) { BindByName = true };
    cmd.Parameters.Add("b0", b0);
    return cmd.ExecuteReader();
  }
  const string SqlPassengerReservations = @"SELECT itineraryreservation.reservation_id, itineraryreservation.reservation_status_code
FROM itinerary_reservations itineraryreservation
WHERE itineraryreservation.passenger_id = :b0
ORDER BY itineraryreservation.reservation_id ASC";
  // passenger_reservations — relational shape
  public static OracleDataReader PassengerReservations(OracleConnection conn, object b0) {
    var cmd = new OracleCommand(SqlPassengerReservations, conn) { BindByName = true };
    cmd.Parameters.Add("b0", b0);
    return cmd.ExecuteReader();
  }
  const string SqlReservationsByStatus = @"SELECT itineraryreservation.reservation_id, itineraryreservation.passenger_id
FROM itinerary_reservations itineraryreservation
WHERE itineraryreservation.reservation_status_code = :b0
ORDER BY itineraryreservation.reservation_id ASC
FETCH FIRST 20 ROWS ONLY";
  // reservations_by_status — relational shape
  public static OracleDataReader ReservationsByStatus(OracleConnection conn, object b0) {
    var cmd = new OracleCommand(SqlReservationsByStatus, conn) { BindByName = true };
    cmd.Parameters.Add("b0", b0);
    return cmd.ExecuteReader();
  }
  const string SqlReservationPassenger = @"SELECT itineraryreservation.reservation_id, passenger.last_name, passenger.email_address
FROM itinerary_reservations itineraryreservation
JOIN passengers passenger ON itineraryreservation.passenger_id = passenger.passenger_id
WHERE itineraryreservation.reservation_id = :b0";
  // reservation_passenger — relational shape
  public static OracleDataReader ReservationPassenger(OracleConnection conn, object b0) {
    var cmd = new OracleCommand(SqlReservationPassenger, conn) { BindByName = true };
    cmd.Parameters.Add("b0", b0);
    return cmd.ExecuteReader();
  }
}