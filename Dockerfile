FROM python:3.13-slim
WORKDIR /app
COPY watchdog ./watchdog
COPY .env.example ./
RUN useradd --create-home --uid 10001 watchdog
USER watchdog
CMD ["python3", "watchdog/main.py"]
