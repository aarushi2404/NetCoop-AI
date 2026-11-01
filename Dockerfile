FROM python:3.11-slim

# Install Node.js for building the React frontend
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency definitions first
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Generate scenario data
RUN python -m netcoop generate

# Build frontend
RUN cd web && npm install && npm run build

# Default environment variables
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "python -m netcoop serve-api --port ${PORT:-8000} --host 0.0.0.0"]

