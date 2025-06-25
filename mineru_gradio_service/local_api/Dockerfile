# Dockerfile for the Local MinerU API Service

FROM python:3.10-slim

WORKDIR /opt/api_service

# Copy requirements first for Docker caching
COPY ./local_api/requirements.txt /opt/api_service/requirements.txt

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the MinerU library source code
# This is the 'src/mineru' directory from the project root
COPY ./src/mineru /opt/api_service/src/mineru

# Ensure __init__.py files are present for packages if they were missed.
# src/mineru should already be a package.
# We might need an __init__.py in /opt/api_service/src if Python struggles with finding mineru.
# However, adding /opt/api_service to PYTHONPATH should make `src.mineru` importable.
RUN mkdir -p /opt/api_service/src && touch /opt/api_service/src/__init__.py

ENV PYTHONPATH "${PYTHONPATH}:/opt/api_service"

# Port the API service will run on (default for LOCAL_MINERU_API_BASE in config)
EXPOSE 8080

# Command to run the MinerU Local API service using Uvicorn.
# We need to point uvicorn to the Starlette/FastAPI app instance.
# The `server.py` in `src/mineru` has `create_app()` which returns the Starlette app.
# The `server.run_server` in `projects/mcp/src/mineru/server.py` shows how to run it.
# It uses `uvicorn.run(app_instance, host=host, port=port, log_config=log_config)`.
# We need to ensure `src.mineru.server:create_app()` is callable by uvicorn.
# A common pattern is `module:variable` where variable is the app instance or a factory.
# So, `src.mineru.server:create_app()` should work if `create_app` is the factory.
# The actual app object is usually named `app` within such modules for uvicorn.
# Let's assume `src.mineru.server.app` is the ASGI app object, or we use the factory.
# The `projects/mcp/src/mineru/server.py` defines `app = create_app()`.
CMD ["uvicorn", "src.mineru.server:app", "--host", "0.0.0.0", "--port", "8080"]
