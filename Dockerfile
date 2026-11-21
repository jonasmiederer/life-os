# core image. Non-root. Base image tag is not pinned by digest yet (shortcut: pin before Phase 1c release).
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng poppler-utils \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin lifeos

WORKDIR /app
COPY pyproject.toml ./
COPY core ./core
RUN pip install --no-cache-dir .

USER 10001
ENV LIFEOS_DATA_DIR=/data
ENTRYPOINT ["lifeos"]
CMD ["serve"]
