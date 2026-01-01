# Piston Audio - Docker Image
# 
# Build: docker build -t piston-audio .
# Run:   docker run --privileged --net=host -v /var/run/dbus:/var/run/dbus piston-audio

FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="Piston Audio"
LABEL org.opencontainers.image.description="Raspberry Pi Bluetooth Audio Receiver with Web UI"
LABEL org.opencontainers.image.source="https://github.com/AlexProgrammerDE/piston-audio-ui"
LABEL org.opencontainers.image.licenses="MIT"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    bluez \
    pipewire \
    pipewire-audio-client-libraries \
    wireplumber \
    libspa-0.2-bluetooth \
    libdbus-1-3 \
    libglib2.0-0 \
    dbus \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY pyproject.toml .

# Install the package
RUN pip install --no-cache-dir -e .

# Expose web UI port
EXPOSE 7654

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV DBUS_SYSTEM_BUS_ADDRESS=unix:path=/var/run/dbus/system_bus_socket

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:7654/ || exit 1

# Run the application
ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--host", "0.0.0.0", "--port", "7654"]
