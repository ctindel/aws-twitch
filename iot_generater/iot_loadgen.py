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

# https://docs.aws.amazon.com/documentdb/latest/developerguide/limits.html
CONNECTION_LIMIT=int(os.getenv('DOCDB_CONNECTION_LIMIT', '1500'))
DOCDB_ENDPOINT=os.getenv('DOCDB_ENDPOINT', 'ERROR')
DB_NAME="iot"
DEVICE_COLL_NAME="devices"
DATA_COLL_NAME="device_data"
NUM_WRITER_THREADS=16
PAYLOAD_STATUS_OPTIONS=['STARTING', 'ACTIVE', 'FAILED']

deviceIds = []
threads = []
fake = faker.Faker()

def signal_handler(sig, frame):
    for t in threads:
        t['queue'].put('TERMINATING')

def debug_info():
    if DOCDB_ENDPOINT == 'ERROR':
        raise Exception('Undefined environment variable DOCDB_ENDPOINT')

    print('Running iot_loadgen with %d threads' % (NUM_WRITER_THREADS))
    print('DocumentDB Endpoint: %s' % (DOCDB_ENDPOINT))

class SocketThread (threading.Thread):
    def __init__(self, name, queue):
        threading.Thread.__init__(self)
        self.name = name
        self.queue = queue
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(('0.0.0.0', 5000))
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

class WriterThread (threading.Thread):
   def __init__(self, threadId, name, queue, mongoClient):
      threading.Thread.__init__(self)
      self.threadId = threadId
      self.name = name
      self.queue = queue
      self.mongoClient = mongoClient
   def run(self):
      print ("Starting " + self.name)
      while self.queue.empty():
          deviceId = random.choice(deviceIds)
          location = fake.local_latlng(country_code='US', coords_only=True)
          payload = {
              'deviceId' : deviceId,
              'timestamp' : datetime.datetime.utcnow(),
              'status' : random.choice(PAYLOAD_STATUS_OPTIONS),
              'lastOperator' : fake.name(),
              'location' : {'type' : 'Point', 'coordinates' : [location[1], location[0]]}
          }    
          db[DATA_COLL_NAME].insert_one(payload)
      print ("Exiting " + self.name)

signal.signal(signal.SIGINT, signal_handler)
debug_info()

##Create a MongoDB client, open a connection to Amazon DocumentDB as a replica set and specify the read preference as secondary preferred
mongoClient = pymongo.MongoClient('mongodb://' + DOCDB_ENDPOINT + ':27017/?ssl=true&ssl_ca_certs=' + DOCDB_SSL_CA_CERTS + '&replicaSet=rs0&readPreference=primaryPreferred', maxPoolSize=CONNECTION_LIMIT, username='docdb', password='password') 

##Specify the database to be used
db = mongoClient[DB_NAME]

def readDeviceIds():
    collection = db[DEVICE_COLL_NAME]

    for doc in collection.find():
        deviceIds.append(doc['deviceId'])
    print('Working with %d Device IDs' % (len(deviceIds)))

readDeviceIds()

q = queue.Queue()
socketThread = SocketThread("Thread-Socket", q)
socketThread.start()
threads.append({'thread' : socketThread, 'queue' : q})

for x in range(NUM_WRITER_THREADS):
    threadDict = dict()
    q = queue.Queue()
    thread = WriterThread(x, "Thread-" + str(x), q, mongoClient)
    thread.start()
    threadDict['thread'] = thread
    threadDict['queue'] = q
    threads.append(threadDict)

# Wait for all threads to complete 
for t in threads:
    t['thread'].join()

##Close the connection
mongoClient.close()
