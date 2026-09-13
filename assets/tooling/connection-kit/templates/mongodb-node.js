// Copyright (c) 2026 Oracle and/or its affiliates.
// Connect to the Oracle API for MongoDB with the Node.js mongodb driver.
//   npm install mongodb
const { MongoClient } = require("mongodb");

const uri =
  "mongodb://{{USER}}:{{PASSWORD}}@{{HOST}}:{{MONGO_PORT}}/{{USER}}" +
  "?authMechanism=PLAIN&authSource=$external&tls=true" +
  "&retryWrites=false&loadBalanced=true";

(async () => {
  const client = new MongoClient(uri, { tlsAllowInvalidCertificates: true });
  await client.connect();
  const db = client.db("{{USER}}");
  await db.collection("demo").insertOne({ hello: "oracle" });
  console.log("docs:", await db.collection("demo").countDocuments());
  await client.close();
})();
