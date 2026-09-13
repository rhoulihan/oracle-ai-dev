// Copyright (c) 2026 Oracle and/or its affiliates.
// Connect to Oracle AI Database 26ai with node-oracledb (thin mode).
//   npm install oracledb
const oracledb = require("oracledb");

(async () => {
  const conn = await oracledb.getConnection({
    user: "{{USER}}",
    password: "{{PASSWORD}}",
    connectString: "{{HOST}}:{{PORT}}/{{SERVICE}}",
  });
  const r = await conn.execute("SELECT banner FROM v$version WHERE ROWNUM = 1");
  console.log(r.rows[0][0]);
  await conn.close();
})();
