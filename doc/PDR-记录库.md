# 记录库 PDR

日期：2026-10-12
状态：方向已定，项目目录已建立，尚未写代码
读者：在本仓库开发的人和 Agent

本文是本仓库的需求与设计基线，路径为 `doc/PDR-记录库.md`。聊天记录不算进度。实现以这份为准。

暂定名称：**记录库**。仓库名可以另取，接口和数据模型以本文为准。

## 1. 背景

个人远程 Linux 服务器目前在跑几个很小的 Docker 程序。工作电脑上偶尔会有随手记，家庭电脑上有本地大模型，希望拿这些记录来分析。2026-10-12 对这台服务器做过一次实地检查，结论如下。

机器是 2 核，内存一共 1.9 GiB。检查当时可用内存约 818 MiB，Swap 已用 1.0 GiB / 1.9 GiB。根分区 50G，已用 65%，剩余约 17G。负载接近空闲，但内存没有余量。`dockerd` 本身大约占 430 MiB。

Docker 29.6.2 和 Compose v5.3.1 已安装，服务在运行。当时没有 Docker volume。在跑的容器：

| 项目 | 服务 | 状态 | 端口 |
|---|---|---|---|
| show-myself | web | 已运行约 8 周，健康 | 主机 3000 → 容器 3000 |
| show-myself | data-perms | 已退出 | 无 |
| dz-pk | web | 已运行约 2 个月 | 主机 1111 → 容器 80 |
| dz-pk | api | 已运行约 2 个月 | 仅容器内 3001 |

另外有一个 6 个月前的 `hello-world` 镜像，没有对应容器。主机上还有 `caddy` 进程。本文不假定它的站点配置，部署时再核对。

SQLite 的情况：命令行 `sqlite3` 没装。系统库 `libsqlite3` 是 3.45.1，`python3` 是 3.12.3，可以直接 `import sqlite3`，模块报告的 SQLite 版本也是 3.45.1。

曾经考虑过在 Docker 里跑一个最小的单节点 Kafka，让工作电脑写入、家庭电脑订阅。最小堆内存按 256 MiB 估算，进程仍要占 450–700 MiB。以当时的可用内存，它能启动，启动后机器会继续吃 Swap。随手记和分析用的记录一年也就一批文本，用不上 Kafka 的吞吐、分区和消费位点。消费位点往前走之后，记录也不会留在服务器上供以后换着问。

MySQL 同样不合适。它是常驻服务，要用户、端口和自己的内存。这台机器要的是一个文件，加上一个很瘦的读写入口。

因此服务器只记账。分析放在家庭电脑的本地模型上。Docker 里的小程序和工作电脑的随手记都通过同一个入口追加记录。家庭电脑按游标把新行拉走。

随手记、想法、新闻、交易记录都进这一份库。类型不同，表不拆。

## 2. 要完成的事

服务器上留下一份只追加的记录。写入方可以是现有的 Docker 小程序，也可以是工作电脑上的一条随手记。一条记录带类型：随手记、想法、新闻、交易记录，以及以后临时出现的其它类型。家庭电脑以后随时按编号把没看过的行取走，可以全部拿走，也可以只拿某一种，交给本地模型。同一批记录可以反复取、换着问。模型的结论默认留在家里。

第一刀不改造 `show-myself` 和 `dz-pk`。先证明：写进一条、进程重启后还在、家里能按编号拉到。

## 3. 谁在用

三条使用路径，都调用第 9 节那一套 REST 接口。没有第二条写入通道，也没有专门的拉取协议。

1. 服务器上的小程序 `POST /v1/records`。
2. 人在工作电脑上补一条随手记，同样 `POST /v1/records`。
3. 人在家庭电脑上 `GET /v1/records`，把返回的记录交给本地模型。模型不在服务器上跑。

没有账号体系，接口也不校验调用方身份。

## 4. 产品是什么

记录库是一台服务器上的一个小进程，背后一个 SQLite 文件。

对外只有这一套 HTTP 接口。业务程序不打开数据库文件，也不走第二套私有协议。`body` 只是记录上的一个字段，不是存取方式。

它也不是消息队列。没有消费位点。拉走一条不会把它从库里删掉。

多种数据类型共用这个进程、这一份文件。交易记录不会单独占一个库。

## 5. 第一版不做

