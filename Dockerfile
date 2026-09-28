# Image de la démo publique de l'agent (voir deploy/README.md).
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEMO_MODE=true

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Seulement ce qu'il faut pour servir la démo : code, interface et
# fichiers d'exemple. Ni contrats, ni données, ni .env.
COPY api.py .
COPY src ./src
COPY public ./public
COPY data/samples ./data/samples

# Utilisateur sans privilèges, propriétaire des seuls dossiers de travail.
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p uploads data/archive demo_workspaces \
    && chown -R agent uploads data demo_workspaces
USER agent

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
