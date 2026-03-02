# ============================
# Stage 1: Build the Vue frontend
# ============================
FROM node:22.21.1-alpine3.22 AS build-stage
WORKDIR /app

COPY package.json yarn.lock ./
RUN yarn config set network-timeout 300000
RUN apk add --no-cache g++ make py3-pip
RUN yarn global add node-gyp
RUN yarn install
COPY . .
RUN yarn run build


# ============================
# Stage 2: Python backend + built frontend
# ============================
FROM python:3.12-slim

WORKDIR /app

# Install system build dependencies for Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libffi-dev \
    libssl-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
RUN pip install uv

# Copy Python requirements
COPY requirements.txt ./requirements.txt

# Install backend dependencies using uv
RUN uv pip install --system --no-cache --no-deps -r requirements.txt

# Copy backend source
COPY src/backend/ ./src/backend/

# Copy built frontend from stage 1
COPY --from=build-stage /app/dist ./dist/

EXPOSE 8000

CMD ["uvicorn", "src.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
