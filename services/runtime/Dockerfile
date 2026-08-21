FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN pip install --no-cache-dir uv==0.8.14

COPY pyproject.toml uv.lock ./
COPY services/runtime/pyproject.toml services/runtime/pyproject.toml
RUN uv sync --frozen --no-dev --package veritas-runtime

COPY services/runtime/src services/runtime/src

RUN addgroup --system veritas && adduser --system --ingroup veritas veritas \
    && chown -R veritas:veritas /app
USER veritas

ENV PYTHONPATH=/app/services/runtime/src \
    PORT=8080

EXPOSE 8080

CMD ["uvicorn", "veritas_runtime.api:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]

