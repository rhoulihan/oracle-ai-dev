// Copyright (c) 2026 Oracle and/or its affiliates.
// Connect to Oracle AI Database 26ai with JDBC (ojdbc11 on the classpath).
import java.sql.*;

public class Connect {
  public static void main(String[] args) throws Exception {
    String url = "jdbc:oracle:thin:@//{{HOST}}:{{PORT}}/{{SERVICE}}";
    try (Connection c = DriverManager.getConnection(url, "{{USER}}", "{{PASSWORD}}");
         Statement s = c.createStatement();
         ResultSet r = s.executeQuery("SELECT banner FROM v$version WHERE ROWNUM = 1")) {
      if (r.next()) System.out.println(r.getString(1));
    }
  }
}
