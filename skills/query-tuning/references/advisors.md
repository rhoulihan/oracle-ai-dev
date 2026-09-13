# Advisors and packs on Free

**Runtime-verified (gap-1): Oracle AI Database 26ai Free includes both the
Diagnostics Pack and the Tuning Pack.** `CONTROL_MANAGEMENT_PACK_ACCESS` defaults
to `DIAGNOSTIC+TUNING` on the Free image. So these all work:

| Tool | Package / view | Use |
|---|---|---|
| AWR | `DBMS_WORKLOAD_REPOSITORY` | workload snapshots + reports |
| ASH | `V$ACTIVE_SESSION_HISTORY` | active session sampling |
| ADDM | `DBMS_ADDM` | automatic diagnostics |
| SQL Tuning Advisor | `DBMS_SQLTUNE` | recommends indexes / profiles / rewrites |
| SQL Access Advisor | `DBMS_ADVISOR` | index/MV recommendations (regular users; QSM-00794 on SYS-owned tables) |
| Real-Time SQL Monitor | `DBMS_SQL_MONITOR`, `V$SQL_MONITOR` | live statement monitoring |
| SQL Plan Management | baselines + evolve | plan stability |

## NOT licensed on Free — do not recommend these
- **Real Application Testing** (SQL Performance Analyzer, DB Replay)
- **Automatic Indexing**
- **Automatic / real-time SQL Plan Management**

## Note on oracle/skills
The upstream `oracle/skills` performance content carries licensing warnings that
are *misleading for Free* ("AWR requires a license…") — on Free the packs are
included. This skill corrects that.

## Sources
- Oracle Database Licensing Information (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/dblic/
