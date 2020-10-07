#!/usr/bin/python 

import pymongo
import sys
import threading
import time
import random
import signal
import queue
import datetime
import faker
import os
import socket

# We'll use the local file if there isn't one passed in an env var
DOCDB_SSL_CA_CERTS=os.getenv('DOCDB_SSL_CA_CERTS', 'rds-combined-ca-bundle.pem')
PORT=int(os.getenv('PORT', '5000'))

# https://docs.aws.amazon.com/documentdb/latest/developerguide/limits.html
CONNECTION_LIMIT=int(os.getenv('DOCDB_CONNECTION_LIMIT', '1500'))
DOCDB_ENDPOINT=os.getenv('DOCDB_ENDPOINT', 'ERROR')
DB_NAME="iot"
DEVICE_COLL_NAME="devices"
DATA_COLL_NAME="device_data"
NUM_WRITER_THREADS=16
PAUSE_SECS=300
PAYLOAD_STATUS_OPTIONS=['STARTING', 'ACTIVE', 'FAILED']

deviceIds = []

def debugInfo():
    if DOCDB_ENDPOINT == 'ERROR':
        raise Exception('Undefined environment variable DOCDB_ENDPOINT')

    print('DocumentDB Endpoint: %s' % (DOCDB_ENDPOINT))

def readWithPause(mongoClient):
    db = mongoClient[DB_NAME]
    collection = db[DEVICE_COLL_NAME]
    deviceId = random.choice(deviceIds)
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(minutes=15)
    items = db[DATA_COLL_NAME].find({'deviceId' : deviceId, 'timestamp' : {'$gte' : start, '$lte' : end}})
    for doc in items:
        print (doc)
        time.sleep(PAUSE_SECS)
        
debugInfo()

##Create a MongoDB client, open a connection to Amazon DocumentDB as a replica set and specify the read preference as secondary preferred
mongoClient = pymongo.MongoClient('mongodb://' + DOCDB_ENDPOINT + ':27017/?ssl=true&ssl_ca_certs=' + DOCDB_SSL_CA_CERTS + '&replicaSet=rs0&readPreference=primaryPreferred', maxPoolSize=CONNECTION_LIMIT, username='docdb', password='password') 

def readDeviceIds(mongoClient):
    db = mongoClient[DB_NAME]
    collection = db[DEVICE_COLL_NAME]

    for doc in collection.find():
        deviceIds.append(doc['deviceId'])
    print('Working with %d Device IDs' % (len(deviceIds)))

readDeviceIds(mongoClient)
readWithPause(mongoClient)

##Close the connection
mongoClient.close()
