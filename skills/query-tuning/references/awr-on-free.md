# AWR on the Free container

The gotcha (gap-1, verified): connected to **FREEPDB1**, `DBA_HIST_SNAPSHOT` is
empty because CDB-root snapshots are invisible from inside the PDB, so SQLcl's
`awr create text` initially finds nothing to report.

## The bracket-snapshot pattern (canonical workflow)
Create PDB-local snapshots around the workload you want to analyze:

```sql
-- inside FREEPDB1
EXEC DBMS_WORKLOAD_REPOSITORY.CREATE_SNAPSHOT;   -- start bracket
-- ... run the workload ...
EXEC DBMS_WORKLOAD_REPOSITORY.CREATE_SNAPSHOT;   -- end bracket
```

Then generate the report between the two snap IDs (SQLcl `awr create text`, or
`DBMS_WORKLOAD_REPOSITORY.AWR_REPORT_TEXT`). With PDB-local snapshots present, the
report produces a full PDB AWR.

## Reachable through MCP
`CREATE_SNAPSHOT` and the report generation run through the SQLcl MCP `sql_run`
tool at restrict level 4.

## Sources
- Oracle Database Licensing Information (26ai), management-pack matrix — https://docs.oracle.com/en/database/oracle/oracle-database/26/dblic/
- Pack availability on Free — runtime-verified on the 26ai Free container, 2026.
