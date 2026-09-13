// Generated data-access layer (Oracle JDBC). Binds by name via the Oracle
// extension; reads DB_USER / DB_PASSWORD / DB_DSN from the environment.
import java.sql.*;
import oracle.jdbc.OraclePreparedStatement;

public final class Repository {
  public static Connection connect() throws SQLException {
    return DriverManager.getConnection("jdbc:oracle:thin:@" + System.getenv("DB_DSN"),
        System.getenv("DB_USER"), System.getenv("DB_PASSWORD"));
  }
  static final String SQL_GET_RESERVATION = "SELECT itineraryreservation.reservation_id, itineraryreservation.reservation_status_code, itineraryreservation.ticket_type_code, itineraryreservation.travel_class_code, itineraryreservation.number_in_party FROM itinerary_reservations itineraryreservation WHERE itineraryreservation.reservation_id = :b0";
  // get_reservation — relational shape
  public static ResultSet getReservation(Connection conn, Object b0) throws SQLException {
    OraclePreparedStatement ps = (OraclePreparedStatement) conn.prepareStatement(SQL_GET_RESERVATION);
    ps.setObjectAtName("b0", b0);
    return ps.executeQuery();
  }
  static final String SQL_PASSENGER_RESERVATIONS = "SELECT itineraryreservation.reservation_id, itineraryreservation.reservation_status_code FROM itinerary_reservations itineraryreservation WHERE itineraryreservation.passenger_id = :b0 ORDER BY itineraryreservation.reservation_id ASC";
  // passenger_reservations — relational shape
  public static ResultSet passengerReservations(Connection conn, Object b0) throws SQLException {
    OraclePreparedStatement ps = (OraclePreparedStatement) conn.prepareStatement(SQL_PASSENGER_RESERVATIONS);
    ps.setObjectAtName("b0", b0);
    return ps.executeQuery();
  }
  static final String SQL_RESERVATIONS_BY_STATUS = "SELECT itineraryreservation.reservation_id, itineraryreservation.passenger_id FROM itinerary_reservations itineraryreservation WHERE itineraryreservation.reservation_status_code = :b0 ORDER BY itineraryreservation.reservation_id ASC FETCH FIRST 20 ROWS ONLY";
  // reservations_by_status — relational shape
  public static ResultSet reservationsByStatus(Connection conn, Object b0) throws SQLException {
    OraclePreparedStatement ps = (OraclePreparedStatement) conn.prepareStatement(SQL_RESERVATIONS_BY_STATUS);
    ps.setObjectAtName("b0", b0);
    return ps.executeQuery();
  }
  static final String SQL_RESERVATION_PASSENGER = "SELECT itineraryreservation.reservation_id, passenger.last_name, passenger.email_address FROM itinerary_reservations itineraryreservation JOIN passengers passenger ON itineraryreservation.passenger_id = passenger.passenger_id WHERE itineraryreservation.reservation_id = :b0";
  // reservation_passenger — relational shape
  public static ResultSet reservationPassenger(Connection conn, Object b0) throws SQLException {
    OraclePreparedStatement ps = (OraclePreparedStatement) conn.prepareStatement(SQL_RESERVATION_PASSENGER);
    ps.setObjectAtName("b0", b0);
    return ps.executeQuery();
  }
}