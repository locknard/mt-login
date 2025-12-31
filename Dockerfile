FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium is enough for most login flows
RUN playwright install chromium

COPY mt2fa ./mt2fa
COPY templates ./templates
COPY static ./static
COPY main.py .

# TOTP is time sensitive; ensure timezone is correct (host time sync still matters)
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

EXPOSE 8000

CMD ["uvicorn", "mt2fa.web:app", "--host", "0.0.0.0", "--port", "8000"]
