#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Connect with SQLcl (or SQL*Plus) to Oracle AI Database 26ai.
sql {{USER}}/{{PASSWORD}}@//{{HOST}}:{{PORT}}/{{SERVICE}} <<'SQL'
SELECT banner FROM v$version WHERE ROWNUM = 1;
SQL
