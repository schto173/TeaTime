FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# pymumble is the small Mumble client library the bot is built on. The bot
# includes a fix for the one thing that library does not support on Python 3.12
# and does not need an Opus library, so nothing else has to be installed.
RUN pip install --no-cache-dir pymumble==1.6.1

COPY teatime_mumble.py .

RUN useradd --system --no-create-home teatime
USER teatime

CMD ["python", "teatime_mumble.py", "--host", "mumble-server"]
