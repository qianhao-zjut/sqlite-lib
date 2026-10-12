# 记录库状态

- 活动里程碑：M1 写一条，重启还在，家里拉得到
- 分支：`main`（还没有任何提交，本次改动未提交）
- 部署：尚未部署到远程服务器
- 远程验收：未做。M1 的完成以服务器上的验收为准，本机测试通过不算部署完成

## 已完成

M1 的本机部分已经按 `doc/PDR-记录库.md` 实现，尚未部署：

- 标准库 HTTP + SQLite 进程，`POST/GET /v1/records`、`GET /v1/records/{id}`、`GET /v1/kinds`、`GET /health`
- 令牌、已登记类型字段检查、未登记类型可写、`client_key` 去重
- 建库 pragma、结构版本 1、64 KiB / 16 KiB 上限、游标 `next_after_id`
- `Dockerfile` 与 `docker-compose.yml`：内存 128 MiB，数据库目录 bind mount，主机只绑定 `127.0.0.1:8787`
- 手动备份：`python -m recordstore.backup SRC DEST`（SQLite backup API）

## 验证

2026-10-12，在本仓库根目录。

单元测试：

```text
python3 -m unittest discover -s tests
Ran 18 tests in 8.325s
OK
```

覆盖 PDR 第 12 节：缺字段和空正文、超长正文、超大 payload、交易字段、新闻标题、未登记类型、非法 kind、令牌和 `/health`、`client_key`、分页和 `next_after_id`、按 `kind` 过滤时不跳过下一条交易、空结果不推进游标、重启后 payload 仍在、备份快照行数一致。

本机进程，临时库，`python3 -m recordstore`，停掉后再对同一个库文件启动：

- `POST` note → `201`，`Location: /v1/records/1`
- `POST` trade → `201`，`Location: /v1/records/2`，`payload` 与写入一致
- `GET /v1/records` → `200`，两条，id 为 1、2，`next_after_id` 为 2
- `GET /v1/records/2` → `200`，与刚写入的交易相同
- `GET /v1/records?kind=trade` → 只有 id 2
- `GET /v1/kinds` → `note`、`idea`、`news`、`trade`
- `GET /health` → `200`，`{"ok": true}`
- 错误令牌和缺少令牌都是 `401`，正文相同，`error` 为 `unauthorized`
- 重启后列表仍是这两条，按 id 读取的交易 `payload` 不变
- 访问日志里没有令牌、正文和交易标的

`docker compose config` 解析通过：内存限制 134217728 字节（128 MiB），端口 `127.0.0.1:8787` 映射到容器 `8787`。没有执行 `docker compose up`，也没有部署到远程机器。

## 未完成

- 在那台 1.9 GiB 的服务器上启动，并按 PDR 第 11 节做远程验收
- 从另一台电脑经 SSH 本地转发调用同一个 `GET`，核对正文
- M2 接入 `show-myself` 或 `dz-pk`。接哪一个还没定，不挡住已经写完的 M1 代码

## 下一步

把 M1 部署到服务器并做远程验收。上一刀没有在服务器上跑通之前，不开始 M2。