- 不在这台服务器上部署 Kafka、ZooKeeper、MySQL，或任何分析模型。
- 不改 `show-myself`、`dz-pk` 的现有功能。接入某个现有程序是第一刀之后的事。
- 不做账号、多租户、按来源授权。
- 不做修改和删除。写错了就再追加一条更正。
- 不按数据类型拆表或拆库。
- 不做全文检索、向量、标签系统和后台页面。
- 不在服务器上按 `payload` 里的字段查询。要按股票代码筛交易，第一版在家庭电脑拉下来之后做。
- 不把分析结论写回服务器。
- 不把 SQLite 文件放到网络盘上，也不把文件本身拷给两台电脑当同步副本。
- 不校验令牌，也不做登录。

## 6. 决策

### Decision: 用 SQLite 文件，不用独立数据库服务

- Problem and constraints: 记录量小，机器可用内存大约 800 MiB，Swap 已经用了一半。需要断电或重启后数据还在。
- Candidates: Kafka、MySQL、SQLite 文件、直接追加一个 JSONL 文件。
- Current recommendation: 一个 SQLite 文件，由唯一的记录库进程打开。
- Why this fits now: Python 3.12 已能调用 SQLite 3.45.1，不必再装数据库服务。JSONL 好追加，但按编号续拉、去重和崩溃后的完整性要自己做。SQLite 这些都有。
- Reconsider when: 需要很多客户端同时高频率写入，或单文件超过约 1GB，或必须从公网多点同时写。
- Explicit non-goals: 不把 SQLite 换成 MySQL 来“以后好扩展”。

### Decision: 只有记录库进程能打开数据库文件

- Problem and constraints: 写入方有多个容器和两台电脑。SQLite 在本机多进程写需要小心锁；跨机器直接打开文件不可行。
- Candidates: 每个程序挂载同一个文件自己写；一个 HTTP 进程统一写。
- Current recommendation: 只有记录库进程打开这个文件。其他程序调用它的 HTTP 接口。
- Why this fits now: 写入次数低，多一个很瘦的进程比把锁散落到各个容器里清楚。
- Reconsider when: 记录库和某个程序必须合成一个进程才能部署。即便如此，仍然只有一处打开文件。
- Explicit non-goals: 不提供“把数据库文件路径配进业务容器”这种接入方式。

### Decision: 只追加，用自增 id 当游标

- Problem and constraints: 家庭电脑要能中断后继续拉，也要能把同一批记录重新交给模型。
- Candidates: 消费位点、按时间拉取、按自增 id 拉取。
- Current recommendation: `id` 为 SQLite `INTEGER PRIMARY KEY`。拉取参数是 `after_id`。响应里给出本批最大 id，调用方自己记住。
- Why this fits now: 时间会乱序或重复，id 不会。没有消费位点，重复拉取是正常操作。
- Reconsider when: 需要服务端记住“家里已经分析过哪些”。那是另一张表，不属于第一版。
- Explicit non-goals: 不实现 Kafka 式的 consumer group。

### Decision: 多种数据类型共用一张表

- Problem and constraints: 同一份库要收下随手记、想法、新闻、交易记录，以及还没想好名字的其它记录。这些都是一段文字加一个标签。机器小，不能为每种类型起一个服务。
- Candidates: 每种类型一张表；一种类型一个库；一张表，用 `kind` 区分，结构化字段放 JSON。
- Current recommendation: 一张 `records` 表。`kind` 是标签。`body` 始终是给模型读的纯文本。`payload` 可选，出现时必须是 JSON 对象，服务器不检查里面的键。`news` 是例外：带了 `payload` 时要有非空 `title`。交易记录和随手记一样，只靠 `kind` 区分。
- Why this fits now: 家庭电脑的主路径是按顺序把新行拉走，再按标签分开看。交易记录先记成一段文字，价格和数量不在服务器上卡格式。没登记的标签也可以写入，这样「其它」不必先改表、先发版。
- Reconsider when: 某一种类型要在服务器上按自己的字段频繁筛选，或单种记录的写入量已经盖过其它所有类型。那时再为那一种单独加表，不提前拆。
- Explicit non-goals: 不建 `trades`、`ideas`、`news` 三张业务表。不把 `payload` 展开成列。

### Decision: 存和取都走同一套 REST 资源

