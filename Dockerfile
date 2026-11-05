FROM python:3.12-alpine
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8095 DATABASE_PATH=/data/community.db
RUN addgroup -S community && adduser -S -G community community && mkdir /data && chown community:community /data
COPY --chmod=644 requirements.txt ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir --requirement requirements.txt
COPY --chmod=644 server.py index.html style.css script.js impressum.html datenschutz.html ./
USER community
EXPOSE 8095
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8095/api/me', timeout=2)" || exit 1
CMD ["python", "server.py"]
