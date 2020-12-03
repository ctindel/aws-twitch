#!/bin/bash

mongo --ssl --host $DOCDB_ENDPOINT:27017 --sslCAFile rds-combined-ca-bundle.pem --username docdb --password password cards --eval 'db.dropDatabase()'

mongoimport --ssl --host $DOCDB_ENDPOINT:27017 --sslCAFile rds-combined-ca-bundle.pem --username docdb --password password --jsonArray --db cards --collection cards --file data/cards.json