- Problem and constraints: 写入方有小程序和工作电脑，读取方是家庭电脑，类型有随手记、想法、新闻、交易和未登记类型。若把「存」和「拉」写成两套说明，调用方会各自发明路径。
- Candidates: 每种类型一组路径，例如 `/v1/trades`；一个集合 `/v1/records`，用 `kind` 区分；另做一套仅供同步的私有接口。
- Current recommendation: 只有资源 `records`。创建用 `POST /v1/records`，列出用 `GET /v1/records`，读取一条用 `GET /v1/records/{id}`。类型和来源的目录用 `GET /v1/kinds`。不提供 `PUT`、`PATCH`、`DELETE`。
- Why this fits now: 调用方学习一个集合就够。按类型过滤是查询参数，不是另一套接口。`after_id` 也只是这个集合上的查询参数，用来从上次看到的 id 之后继续取。
- Reconsider when: 某一种类型的字段多到无法放进同一个 JSON 表示，或确实需要更新已有行。
- Explicit non-goals: 不为 `note`、`idea`、`news`、`trade` 各做一组 CRUD。不增加 `/pull`、`/store`、`/sync` 这类动词路径。

### Decision: 分析留在家庭电脑

- Problem and constraints: 服务器 1.9 GiB 内存，本地模型放不上去。
- Candidates: 服务器上跑模型；家庭电脑拉取原文后本地分析。
- Current recommendation: 服务器只保存原文。家庭电脑拉取后自行调用本地模型。
- Why this fits now: 模型和提示词会变，原文留下就能重跑。
- Reconsider when: 服务器内存和磁盘都足够跑指定模型，并且确实要把分析放到服务器上。
- Explicit non-goals: 第一版不保存模型名称、提示词和分析结果。

### Decision: Python 标准库实现，不引入 Web 框架

- Problem and constraints: 服务器已有 Python 3.12.3 和 `sqlite3`。请求量是人的随手记加上几个小程序的偶发写入。
- Candidates: Python 标准库、FastAPI/Flask、Go、单独的 sqlite CLI 脚本。
- Current recommendation: 一个 Python 进程，使用标准库 `sqlite3` 和 `http.server.ThreadingHTTPServer`。
- Why this fits now: 少一层依赖，镜像和内存都好控制。`sqlite3` 命令行目前没装，不依赖它。
- Reconsider when: 接口需要上传文件、流式响应，或标准库 HTTP 实现开始挡验收。
- Explicit non-goals: 不为了“正规”先引入框架。

### Decision: 不校验令牌，8787 对主机网卡开放

- Problem and constraints: 这是自己用的记录库。工作电脑和家庭电脑要直接请求 REST，不想保管令牌，也不想先做 SSH 转发。
- Candidates: 继续只监听本机并带令牌；公网端口加令牌；公网端口不校验身份。
- Current recommendation: 请求不带 `Authorization`。容器端口映射为 `8787:8787`，主机监听所有网卡。本机直接跑 `python -m recordstore` 时默认仍是 `127.0.0.1`，避免开发时误开放。
- Why this fits now: 调用方就是自己的电脑。少一个令牌文件，接口可以直接 `curl`。
- Reconsider when: 这台机器的 `8787` 被扫到，或记录里开始出现不想公开的内容。那时再加令牌或改回只监听本机。
- Explicit non-goals: 不做登录、账号和 HTTPS。不修改 caddy 配置。

## 7. 运行约束

这些数字来自 2026-10-12 的检查，开工时再核一次。机器状态变了就改本文，不要沿用过期数字做部署决定。

- 内存上限：容器 `--memory=128m`。进程常态 RSS 目标低于 80 MiB。超过这个上限就停下来查，不要把上限调到 512 MiB 硬扛。
- 磁盘：数据库目录用主机目录的 bind mount。不要用匿名 volume，否则重建容器时说不清文件在哪。
- 端口：避开 3000、1111、3001。容器内监听 8787，主机侧把 `8787` 发布到所有网卡。主机端口若与现网冲突，改映射，不改接口。
- 写入频率按“人可以手工看完”设计。不做批量导入通道。
- 单条 `body` 最大 64 KiB。单条 `payload` 序列化后最大 16 KiB。更大的内容先被拒绝，避免一条记录把模型和进程一起撑住。
- 单次拉取默认 50 条，最大 100 条。

## 8. 数据

文件位置在部署时确定，进程启动时创建。建议目录只放这一份库和它的备份，不和 `show-myself`、`dz-pk` 的目录混放。

连接建立后立刻执行：

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
```

`synchronous = FULL` 是有意的。写入很少，少丢最后一次提交比快几毫秒重要。

```sql
CREATE TABLE records (
  id          INTEGER PRIMARY KEY,
  source      TEXT NOT NULL,
  kind        TEXT NOT NULL,
  body        TEXT NOT NULL,
  payload     TEXT,
  created_at  TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  client_key  TEXT UNIQUE
);

