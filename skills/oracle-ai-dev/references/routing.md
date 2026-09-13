# Routing decision table

| The developer wants to… | Go to path |
|---|---|
| Install / connect / troubleshoot the database | Set up the database |
| Migrate an existing app / database / workload to Oracle | Migrate an existing app |
| Reverse-engineer a model from existing DDL / documents / `$jsonSchema` / Mongoose / DynamoDB | Migrate › ingest, then Model the data (brownfield/review) |
| Move a MongoDB app/workload to Oracle | Migrate › then Documents › MongoDB-compatible API (+ mongosh→SQL translation) |
| Decide tables vs collections vs hybrid vs duality vs summaries — or graph | Model the data |
| Record our org standards, capture a lesson, or reconcile them with the shipped principles | Model the data › [local knowledge](../../oracle-data-modeling/references/local-knowledge.md) |
| Store/query JSON with SQL | Documents › JSON with SQL |
| Serve one dataset as both rows and documents | Documents › JSON Relational Duality |
| Run a MongoDB app or driver against Oracle | Documents › MongoDB-compatible API |
| Add semantic search or RAG | Vector search & RAG |
| Build an agent over the database | AI agents |
| Fix a slow query or regressed plan | Write & tune queries |
