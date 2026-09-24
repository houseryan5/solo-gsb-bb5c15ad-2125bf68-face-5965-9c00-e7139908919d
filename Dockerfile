FROM python:3.11-slim

# 依赖在容器"启动时"通过 entrypoint.sh 安装（见该脚本），
# 构建镜像只拷贝代码，便于修改 requirements.txt 后无需重新 build。
WORKDIR /app

COPY requirements.txt /app/requirements.txt
COPY app /app/app
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV HOST=0.0.0.0 \
    PORT=8000 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# 健康检查直接使用 Python 标准库，镜像内无需安装 curl。
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import os,urllib.request,sys; port=os.getenv('PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3).status==200 else 1)"

ENTRYPOINT ["/app/entrypoint.sh"]
