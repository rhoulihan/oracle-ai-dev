# Copyright (c) 2026 Oracle and/or its affiliates.
# Connect to the Oracle API for MongoDB with PyMongo.
#   pip install "pymongo>=3.12"
from pymongo import MongoClient

uri = ("mongodb://{{USER}}:{{PASSWORD}}@{{HOST}}:{{MONGO_PORT}}/{{USER}}"
       "?authMechanism=PLAIN&authSource=$external&tls=true"
       "&retryWrites=false&loadBalanced=true")
client = MongoClient(uri, tlsAllowInvalidCertificates=True)
db = client["{{USER}}"]
db.demo.insert_one({"hello": "oracle"})
print("docs:", db.demo.count_documents({}))
