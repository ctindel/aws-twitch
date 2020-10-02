#!/bin/bash

mongo --ssl --host $DOCDB_ENDPOINT:27017 --sslCAFile rds-combined-ca-bundle.pem --username docdb --password password
