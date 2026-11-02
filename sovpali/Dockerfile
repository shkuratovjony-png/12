FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python fix_admin_template.py && python patch_no_menu_images.py && python -m py_compile app.py visuals.py setup_runner.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "setup_runner.py"]
