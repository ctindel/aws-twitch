#!/bin/bash

mongo --ssl --host $DOCDB_ENDPOINT:27017 --sslCAFile rds-combined-ca-bundle.pem --username docdb --password password twitch --eval 'db.dropDatabase()'

mongo --ssl --host $DOCDB_ENDPOINT:27017 --sslCAFile rds-combined-ca-bundle.pem --username docdb --password password repl --eval 'db.dropDatabase()'

mongo --ssl --host $DOCDB_ENDPOINT:27017 --sslCAFile rds-combined-ca-bundle.pem --username docdb --password password twitch --eval 'db.adminCommand({modifyChangeStreams: 1, database: "", collection: "", enable: true});'

curl -X DELETE $ELASTICSEARCH_URI/twitch-demo
echo
