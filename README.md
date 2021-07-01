# Amedia Data Science Corpus maker sample code

## Description

This project is a micro-service  for text corpus compilation using 
docker, gunicorn and falcon. This is a simplified version of a
project used in production by Amedia, which also performs various
types of NLP/analysis and classification using tensorflow, keras, spacy,
and other libraries.

The resulting deployment can be used as a simple webserver and/or daemon machine.
At present, the webserver is not really used: it just listens for requests and
responds by returning a simple blank status page.

The daemon part of this project is meant to automate corpus creation.

This project follows Amedia's release and deployment standard practices.
The project is intended to be deployed on Gcloud-Kubernetes-Docker, but it
could easily be adapted to other platforms.


## Logic of the corpus-making process


## Building, running, controlling the container

- building: `docker stop $(docker ps -a -q); docker rm ds_corpus_maker_sample ; docker build -t ds_corpus_maker_sample:latest . ;`
- attached: `docker run --shm-size=512m -i -t -p 9802:9802 --name ds_corpus_maker_sample ds_corpus_maker_sample:latest`
- detached: `docker run --shm-size=512m -i -t -d -p 9802:9802 --name ds_corpus_maker_sample ds_corpus_maker_sample:latest`
- control: `docker ps`
- logs: `docker logs ds_corpus_maker_sample`
# ds_corpus_maker_sample
