#!/bin/env python

import json
import logging
import os
import string
import sys
import time
import boto3
import datetime
import queue
import threading
import socket
import signal
from bson import json_util
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from elasticsearch import Elasticsearch                                        
import urllib.request  

db_client = None                        # DocumentDB client - used as source 
es_client = None                        # ElasticSearch client - used as target 
threads = []

docdb_endpoint = os.getenv('DOCDB_ENDPOINT', 'ERROR')
es_uri = os.getenv('ELASTICSEARCH_URI', 'ERROR')

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

DOCDB_USER = 'docdb'
DOCDB_PASSWORD = 'password'
DOCDB_STATE_DB = 'repl'
DOCDB_STATE_COLLECTION = 'state'
DOCDB_SSL_CA_CERTS=os.getenv('DOCDB_SSL_CA_CERTS', 'rds-combined-ca-bundle.pem')
DOCDB_CONNECTION_LIMIT=int(os.getenv('DOCDB_CONNECTION_LIMIT', '1500'))
PORT=int(os.getenv('PORT', '5000'))
WATCHED_DB_NAME = 'twitch'
WATCHED_COLLECTION_NAME = 'demo'
STATE_SYNC_COUNT = 1
MAX_LOOP=1

# The error code returned when data for the requested resume token has been deleted
TOKEN_DATA_DELETED_CODE = 136

def signalHandler(sig, frame):
    for t in threads:
        t['queue'].put('TERMINATING')

class SocketThread (threading.Thread):
    def __init__(self, name, queue):
        threading.Thread.__init__(self)
        self.name = name
        self.queue = queue
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(('0.0.0.0', PORT))
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.settimeout(1) # timeout for listening
        self.sock.listen(1)

    def run(self):
        print ("Starting " + self.name)
        while self.queue.empty():
            try:
                connection, client_address = self.sock.accept()
            except socket.timeout:
                pass

        print ("Exiting " + self.name)

class WorkerThread (threading.Thread):
    def __init__(self, name, queue):
        threading.Thread.__init__(self)
        self.name = name
        self.queue = queue

    def read(self):
        deviceId = random.choice(deviceIds)
        end = datetime.datetime.utcnow()
        start = end - datetime.timedelta(minutes=15)
        items = db[DATA_COLL_NAME].find({'deviceId' : deviceId, 'timestamp' : {'$gte' : start, '$lte' : end}})
        for doc in items:
            print (doc)

    def run(self):
        while self.queue.empty():
            self.replicate()
            time.sleep(10)

    def replicate(self):
        """Read any new events from DocumentDB and apply them to an streaming/datastore endpoint."""
    
        global WATCHED_DB_NAME
        global WATCHED_COLLECTION_NAME
        global MAX_LOOP
        global STATE_SYNC_COUNT
    
        events_processed = 0
        canary_record = None
    
        try:
            es_client = get_es_client()
            es_index = WATCHED_DB_NAME + '-' + WATCHED_COLLECTION_NAME
            logger.debug('ES client set up for index: ' + es_index)
        
            # DocumentDB watched collection set up
            db_client = get_db_client()
            collection_client = db_client[WATCHED_DB_NAME][WATCHED_COLLECTION_NAME]
            logger.debug('Watching collection {}'.format(collection_client))
        
            # DocumentDB sync set up
            last_processed_id = get_last_processed_id()
            logger.debug("last_processed_id: {}".format(last_processed_id))
        
            with collection_client.watch(full_document='updateLookup', resume_after=last_processed_id) as change_stream:
                i = 0
        
                if last_processed_id is None:
                    canary_record = insertCanary()
                    deleteCanary()
        
                while change_stream.alive and i < MAX_LOOP:
                    logger.debug('i: {}'.format(i))
                    
                    i += 1
                    change_event = change_stream.try_next()
                    logger.debug('Event: {}'.format(change_event))
        
