# 记录库

一个只追加的记录服务。随手记、想法、新闻、交易和临时类型都写进同一个 SQLite 文件。家庭电脑按编号把新行拉走，分析留在家里。没有修改和删除接口。

接口和字段以 `doc/PDR-记录库.md` 为准。当前进度见 `doc/STATUS.md`。

## 本地运行

需要 Python 3.12 或更高版本，只用标准库。

```bash
export RECORD_DB=./data/records.db
export RECORD_HOST=127.0.0.1
export RECORD_PORT=8787
python3 -m recordstore
```

本机调试时进程监听 `127.0.0.1:8787`。数据库文件由 `RECORD_DB` 指定，目录不存在时会创建。

另开一个终端：

```bash
curl -sS http://127.0.0.1:8787/health
curl -sS -H "Content-Type: application/json" \
  -d '{"source":"manual","kind":"note","body":"hello"}' \
  http://127.0.0.1:8787/v1/records
```

## 在服务器上运行

不校验令牌。`docker compose up -d --build` 把容器的 `8787` 发布到主机的 `8787`，主机侧监听所有网卡。数据库在 `./data`，备份目录是 `./backups`，都是主机目录的 bind mount。容器内存上限 128 MiB。主机端口如果和现网冲突，只改冒号左边的端口，不改容器内的 8787。

停掉服务：

```bash
docker compose stop
```

## 从别的电脑访问

直接请求服务器的 `8787`，不需要令牌，也不需要 SSH 转发：

```bash
curl -sS http://<server>:8787/health
curl -sS "http://<server>:8787/v1/records?after_id=0&limit=50"
```

`<server>` 换成这台机器的地址，不要把地址写进仓库。同一台机器上的其他容器以后要访问时，走 Docker 网络里的服务名 `recordstore` 和端口 `8787`。第一版不接入现有程序。

## 调用

不需要 `Authorization`。`POST` 带 `Content-Type: application/json`。

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/v1/records` | 新增。`201`，`Location` 指向新记录。`client_key` 已存在时 `200` 并返回原来的记录 |
| `GET` | `/v1/records` | `after_id` 默认 0，`limit` 默认 50、最大 100，可加 `kind` |
| `GET` | `/v1/records/{id}` | 没有这条时 `404` |
| `GET` | `/v1/kinds` | 已登记类型，加上库里出现过的类型。每项有 `sources`。可加 `source` 只看该来源写过的类型 |
| `GET` | `/health` | 返回 `{"ok": true}` |

没有 `PUT`、`PATCH`、`DELETE`。`limit` 不在 1 到 100 之间时返回 `400`。

错误正文是 `{"error": "...", "message": "..."}`。`error` 为 `validation_error`、`payload_too_large` 或 `not_found`。

## 备份

用 SQLite 的 backup API 写一份一致快照，不要在 WAL 模式下直接 `cp` 正在使用的库文件。

本地：

```bash
python3 -m recordstore.backup data/records.db backups/records.db
```

服务器上，目标文件名不要和已有快照重复：

```bash
docker compose exec recordstore python -m recordstore.backup \
  /data/records.db /backups/records-$(date -u +%Y%m%dT%H%M%SZ).db
```

这条命令不能代替把快照拷离这台机器。清库不是程序里的命令：先停进程，确认后再把数据库文件挪走。

## 测试

在仓库根目录：

```bash
python3 -m unittest discover -s tests -v
```
