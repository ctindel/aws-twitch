FROM python:3.7-slim

ADD iot_loadgen.py /tmp
ADD entrypoint.sh /tmp
ADD requirements.txt /tmp
ADD rds-combined-ca-bundle.pem /tmp

RUN pip install -r /tmp/requirements.txt
RUN chmod 755 /tmp/entrypoint.sh

ENTRYPOINT [ "/tmp/entrypoint.sh" ]
