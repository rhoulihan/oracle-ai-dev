import java.sql.*;
import java.math.BigDecimal;
public class Main {
  static String cell(Object v) {
    if (v == null) return "null";
    if (v instanceof BigDecimal) return ((BigDecimal)v).toPlainString();
    if (v instanceof Number) return v.toString();
    if (v instanceof Timestamp) return "\"" + ((Timestamp)v).toInstant().toString() + "\"";
    return "\"" + v.toString().replace("\\","\\\\").replace("\"","\\\"") + "\"";
  }
  static String rows(ResultSet rs) throws SQLException {
    StringBuilder sb = new StringBuilder("[");
    int n = rs.getMetaData().getColumnCount();
    boolean first = true;
    while (rs.next()) {
      if (!first) sb.append(","); first = false;
      sb.append("[");
      for (int i = 1; i <= n; i++) { if (i > 1) sb.append(","); sb.append(cell(rs.getObject(i))); }
      sb.append("]");
    }
    sb.append("]"); rs.close(); return sb.toString();
  }
  public static void main(String[] a) throws Exception {
    Connection c = Repository.connect();
    StringBuilder o = new StringBuilder("{");
    o.append("\"get_reservation\":").append(rows(Repository.getReservation(c, new BigDecimal(1500)))).append(",");
    o.append("\"passenger_reservations\":").append(rows(Repository.passengerReservations(c, new BigDecimal(5)))).append(",");
    o.append("\"reservations_by_status\":").append(rows(Repository.reservationsByStatus(c, "CONFIRMED"))).append(",");
    o.append("\"reservation_passenger\":").append(rows(Repository.reservationPassenger(c, new BigDecimal(1500))));
    o.append("}");
    System.out.print(o.toString());
    c.close();
  }
}
