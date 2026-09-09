FROM python:3.12-slim AS base

WORKDIR /srv

RUN adduser --disabled-password --gecos "" --uid 10001 appuser

COPY app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app/main.py ./app/main.py
COPY app/__init__.py ./app/__init__.py

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
