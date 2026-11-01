FROM python:3.13-slim
WORKDIR /app
COPY watchdog ./watchdog
COPY .env.example ./
RUN useradd --create-home --uid 10001 watchdog
RUN mkdir -p /var/lib/instabox-watchdog && chown -R watchdog:watchdog /var/lib/instabox-watchdog
USER watchdog
EXPOSE 10000
CMD ["python3", "watchdog/main.py"]
