FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY db ./db
COPY scripts ./scripts
COPY tests ./tests
COPY .streamlit ./.streamlit
COPY pytest.ini ./pytest.ini

RUN useradd -m app && chown -R app:app /app
USER app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"]

CMD ["streamlit", "run", "app/ui/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
