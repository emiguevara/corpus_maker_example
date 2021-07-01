# as of 2020/11/02, and since 2020/01, the latest-py3 tag installs Tensorflow 2.1.0, for Tf 1.15.4, use tag 1.15.4-py3
# FROM tensorflow/tensorflow:latest-py3
FROM tensorflow/tensorflow:2.2.2-py3
# FROM tensorflow/tensorflow:1.15.5-py3

# LANG='en_US.UTF-8' LANGUAGE='en_US:en' LC_ALL='en_US.UTF-8'
ENV PYTHONIOENCODING='utf-8'
# write out to logs inmediately
ENV PYTHONUNBUFFERED=TRUE

EXPOSE 9802

# try setting the correct timezone in the docker container
RUN DEBIAN_FRONTEND=noninteractive apt-get update -y && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y tzdata
ENV TZ=Europe/Oslo
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
RUN dpkg-reconfigure -f noninteractive tzdata
RUN date

ADD ./app /opt/app
WORKDIR /opt/app

# only install pip and our packages
# everything else is handled by dependencies in ds_nlp_utils
RUN pip install --upgrade pip
#RUN pip install "data/ds_nlp_utils-0.0.2.tar.gz" && \
#    pip install "data/nb_amedia_nlp_1000-3.1.0.tar.gz"
RUN pip install mwparserfromhell && \
    pip install HTMLParser && \
    pip install falcon && \
    pip install gunicorn && \
    pip install jinja2 && \
    pip install google-cloud-bigquery && \
    pip install google-cloud-storage && \
    pip install google-oauth && \
    pip install srsly

# increase gunicorn timeout for requests of around 1000 acp_articles
# 100 about 10s, 1k should be 100s, exaggerate by excess
# --workers 2 for simple duplication/concurrency (Tensorflow is not threadsafe)
# CMD gunicorn --bind 0.0.0.0:9802 --timeout 120 --workers 1 --threads 2 start:api
CMD [ "python", "./start.py" ]