FROM python:3.11-slim

# Thiết lập múi giờ Việt Nam
ENV TZ=Asia/Ho_Chi_Minh

WORKDIR /app

# Copy requirement trước để cache layer tải package
COPY requirements.txt .

# Nâng cấp pip và cài đặt dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source code vào image
COPY . .

# Expose port
EXPOSE 8000

# Chạy app FastAPI bằng Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]