# accel-mirror 只读 API —— 多阶段构建后的运行镜像
#
# 构建上下文必须是仓库根目录（因为要拷 references/）：
#   docker build -f server/Dockerfile -t accel-mirror-api .
#   docker run -d --name accel-mirror-api -p 8787:8787 --restart unless-stopped accel-mirror-api
#
# 或者直接用 compose（见 server/docker-compose.yml）。

FROM python:3.12-alpine

LABEL org.opencontainers.image.title="accel-mirror-api" \
      org.opencontainers.image.description="中国大陆网络加速源：只读查询接口" \
      org.opencontainers.image.source="https://github.com/gitfox-enter/accel-mirror" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

# 只拷运行必需的三个文件：数据库、配方、服务代码。
# 没有任何第三方依赖，所以不需要 pip install。
COPY references/mirrors.json references/recipes.json /app/references/
COPY server/accel_mirror_api.py /app/server/

# 以非 root 运行
RUN adduser -D -H -s /sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/v1/health', timeout=4).status == 200 else 1)"

CMD ["python", "server/accel_mirror_api.py", "--host", "0.0.0.0", "--port", "8787", "--quiet"]
