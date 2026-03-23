## 目标与适用范围

这份指南面向新手，目标是在 **Linux + Docker Compose** 上为本项目准备 Phase 3 的数据库环境，并且在 **智星云** 这类“实例可能更换”的云主机场景下，做到 **数据可跨实例保留**。

你将获得：

- **PostgreSQL 16 + pgvector**（`pgvector/pgvector:pg16` 镜像）
- `vector` 扩展与 `uuid-ossp` 扩展已创建（通过 `docker/postgres/init.sql`）
- 后端通过 `DATABASE_URL` 连接；后端启动时会自动建表（开发阶段使用 `create_all`）
- **数据默认保存在系统盘**：使用 Docker 命名卷（`postgres_data`）持久化
- **智星云到期后保留数据**：到期后请使用“从保留磁盘重启（Status=8）”，即可在新实例继续使用同一块磁盘数据

---

## 0. 前置条件（你已安装 Docker，只做检查）

```bash
docker --version
docker compose version
```

如果提示 `permission denied`：

```bash
sudo usermod -aG docker "$USER"
newgrp docker
```

---

## 1. 本项目与数据库的适配点（必须知道）

- **连接串**：后端通过 `DATABASE_URL` 决定连 SQLite 还是 PostgreSQL  
  - PostgreSQL 示例：`postgresql+asyncpg://finance:finance123@localhost:5432/finance_db`
- **建表方式**：开发阶段后端启动会执行 `Base.metadata.create_all()` 自动建表
- **pgvector 初始化**：`docker/postgres/init.sql` 在“首次初始化数据目录”时创建扩展：
  - `CREATE EXTENSION IF NOT EXISTS vector;`
  - `CREATE EXTENSION IF NOT EXISTS "uuid-ossp";`

> 注意：`init.sql` 只会在数据目录首次初始化时自动执行。你如果已有旧数据目录，改了 `init.sql` 不会自动重跑。

---

## 2. 默认推荐（系统盘）：使用 Docker 命名卷持久化 PostgreSQL 数据

### 2.1 原理（先讲结论）

本项目 `docker/docker-compose.yml` 默认使用 Docker 命名卷 `postgres_data`：

```yaml
volumes:
  - postgres_data:/var/lib/postgresql/data
```

这会把 Postgres 数据保存在宿主机（系统盘）的 Docker 数据目录里（常见在 `/var/lib/docker/volumes/...`），容器重建/重启都不会丢数据。

### 2.2 智星云“到期/结束”后如何继续用原数据（关键）

如果你在智星云创建实例时勾选了“**租用结束后保留全部磁盘**”，到期后实例会进入 **Status=8（保留磁盘）**。此时请在控制台选择 **“从保留磁盘重启”**，系统会重新创建新实例，但会继续使用原磁盘数据，因此你的 Docker volumes 和 Postgres 数据也会跟着保留。

如果你不走“从保留磁盘重启”，而是直接新建一个全新实例，那么旧系统盘/旧 Docker volume 通常不会自动带过去，你就会看到“数据丢失”的情况。

---

## 3. 启动 PostgreSQL（pgvector）并验证扩展（docker-compose）

### 3.1 启动

```bash
cd /root/Finance
docker compose -f docker/docker-compose.yml up -d postgres
```

> 第一次会拉取镜像，可能需要几分钟。

### 3.2 看日志

```bash
docker logs finance_postgres --tail 80
```

### 3.3 验证可连接

```bash
docker exec -it finance_postgres psql -U finance -d finance_db -c "SELECT version();"
```

### 3.4 验证 pgvector / uuid-ossp 扩展存在（必须）

```bash
docker exec -it finance_postgres psql -U finance -d finance_db -c "SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector','uuid-ossp') ORDER BY extname;"
```

---

## 4. 让后端连上 PostgreSQL 并自动建表

### 4.1 宿主机运行后端（开发常用）

设置 `backend/.env`：

```bash
DATABASE_URL=postgresql+asyncpg://finance:finance123@localhost:5432/finance_db
```

启动后端：

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 4.2 验证表是否已创建


```bash
docker exec -it finance_postgres psql -U finance -d finance_db -c "\dt"
```

---

## 5. 可选增强：如果你未来加“数据盘”，再迁移到数据盘（更独立、更稳）

系统盘方案的前提是：你每次到期后都使用 **“从保留磁盘重启（Status=8）”** 来恢复原磁盘。

如果你希望“磁盘独立于实例、可单独挂载迁移”，可以后续再加一块数据盘，把 Postgres 数据目录迁移过去并改为 bind mount（见下方步骤）。

---

### 5.1（可选）准备数据盘挂载点

假设你把数据盘挂载到 `/data/finance-postgres`（挂载与 UUID 固定流程略，按云盘通用做法配置即可）。

确保目录权限（常见 uid 999）：

```bash
sudo mkdir -p /data/finance-postgres
sudo chown -R 999:999 /data/finance-postgres
```

### 5.2（可选）从命名卷导出并导入到数据盘目录

先停 postgres：

```bash
cd /root/Finance
docker compose -f docker/docker-compose.yml down
```

把命名卷数据复制出来（只要执行一次）：

```bash
sudo rsync -aH --numeric-ids /var/lib/docker/volumes/postgres_data/_data/ /data/finance-postgres/
```

然后修改 `docker/docker-compose.yml`，把：

- `postgres_data:/var/lib/postgresql/data`

改成：

- `/data/finance-postgres:/var/lib/postgresql/data`

再启动：

```bash
docker compose -f docker/docker-compose.yml up -d postgres
```

---

## 6. 常见问题

### 7.1 `init.sql` 没执行/扩展没创建

如果你使用的是“已有旧数据目录”，Postgres 不会再次执行 `/docker-entrypoint-initdb.d/`。这时你可以手动在库里执行一次：

```bash
docker exec -it finance_postgres psql -U finance -d finance_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 7.3 端口 5432 被占用

改 `docker/docker-compose.yml` 的端口映射，例如把 `"5432:5432"` 改为 `"15432:5432"`，并相应修改 `DATABASE_URL` 里的端口为 `15432`。

---

## 7. 可选：用仓库脚本一键执行

仓库根目录 `scripts/`：

- `./scripts/db_up_postgres.sh`：只启动 postgres
- `./scripts/db_check.sh`：检查版本/扩展/表
- `./scripts/psql.sh`：进入 psql
- `./scripts/db_reset_volume.sh`：重置数据卷（清空数据；仅用于你还在用命名卷时）
