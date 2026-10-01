FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY backend ./backend
COPY quant_us ./quant_us
COPY config ./config
COPY scripts ./scripts

RUN python -m pip install --upgrade pip \
    && python -m pip install .

EXPOSE 8000
CMD ["python", "-m", "backend.app"]
