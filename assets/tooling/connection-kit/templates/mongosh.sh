#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Connect to the Oracle API for MongoDB with mongosh. TLS is on by default
# (self-signed locally, hence --tlsAllowInvalidCertificates).
mongosh --tlsAllowInvalidCertificates \
  "mongodb://{{USER}}:{{PASSWORD}}@{{HOST}}:{{MONGO_PORT}}/{{USER}}?authMechanism=PLAIN&authSource=\$external&tls=true&retryWrites=false&loadBalanced=true" \
  --eval 'db.hello().ok'
