FROM tensorflow/tensorflow:2.2.2-py3

ENV PYTHONIOENCODING='utf-8'
ENV PYTHONUNBUFFERED=TRUE
# set the correct timezone in the docker container
RUN DEBIAN_FRONTEND=noninteractive apt-get update -y && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y tzdata
ENV TZ=Europe/Oslo
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
RUN dpkg-reconfigure -f noninteractive tzdata
RUN date

EXPOSE 9802

RUN pip install --upgrade pip
RUN pip install mwparserfromhell && \
    pip install HTMLParser && \
    pip install falcon && \
    pip install gunicorn && \
    pip install jinja2 && \
    pip install google-cloud-bigquery && \
    pip install google-cloud-storage && \
    pip install google-oauth && \
    pip install srsly

ADD ./app /opt/app
WORKDIR /opt/app

# CMD gunicorn --bind 0.0.0.0:9802 --timeout 120 --workers 1 --threads 2 start:api
CMD [ "python", "./start.py" ]