CREATE INDEX idx_records_kind_id ON records (kind, id);
```

- `id` 只由数据库分配，调用方不能指定。
- `source` 表示谁写的，例如 `manual`、`show-myself`、`dz-pk`。第一版不设枚举，调用方自己保持稳定拼写。
- `kind` 表示数据类型，见下文。接口里用英文短名，不用中文。
- `body` 是交给模型的正文，纯文本。每种类型都要有。交易记录也要写一句人能读懂的话，不能只丢一个 JSON。
- `payload` 可空。入库时存 JSON 文本，取出时还原成对象。没有则是 `null`。服务器不按里面的键做查询。
- `created_at` 是事情发生的时间，ISO 8601 UTC，由调用方提供。没提供时，服务器填与 `ingested_at` 相同的值。
- `ingested_at` 只由服务器填写。
- `client_key` 可选，全局唯一，不分类型。相同 `client_key` 再次提交时，返回已有记录的 `id`，不插入第二行。工作电脑重试时靠这个去重。

另有一张表记录结构版本，第一版版本号为 1。以后改表先改版本，再改进程。

不建更新时间，不建删除标记。

### 8.1 类型

`kind` 匹配 `^[a-z][a-z0-9_-]{0,31}$`。不符合的请求返回 `400`。

没登记的类型直接收下，这就是「其它」的入口，不必为了一个新名字先发版。

| kind | 含义 | 必填 | payload |
|---|---|---|---|
| `note` | 随手记 | `body` | 可省略 |
| `idea` | 想法 | `body` | 可省略 |
| `news` | 新闻 | `body` | 可省略。若带了 `payload`，里面必须有非空 `title`。`url` 可有可无 |
| `trade` | 交易记录 | `body` | 可省略。服务器不检查价格、数量、方向或代码。`kind` 只是标签 |

分红、转账、申购可以用 `trade`，也可以用新的 `kind`，例如 `dividend`。没登记也能先写入。

交易记录的正文由调用方写。有没有价格都收下。

## 9. 接口

数据进出只有下表这些方法。小程序、工作电脑、家庭电脑用同一组路径。请求直接打到主机的 `8787`，不需要另做一套接口。

监听地址是容器内的 `0.0.0.0:8787`，发布到主机的 `8787`。请求不需要 `Authorization`。`POST` 带：

```http
Content-Type: application/json
```

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/v1/records` | 新增一条记录 |
| `GET` | `/v1/records` | 列出记录 |
| `GET` | `/v1/records/{id}` | 读取一条 |
| `GET` | `/v1/kinds` | 列出已登记类型，以及库里出现过的类型和来源 |
| `GET` | `/health` | 进程是否在听 |

没有 `PUT`、`PATCH`、`DELETE`。写错了再 `POST` 一条新记录。

错误响应统一为：

```json
{"error": "validation_error", "message": "body is required"}
```

`error` 只用这几个值：`validation_error`（400）、`payload_too_large`（413）、`not_found`（404）。`message` 给人看，调用方只依赖 `error` 和状态码。

一条记录在三个读接口里的形状相同：

```json
{
  "id": 4,
  "source": "manual",
  "kind": "trade",
  "body": "买入 100 股 600519，价格 1680 CNY",
  "payload": {
    "symbol": "600519",
    "side": "buy",
    "qty": 100,
    "price": 1680,
    "currency": "CNY"
  },
  "created_at": "2026-10-12T01:30:00Z",
  "ingested_at": "2026-10-12T01:30:02Z"
}
```

没有 `payload` 时，该字段为 `null`。

### POST /v1/records

```http
POST /v1/records
Content-Type: application/json

{
  "source": "manual",
  "kind": "note",
  "body": "今天把超时从 3 秒改成 8 秒",
  "created_at": "2026-10-12T08:00:00Z",
  "client_key": "work:2026-10-12T08:00:00Z:1"
}
```

`source`、`kind`、`body` 必填，且去掉首尾空白后不能是空字符串。`created_at`、`client_key`、`payload` 可省略，`trade` 也一样。`payload` 若出现，必须是 JSON 对象，不能是数组或字符串。服务器不检查 `trade` 的 `payload` 里有没有价格。

成功插入返回 `201`，响应头带 `Location: /v1/records/1`，正文是完整记录，不是只含 `id`。

