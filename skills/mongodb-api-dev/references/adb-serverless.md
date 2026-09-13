# MongoDB API on Autonomous Database Serverless

On ADB Serverless the API is managed — no ORDS to install — but it has a
hard network prerequisite and its own privilege set. Everything here is
verified against the current ADB Serverless documentation (2026-08).

## Enablement — and the network prerequisite that gates it

The API **cannot run with the default "secure access from everywhere"
configuration.** Network access must first be one of:

- **Secure access from allowed IPs and VCNs only** (ACLs), or
- **Private endpoint access only.**

With that in place, enable per instance from the OCI console: the
**Tool configuration** tab → Edit tool configuration → MongoDB API row →
Enabled → Apply (the instance passes through the Updating lifecycle
state). At provision or clone time, the same switch lives under Show
advanced options → **Tools**.

## The ADB-S privilege set

A schema reachable through the API needs, beyond ORDS enablement:
`SODA_APP`, `CREATE TABLE`, and `CREATE SESSION` — all contained in
`DWROLE` — plus quota on tablespace `DATA`. Optionally grant `EXECUTE ON
CS_SESSION` so index creation runs automatically in parallel. The user
model itself (PLAIN auth, admin schemas) is in
[users-auth.md](users-auth.md).

## Private-endpoint connections

When the database sits on a private endpoint, the network does the work:

- The subnet's security rules (NSG or security list) must allow **TCP
  27017 ingress to the database and egress back** from wherever clients
  live.
- From outside the VCN, tunnel through a bastion:
  `ssh -i <key> -C -L 27017:<db-private-ip>:27017 opc@<bastion>` (add
  more `-L` pairs for HTTPS; use a local port above 1024 to avoid
  running the tunnel privileged).
- **Connect by NAME, not IP.** The TLS certificate is issued to the
  database's FQDN, and Oracle's private-endpoint doc prescribes
  hosts-file entries mapping **both** FQDNs to the private IP — the
  `.oraclecloud.com` name (SQL*Net) and the `.oraclecloudapps.com` name
  (ORDS-served tools, which is what the MongoDB API connection string
  uses). OCI private DNS is the documented alternative to hosts-file
  entries. Without this, tools return 404s or certificate-validation
  failures.

## Choosing a tier — a documented gap

Oracle publishes **no comparison of AJD vs ATP vs ADW for MongoDB API
workloads** (feature differences, cost, or AJD's document-store limits)
— the choice is currently **undocumented** and is an open question with
Oracle. Until that lands, state the gap rather than inferring; all three
tiers expose the API subject to the enablement above.

## Sources

- Using Oracle Database API for MongoDB — Autonomous Database Serverless
  documentation (enablement, network prerequisite, privileges).
- Autonomous Database Serverless private-endpoint documentation
  (supported tools list, hosts-file FQDN mapping, private DNS).
