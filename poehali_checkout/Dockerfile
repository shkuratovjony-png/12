FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "gunicorn -b 0.0.0.0:${PORT:-10000} --workers 2 --timeout 60 app:app"]