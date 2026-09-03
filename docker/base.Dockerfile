# syntax=docker/dockerfile:1.7

FROM python:3.13-slim AS base

COPY docker/apt/configure-debian-mirrors.sh /usr/local/bin/configure-debian-mirrors
RUN sh /usr/local/bin/configure-debian-mirrors

ENV PYTHONPATH="${PYTHONPATH}:/app" \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
