# Stage 1: Build the Vue frontend
FROM node:22.21.1-alpine3.22 AS build-stage
WORKDIR /app

COPY package.json yarn.lock ./
RUN yarn config set network-timeout 300000
RUN apk add g++ make py3-pip
RUN yarn global add node-gyp
RUN yarn install
COPY . .
RUN yarn run build

# Stage 2: Production image with Python backend serving the built frontend
FROM python:3.12-slim

WORKDIR /app

# Install backend dependencies
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY src/backend/ ./src/backend/

# Copy built frontend from stage 1
COPY --from=build-stage /app/dist ./dist/

EXPOSE 8000

CMD ["uvicorn", "src.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
