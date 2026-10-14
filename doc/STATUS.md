# 记录库状态

- 活动里程碑：M1 写一条，重启还在，家里拉得到
- 分支：`main`
- 部署：已在远程服务器用 Docker Compose 启动。接口不校验令牌，主机 `8787` 对所有网卡开放
- 远程验收：2026-10-12 在服务器本机端口通过。另一台电脑的 SSH 转发还没从家庭电脑实际打过一次

## 已完成

M1 已按 `doc/PDR-记录库.md` 实现，并部署到远程服务器：

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

`docker compose config` 解析通过：内存限制 134217728 字节（128 MiB），端口 `127.0.0.1:8787` 映射到容器 `8787`。

2026-10-12，远程服务器上的运行中服务，对 `127.0.0.1:8787` 做了 19 项检查，全部通过：

- `POST` note → `201`，`Location: /v1/records/1`
- `POST` trade → `201`，id 为 2，`payload.price` 为 10
- 缺少 `price` 的交易 → `400`，`validation_error`
- 未登记 `kind` `scratch` → `201`，id 为 3
- 重复 `client_key` → `200`，仍是 id 1，没有第二行
- `GET /v1/records` 返回这三条，`next_after_id` 为 3
- `GET /v1/records/2` 正文与写入一致
- `kind=trade` 只返回交易
- `GET /v1/kinds` 只有 `note`、`idea`、`news`、`trade`
- 错误令牌和缺少令牌都是 `401`，正文相同
- 不存在的 id → `404`
- `docker compose restart` 后健康检查恢复，note 正文和 trade 的 `payload` 仍在
- 监听地址只有本机 `8787`，没有绑到所有网卡
- 容器内存约 14 MiB，上限 128 MiB
- 备份快照能打开，行数为 3
- 容器日志里没有令牌、验收正文和交易标的

验收写入的三行留在服务器数据库里，没有删除。

## 未完成

- 从另一台电脑经 SSH 本地转发调用同一个 `GET`，核对正文
- M2 接入 `show-myself` 或 `dz-pk`。接哪一个还没定

## 随后改动

2026-10-12：`trade` 不再检查 `symbol`、`side`、`qty`、`price`。只有正文的交易记录返回 `201`，`kind` 只作标签。这一版已部署。服务器上验证通过：不带价格的交易写入成功，原先的记录还在，`GET /v1/kinds` 里 `trade` 的 payload 为 `optional`。验证又写入了两条交易，没有删除。

## 随后改动：去掉令牌

2026-10-12：接口不再校验 `Authorization`。服务器把 `8787` 发布到所有网卡。本机直接运行时默认仍是 `127.0.0.1`。

## 随后改动：类型目录带上来源

2026-10-13：`GET /v1/kinds` 不再只返回写死的四种已登记类型。已登记类型仍在最前；库里出现过的未登记类型排在后面。每一项增加 `sources`，列出写过这种类型的来源。`?source=` 只返回该来源写过的类型。新来源写入后下次查询就会出现，不必改代码。这一版还没部署到远程服务器。

## 下一步

从这台电脑直接请求服务器的 `8787`，确认不带令牌能读到记录。云厂商安全组如果没放行 `8787`，请求到不了进程。接现有程序之前，先定 M2 接哪一个。
