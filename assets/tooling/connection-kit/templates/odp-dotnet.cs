// Copyright (c) 2026 Oracle and/or its affiliates.
// Connect to Oracle AI Database 26ai with ODP.NET Core.
//   dotnet add package Oracle.ManagedDataAccess.Core
using Oracle.ManagedDataAccess.Client;

var cs = "User Id={{USER}};Password={{PASSWORD}};" +
         "Data Source={{HOST}}:{{PORT}}/{{SERVICE}}";
using var conn = new OracleConnection(cs);
conn.Open();
using var cmd = new OracleCommand("SELECT banner FROM v$version WHERE ROWNUM = 1", conn);
Console.WriteLine(cmd.ExecuteScalar());
