# Pull base image
FROM python:3.11-alpine

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV DEBUG 0
ENV PRODUCTION 1

# install psycopg2
RUN apk update \
    && apk add --virtual build-essential build-base linux-headers \
    && apk add --virtual curl gcc python3-dev musl-dev \
    && apk add postgresql-dev

# install dependencies
COPY ./requirements.txt .
RUN pip install -r requirements.txt

# Add our code
ADD . /opt/yamllms/
WORKDIR /opt/yamllms
