FROM python:3.12-slim AS base

WORKDIR /srv

RUN adduser --disabled-password --gecos "" --uid 10002 observer

COPY observer/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY observer/__init__.py ./observer/__init__.py
COPY observer/main.py ./observer/main.py
COPY observer/k8s_client.py ./observer/k8s_client.py
COPY observer/static ./observer/static

USER observer

EXPOSE 8080

CMD ["uvicorn", "observer.main:app", "--host", "0.0.0.0", "--port", "8080"]
