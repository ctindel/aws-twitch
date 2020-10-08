FROM python:3.7-slim

ADD docdb-es-replicator.py /tmp
ADD requirements.txt /tmp
ADD rds-combined-ca-bundle.pem /tmp

RUN pip install -r /tmp/requirements.txt

CMD [ "python", "/tmp/docdb-es-replicator.py" ]