#                    if last_processed_id is None:
#                        if change_event['operationType'] == 'delete':
#                            store_last_processed_id(change_stream.resume_token)
#                            last_processed_id = change_event['_id']['_data']
#                        continue
                        
                    if change_event is None:
                        logger.debug("none")
                        break
                    else:
                        op_type = change_event['operationType']
                        op_id = change_event['_id']['_data']
        
                        if op_type in ['insert', 'update']:             
                            doc_body = change_event['fullDocument']
                            doc_id = str(doc_body.pop("_id", None))
                            readable = datetime.datetime.fromtimestamp(change_event['clusterTime'].time).isoformat()
                            # !!! Why would we do this?
                            #doc_body.update({'operation':op_type,'timestamp':str(change_event['clusterTime'].time),'timestampReadable':str(readable)})
                            payload = {'_id':doc_id}
                            payload.update(doc_body)
        
                            logger.debug(json_util.dumps(doc_body))
                            # Publish event to ES   ################## evaluate if re-indexing the whole document is the best approach for updates #####################
                            es_client.index(index=es_index,id=doc_id,body=json_util.dumps(doc_body))   
        
                            logger.debug('Processed event ID {}'.format(op_id))
        
                        elif op_type == 'delete':
                            #try:
                            doc_id = str(change_event['documentKey']['_id'])
                            readable = datetime.datetime.fromtimestamp(change_event['clusterTime'].time).isoformat()
                            payload = {'_id':doc_id,'operation':op_type,'timestamp':str(change_event['clusterTime'].time),'timestampReadable':str(readable)}
        
                            # Delete event from ES
                            es_client.delete(es_index, doc_id)
                            logger.debug('Processed event ID {}'.format(op_id))
        
                        events_processed += 1
        
                        if events_processed >= STATE_SYNC_COUNT:
                            # To reduce DocumentDB IO, only persist the stream state every N events
                            logger.debug('events processed')
                            store_last_processed_id(change_stream.resume_token)
                            logger.debug('Synced token {} to state collection'.format(change_stream.resume_token))
    
        except OperationFailure as of:
            if of.code == TOKEN_DATA_DELETED_CODE:
                # Data for the last processed ID has been deleted in the change stream,
                # Store the last known good state so our next invocation
                # starts from the most recently available data
                store_last_processed_id(None)
            raise
    
        except Exception as ex:
            logger.error('Exception in executing replication: {}'.format(ex))
            raise
    
        else:
            
            if events_processed > 0:
    
                store_last_processed_id(change_stream.resume_token)
                logger.debug('Synced token {} to state collection'.format(change_stream.resume_token))
            else:
                if canary_record is not None:
                    return{
                        'statusCode': 202,
                        'description': 'Success',
                        'detail': json.dumps('Canary applied. No records to process.')
                    }
                else:
                    return{
                        'statusCode': 201,
                        'description': 'Success',
                        'detail': json.dumps('No records to process.')
                    }
signal.signal(signal.SIGINT, signalHandler)

def debugInfo():
    global docdb_endpoint
    global es_uri

    if docdb_endpoint == 'ERROR':
        raise Exception('Undefined environment variable DOCDB_ENDPOINT')
    if es_uri == 'ERROR':
        raise Exception('Undefined environment variable ELASTICSEARCH_URI')

    logger.info('DocumentDB Endpoint: %s' % (docdb_endpoint))
    logger.info('Elasticsearch URI: %s' % (es_uri))
    logger.info('Replicating %s.%s' % (WATCHED_DB_NAME, WATCHED_COLLECTION_NAME))

def get_db_client():
    """Return an authenticated connection to DocumentDB"""
    # Use a global variable so Lambda can reuse the persisted client on future invocations
    global db_client
    global docdb_endpoint
    global DOCDB_USER
    global DOCDB_PASSWORD
    global DOCDB_SSL_CA_CERTS
    global DOCDB_CONNECTION_LIMIT

    if db_client is None:
        logger.debug('Creating new DocumentDB client.')

        try:
            db_client = MongoClient('mongodb://' + docdb_endpoint + ':27017/?ssl=true&ssl_ca_certs=' + DOCDB_SSL_CA_CERTS + '&replicaSet=rs0&readPreference=primaryPreferred', maxPoolSize=DOCDB_CONNECTION_LIMIT, username=DOCDB_USER, password=DOCDB_PASSWORD)
            # force the client to connect
            #db_client.admin.command('ismaster')
            #db_client["admin"].authenticate(name=DOCDB_USER, password=DOCDB_USER)

            logger.debug('Successfully created new DocumentDB client.')
        except Exception as ex:
            logger.error('Failed to create new DocumentDB client: {}'.format(ex))
            raise
    return db_client

def get_es_certificate():                           
    """Gets the certificate to connect to ES."""
    try:
        logger.debug('Getting Amazon Root CA certificate.')
        url = 'https://www.amazontrust.com/repository/AmazonRootCA1.pem'
        urllib.request.urlretrieve(url, '/tmp/AmazonRootCA1.pem')
    except Exception as ex:
        logger.error('Failed to download certificate to connect to ES: {}'.format(ex))
        raise

