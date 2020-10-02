#!/bin/bash

mongo --ssl --host $DOCDB_ENDPOINT:27017 --sslCAFile rds-combined-ca-bundle.pem --username docdb --password password iot --eval 'db.dropDatabase()'

mongoimport --ssl --host $DOCDB_ENDPOINT:27017 --sslCAFile rds-combined-ca-bundle.pem --username docdb --password password --jsonArray --db iot --collection devices --file data/devices_20000.json

#mongoimport --ssl --host $DOCDB_ENDPOINT:27017 --sslCAFile rds-combined-ca-bundle.pem --username docdb --password password --jsonArray --db iot --collection devices --file data/devices_20000.json

