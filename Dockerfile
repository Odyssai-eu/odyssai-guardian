# Odyssai Guardian — self-contained detection sidecar.
# The GLiNER model + DSPy program are baked into the image so an install is
# `docker compose up` with zero runtime downloads and zero hardcoded endpoint.
FROM python:3.11-slim

WORKDIR /app

# System deps for tokenizers / torch wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the GLiNER model into the image (stage 1 works fully offline).
RUN python -c "from gliner2 import GLiNER2; GLiNER2.from_pretrained('fastino/gliner2-privacy-filter-PII-multi')"

COPY server.py contextual.py ./
COPY data/contextual_seed.jsonl ./data/

# Stage 1 never fetches at runtime.
ENV HF_HUB_OFFLINE=1
EXPOSE 8084

# No LLM endpoint baked in — the stage-2 endpoint is supplied per request by
# the caller (the add-on config). Nothing to configure in the image.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8084"]
