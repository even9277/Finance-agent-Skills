# 常用命令参考（Linux / PostgreSQL / Docker / uv）

> 路径以仓库根 `Finance/` 为准，按实际主机目录调整。

## PostgreSQL（Docker 内或本机 psql）

```bash
# 进入容器（示例，容器名见 docker-compose）
docker exec -it <postgres_container> psql -U <user> -d <database>

# 补列示例（执行一次）
ALTER TABLE session_summaries
  ADD COLUMN IF NOT EXISTS compressed_user_count INTEGER DEFAULT 0;
```

## 虚拟环境与 uv

```bash
cd /path/to/Finance
python -m venv .venv
source .venv/bin/activate
uv pip install -r backend/requirements.txt   # 若项目采用 uv；否则 pip install -r ...
```

## Docker Compose（数据库）

```bash
cd docker
docker compose up -d
```

完整从 0 启动见仓库 `docs/从0到1恢复启动指令指南.md`。
