# Amedia Corpus maker sample code

## Description

This project is a simple pipeline for text corpus compilation using 
docker, gunicorn and falcon. This is a simplified version of a
project used in production by Amedia up to 2021, which also performed various
types of NLP/analysis and classification using tensorflow, keras, spacy,
and other libraries.

The resulting deployment can be used as a simple webserver and/or daemon machine.
At present, the webserver is not really used: it just listens for requests and
responds by returning a simple blank status page.
The daemon part of this project is meant to automate corpus creation.

The project is intended to be deployed on Gcloud-Kubernetes-Docker, but it
could easily be adapted to other platforms.


## Building, running, controlling the container

- one-liner for testing: `docker stop $(docker ps -a -q); docker rm corpus_maker_example ; docker build -t corpus_maker_example:latest . ; docker run --shm-size=512m -i -t -p 9802:9802 --name corpus_maker_example corpus_maker_example:latest`

- building: `docker stop $(docker ps -a -q); docker rm corpus_maker_example ; docker build -t corpus_maker_example:latest . ;`
- attached: `docker run --shm-size=512m -i -t -p 9802:9802 --name corpus_maker_example corpus_maker_example:latest`
- detached: `docker run --shm-size=512m -i -t -d -p 9802:9802 --name corpus_maker_example corpus_maker_example:latest`
- control: `docker ps`
- logs: `docker logs corpus_maker_example`
