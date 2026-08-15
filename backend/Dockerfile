FROM python:3.12-slim

RUN groupadd --gid 1000 cairn && useradd --uid 1000 --gid cairn --create-home cairn

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh && chown -R cairn:cairn /app

USER cairn

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
