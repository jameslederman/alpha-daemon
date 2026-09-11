FROM python:3.14-slim

WORKDIR /app

COPY requirements-api.txt .

RUN pip install --no-cache-dir -r requirements-api.txt

COPY src/alpha-daemon ./src/alpha-daemon

ENV PYTHONPATH=/app/src/alpha-daemon

EXPOSE 8000

CMD ["uvicorn", "api:app", "--app-dir", "src/alpha-daemon", "--host", "0.0.0.0", "--port", "8000"]