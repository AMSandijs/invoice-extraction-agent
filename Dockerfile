FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source — only files needed by the Streamlit UI and admin panel.
# function_app/search_indexer.py is imported by sync.py via sys.path.
COPY app.py .
COPY pages/ pages/
COPY agent.py .
COPY uploader.py .
COPY sync.py .
COPY csv_safe.py .
COPY function_app/search_indexer.py function_app/search_indexer.py

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
