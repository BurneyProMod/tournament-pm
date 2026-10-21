FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

RUN useradd --create-home app
USER app

EXPOSE 8000
CMD ["uvicorn", "tournament_pm.main:app", "--host", "0.0.0.0", "--port", "8000"]
