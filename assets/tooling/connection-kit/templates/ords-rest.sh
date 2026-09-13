#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Talk to the database over ORDS REST (AutoREST / SODA for REST). Basic auth uses
# the DB schema credentials. {{ORDS_URL}} is the ORDS base, e.g. http://{{HOST}}:8080/ords
set -euo pipefail
BASE="{{ORDS_URL}}"

# SODA for REST: list collections in the {{USER}} schema.
curl -sk -u "{{USER}}:{{PASSWORD}}" "${BASE}/{{USER}}/soda/latest/" | head -c 400; echo

# Create a collection and insert a document.
curl -sk -u "{{USER}}:{{PASSWORD}}" -X PUT "${BASE}/{{USER}}/soda/latest/demo"
curl -sk -u "{{USER}}:{{PASSWORD}}" -H 'Content-Type: application/json' \
  -X POST "${BASE}/{{USER}}/soda/latest/demo" -d '{"hello":"oracle"}'
