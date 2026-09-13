# Data-access layer

Generated from the model's access patterns against the chosen shape.
Every method binds its inputs by name; connections come from the
`DB_USER` / `DB_PASSWORD` / `DB_DSN` environment variables.

## Platforms
- **python** → `repository.py`
- **node** → `repository.js`
- **java** → `Repository.java`
- **go** → `repository.go`
- **dotnet** → `Repository.cs`

## Access patterns
| Pattern | Shape | Binds |
|---|---|---|
| `get_reservation` | relational | `:b0` |
| `passenger_reservations` | relational | `:b0` |
| `reservations_by_status` | relational | `:b0` |
| `reservation_passenger` | relational | `:b0` |

## Schema
`schema.sql` is the CREATE DDL for the optimal schema. Deploy it with
`./deploy.sh` (reads `DB_USER`/`DB_PASSWORD`/`DB_DSN`), or let the code do
it: the Python layer's `ensure_schema(conn)` checks for the schema and
deploys it if absent (returns True if it deployed).