def get_es_client():
    """Return an Elasticsearch client."""
    # Use a global variable so Lambda can reuse the persisted client on future invocations
    global es_client
    global es_uri
    
    if es_client is None:
        logger.debug('Creating Elasticsearch client Amazon root CA')
        """
            Important:
            Use the following method if you Lambda has access to the Internet, 
            otherwise include the certificate within the package. 
        """

        ### Comment this line if certificate is loaded it as part of the function. 
        get_es_certificate()                                

        try:
            es_client = Elasticsearch([es_uri],
                                      use_ssl=True,
                                      ca_certs='/tmp/AmazonRootCA1.pem')
        except Exception as ex:
            logger.error('Failed to create new Elasticsearch client: {}'.format(ex))
            raise

    return es_client

def get_state_collection_client():
    """Return a DocumentDB client for the collection in which we store processing state."""

    logger.debug('Creating state_collection_client.')
    try:
        db_client = get_db_client()
        state_collection = db_client[DOCDB_STATE_DB][DOCDB_STATE_COLLECTION]
        return state_collection
    except Exception as ex:
        logger.error('Failed to create new state collection client: {}'.format(ex))
        raise

def get_last_processed_id():
    """Return the resume token corresponding to the last successfully processed change event."""

    global WATCHED_DB_NAME
    global WATCHED_COLLECTION_NAME

    logger.debug('Returning last processed id.')
    try:
        last_processed_id = None
        state_collection = get_state_collection_client()
        state_doc = state_collection.find_one({'currentState': True, 'dbWatched': WATCHED_DB_NAME, 
            'collectionWatched': WATCHED_COLLECTION_NAME})
        if state_doc is not None:
            if 'lastProcessed' in state_doc: 
                last_processed_id = state_doc['lastProcessed']
        else:
            state_collection.insert({'dbWatched': WATCHED_DB_NAME, 
                'collectionWatched': WATCHED_COLLECTION_NAME, 'currentState': True})
        logger.debug('last_processed_id: {}'.format(last_processed_id))
        return last_processed_id
    except Exception as ex:
        logger.error('Failed to return last processed id: {}'.format(ex))
        raise

def store_last_processed_id(resume_token):
    """Store the resume token corresponding to the last successfully processed change event."""

    global WATCHED_DB_NAME
    global WATCHED_COLLECTION_NAME

    logger.debug('Storing last processed id.')
    try:
        state_collection = get_state_collection_client()
        state_collection.update_one({'dbWatched': WATCHED_DB_NAME, 'collectionWatched': WATCHED_COLLECTION_NAME},
            {'$set': {'lastProcessed': resume_token}})
    except Exception as ex:
        logger.error('Failed to store last processed id: {}'.format(ex))
        raise

def insertCanary():
    """Inserts a canary event for change stream activation"""
    
    global WATCHED_DB_NAME
    global WATCHED_COLLECTION_NAME

    try:
        logger.debug('Inserting canary')
        db_client = get_db_client()
        collection_client = db_client[WATCHED_DB_NAME][WATCHED_COLLECTION_NAME]

        canary_record = collection_client.insert_one({ "op_canary": "canary" })
        logger.debug('Canary inserted.')
    except Exception as ex:
        logger.error('Exception in inserting canary: {}'.format(ex))
        raise

    return canary_record


def deleteCanary():
    """Deletes a canary event for change stream activation"""
    
    global WATCHED_DB_NAME
    global WATCHED_COLLECTION_NAME

    try:
        logger.debug('Deleting canary')
        db_client = get_db_client()
        collection_client = db_client[WATCHED_DB_NAME][WATCHED_COLLECTION_NAME]

        collection_client.delete_one({ "op_canary": "canary" })
        logger.debug('Canary deleted.')
    
    except Exception as ex:
        logger.error('Exception in deleting canary: {}'.format(ex))
        raise

signal.signal(signal.SIGINT, signalHandler)
debugInfo()

q = queue.Queue()
socketThread = SocketThread("Thread-Socket", q)
socketThread.start()
threads.append({'thread' : socketThread, 'queue' : q})

q = queue.Queue()
thread = WorkerThread("Thread-Replicator", q)
thread.start()
threads.append({'thread' : socketThread, 'queue' : q})

# Wait for all threads to complete
for t in threads:
    t['thread'].join()