`client_key` 已存在时返回 `200` 和原来的那条完整记录，不插入第二行，也不修改旧行。

校验失败返回 `400`。`body` 超过 64 KiB，或 `payload` 超过 16 KiB，返回 `413`。

交易记录用同一个路径，`kind` 写成 `trade`。不带 `payload` 也可以：

```json
{
  "source": "manual",
  "kind": "trade",
  "body": "买入 100 股 600519，价格 1680 CNY",
  "created_at": "2026-10-12T01:30:00Z",
  "client_key": "trade:2026-10-12:600519:1"
}
```

### GET /v1/records

```http
GET /v1/records?after_id=0&limit=50
GET /v1/records?after_id=0&kind=trade&limit=50
GET /v1/records?after_id=0&source=manual&limit=50
GET /v1/records?source=manual&kind=trade
```

`after_id` 省略时按 0。返回 `id` 大于该值的记录，按 `id` 升序。`kind` 省略时不按类型过滤。`source` 省略时不按来源过滤。两个都带时必须同时匹配。`source` 是精确匹配，先去掉首尾空白；空白值返回 `400`。没写过的来源返回空数组，不是 `404`。

```json
{
  "records": [],
  "next_after_id": 4
}
```

`records` 里每项都是上面的完整记录。没有命中的新行时，`records` 为空数组，`next_after_id` 等于请求里的 `after_id`。不要因为库里已经有别的类型或别的来源的更大 `id`，就把 `next_after_id` 推过去。否则带 `limit` 时会漏掉还没返回的匹配记录。

`next_after_id` 是这个列表响应里的继续位置，调用方下次把它放回 `after_id`。服务器不保存调用方的进度。混在一起读，就记一个数，请求里不带 `kind` 和 `source`。只读交易、只读某个来源，或同时限定类型和来源，就为这个组合各记一个数。要重读时，把本地的数调小或调回 0。

### GET /v1/records/{id}

返回这一条的完整记录，`200`。`id` 不存在返回 `404`。

### GET /v1/kinds

```http
GET /v1/kinds
GET /v1/kinds?source=heynote
```

列出已登记类型，以及库里已经出现过的未登记类型。每一项带上写过这种类型的来源。来源不设枚举：谁写入过，下次查询就出现，不必为新来源改代码。

```json
{
  "kinds": [
    {"kind": "note", "payload": "optional", "sources": ["heynote", "manual"]},
    {"kind": "idea", "payload": "optional", "sources": []},
    {"kind": "news", "payload": "optional", "sources": []},
    {"kind": "trade", "payload": "optional", "sources": []},
    {"kind": "daily_job", "payload": "optional", "sources": ["heynote"]}
  ]
}
```

`source` 省略时返回上面这一整份目录。已登记的四种始终在前，顺序固定；还没有记录时 `sources` 为空数组。未登记类型排在后面，按 `kind` 字典序，只有库里出现过才列出。`payload` 仍表示字段检查：已登记类型用登记时的规则，未登记类型是 `optional`。

`source` 是精确匹配，先去掉首尾空白。带了这个参数时，只返回该来源写过的类型；这个来源还没写过任何记录时，`kinds` 为空数组。每一项的 `sources` 仍是写过该类型的全部来源，按字典序，不因为过滤就只剩这一个。同一种类型可以有多个来源，所以字段是数组，不是单个 `source`。

空白的 `source` 返回 `400`。未登记类型仍然可以 `POST`。

### GET /health

返回 `200` 和 `{"ok": true}`。它不读取记录。

## 10. 安全与备份

接口不校验令牌。日志不打印 `body` 和 `payload`。访问日志只留时间、方法、路径、状态码和记录 id。

备份用 SQLite 的 backup API 写出一份一致的快照，不用在 WAL 模式下直接 `cp` 正在写的库文件。第一版提供一条可手动运行的备份命令，把快照写到同一台机器的另一个目录。这不能防磁盘坏掉。把快照拷离这台服务器，放到第二刀，和第一个业务程序接入一起排期，不塞进第一刀。

第一版没有删除接口。要清数据时，停进程，把数据库文件挪走，再启动。这个动作要人确认，不做成程序里的命令。

## 11. 里程碑

每一刀都能单独部署、单独验收。上一刀没有在服务器上跑通，不开始下一刀。

### M1：写一条，重启还在，家里拉得到

包含：建库、第 9 节全部方法、已登记类型的字段检查、未登记类型可写入、`client_key` 去重、128 MiB 内存限制、bind mount、手动备份命令。不校验令牌。

