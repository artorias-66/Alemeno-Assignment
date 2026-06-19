FROM python:3.11-slim

WORKDIR /app

# Add non-root user for security best practices
RUN groupadd -r alemeno && useradd -r -g alemeno alemeno

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Change ownership of app directory and switch to non-root user
RUN chmod +x start.sh && chown -R alemeno:alemeno /app
USER alemeno

CMD ["./start.sh"]
