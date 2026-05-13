FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/home/user/app/src

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates espeak-ng \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 user

WORKDIR /home/user/app

COPY --chown=user requirements.txt pyproject.toml README.md ./
COPY --chown=user src ./src
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e .

COPY --chown=user app.py ./
COPY --chown=user assets ./assets
COPY --chown=user config ./config
COPY --chown=user credentials/.gitkeep ./credentials/.gitkeep
COPY --chown=user outputs/.gitkeep ./outputs/.gitkeep

USER user

EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
