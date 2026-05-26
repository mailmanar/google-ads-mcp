FROM python:3.12-slim

WORKDIR /app

# Install pipx and uv
RUN pip install --no-cache-dir pipx && \
    pipx ensurepath && \
    pip install uv

# Copy project files
COPY . .

# Install dependencies
RUN pip install -e .

# Expose HTTP port
EXPOSE 8045

# Run in HTTP/SSE mode
CMD ["python", "-m", "ads_mcp.server"]

