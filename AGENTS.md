# 记录库：给 Agent 的规则

需求以 `doc/PDR-记录库.md` 为准。进度以 `doc/STATUS.md` 为准，不要只靠聊天记录。

## 秘密

- 不打印、不记录、不复述服务器 IP、用户名或登录口令。
- 接口不使用令牌。`.env` 仍不提交。

## 数据

- 不在未经使用者明确同意时删除、清空或覆盖数据库文件。
- 第一版没有删除接口。要清数据时先停进程，由人把数据库文件挪走，再启动。
- 备份用 SQLite backup API：`python -m recordstore.backup SRC DEST`。不要在 WAL 模式下直接 `cp` 正在使用的库文件。
- 日志不打印 `body` 和 `payload`。

## 范围

- 未得到要求时，不部署到远程服务器，不改造 `show-myself` 或 `dz-pk`。
- 不改已经定下的接口和数据模型，除非先改 PDR。
