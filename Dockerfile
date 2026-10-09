FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/entrypoint.sh ./entrypoint.sh
RUN useradd --create-home strategy && chown -R strategy:strategy /app
USER strategy
EXPOSE 8000
CMD ["sh", "entrypoint.sh"]
