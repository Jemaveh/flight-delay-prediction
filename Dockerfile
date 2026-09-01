# Image de l'API FastAPI (durée observée). Tag Python figé, pas de tag flottant.
FROM python:3.11.9-slim-bookworm

WORKDIR /app

# LightGBM a besoin de libgomp sur Debian slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-api.txt /app/requirements-api.txt
RUN pip install --no-cache-dir -r /app/requirements-api.txt

COPY config /app/config
COPY src /app/src

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8000

# 0.0.0.0 : écouter hors du conteneur. Pas de --reload en image.
CMD ["python", "-m", "uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
