FROM python:3.11-slim

WORKDIR /app

# Ensure logs appear immediately
ENV PYTHONUNBUFFERED=1

# Install ffmpeg for video rendering
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt fastapi uvicorn requests python-dotenv

# Copy the rest of the application
COPY . .

# Hugging Face Spaces require port 7860
EXPOSE 7860

# Standard robust Uvicorn launch
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]