不包含：改造现有 Docker 程序，图形界面，模型调用，公网入口。

验收时对同一路径 `POST` 一条 `note` 和一条只有正文的 `trade`，请求不带 `Authorization`。重启容器后 `GET /v1/records` 仍能看到两条，`GET /v1/records/{id}` 能读到其中一条。`kind=trade` 时只有交易。没有价格的交易返回 `201`。没登记过的合法 `kind` 可以 `POST`。`GET /v1/kinds` 列出已登记的四种，并带上库里出现过的类型及其来源。从另一台电脑直接请求主机 `8787`，正文一致。重复的 `client_key` 不产生第二行。不存在的 id 得到 `404`。

### M2：一个现有程序真正写入

选 `show-myself` 或 `dz-pk` 里一个已经在产生文本的点，改那一处，让它 `POST /v1/records`。选哪个在 M1 完成后再定，不在本文里猜。

验收时，那个程序的一次真实操作会在记录库里出现一行，`source` 能看出是它写的。原程序的原有页面和接口仍按改造前的方式可用。

### M3：家庭电脑上的拉取脚本

一个本地脚本记住游标，拉出新行，输出成适合粘贴给本地模型的文本。默认一个游标拉全部类型。脚本要能改成只拉一种 `kind`，并为这种类型单独记住游标。脚本不调用模型，不把结论上传。

验收时，连续跑两次：第一次打出新行并记住游标，第二次没有新行时输出为空。把游标改回 0 后能再次打出旧行。只拉 `trade` 时，输出里有这些记录的 `body`，且不含想法和新闻。

## 12. 测试与放行

去重、游标和重启后的数据属于高风险行为。M1 先写失败测试，再写实现。至少覆盖：

- 缺字段、空正文、超长正文、超大 `payload`
- 只有正文的 `trade` 返回 `201`，不完整的 `payload` 也原样保存
- `news` 带了 `payload` 但没有 `title`
- 未登记但合法的 `kind` 可以写入；不合法的 `kind` 返回 `400`
- `GET /v1/kinds` 包含已登记类型和库里出现过的未登记类型，每项带 `sources`；`source` 只返回该来源写过的类型，没写过时 `kinds` 为空数组
- 不带 `Authorization` 也能新增和查询；`/health` 返回 `{"ok": true}`
- 相同 `client_key` 只有一行，且不分类型
- `after_id` 分页顺序和 `next_after_id`
- `kind=trade` 时不返回其它类型；本页之间夹着别的类型时，不能把那些类型的 id 跳过到漏掉下一条交易
- `source=manual` 时不返回其它来源；可与 `kind` 同时使用。夹着别的来源时，不能把那些 id 跳过到漏掉下一条匹配记录
- 过滤结果为空时，`next_after_id` 保持为请求中的 `after_id`
- 进程重启后行还在，`payload` 与写入时一致
- 备份快照能用 SQLite 打开，并且行数与原库一致

M1 的完成以服务器上的验收为准，不以本机单元测试通过为准。部署用的镜像或进程必须在这台 1.9 GiB 的机器上启动，并满足第 7 节的内存上限。

## 13. 开工时还要补的文件

设计规格已经在 `doc/PDR-记录库.md`。开始写代码前再补这三份，不要改本文里已经定下的接口和数据模型：

1. 写 `README.md`，只说明这个服务做什么、如何在服务器上启动、调用方如何通过 SSH 转发访问。
2. 写 `doc/STATUS.md`，标明当前处于 M1，以及还没有部署。
3. 写 `AGENTS.md`，写明：不打印服务器 IP、用户名、登录口令；不在未经同意时删除数据库文件。

`ai-use-test` 里还有一份同名草稿。两份若以后不一致，以本仓库这份为准。

## 14. 开工前不必再讨论的事

下面几件已经定了，后续实现不要改口，除非先改本文：

- 服务器记账，家庭电脑分析。
- 一个 SQLite 文件，一个写入进程。
- 只追加，用 `id` 续拉。
- 多种数据类型共用一张表。`kind` 是标签，`body` 是正文。交易记录不检查价格等字段。
- 存和取只有 `/v1/records` 这一套 REST 资源。
- 接口不校验令牌。服务器上的 `8787` 对主机网卡开放。
- 第一版不接入现有的两个 Docker 项目。

还没定、但不挡住 M1 的只有一件：M2 先接 `show-myself` 还是 `dz-pk`。
