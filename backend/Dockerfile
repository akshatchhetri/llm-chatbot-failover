FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /venv && /venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
ENV PATH="/venv/bin:$PATH" PYTHONUNBUFFERED=1 DATABASE_URL=sqlite:////data/app.db
WORKDIR /srv
COPY --from=builder /venv /venv
COPY app ./app
RUN mkdir -p /data && useradd -m app && chown app /data
USER app
VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
