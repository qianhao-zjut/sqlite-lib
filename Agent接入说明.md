## Agent接说明
核心查询接口是：
GET	/v1/kinds	已登记类型，加上库里出现过的类型。每项有 sources。可加 source 只看该来源写过的类型
GET	/v1/records	after_id 默认 0，limit 默认 50、最大 100。可加 kind、source，两个都带时同时匹配。支持游标，通过 after_id 来控制。


目前source 来源主要有
- heynote：mac 端，笔记便签工具
- qh_note：手机端笔记工具
- dz-pk： 德州扑克小游戏

可以用 GET	/v1/kinds，先分析来源有哪些kind 然后在看下面的场景分析，并按照不同场景去分析数据。


主要用来分析的场景有：
电脑端
source=heynote&kind=trade_daily : 表示日常行情观察和交易日志
source=heynote&kind=meet_thing : 工作会议记录
source=heynote&kind=daily_job : 日常工作摘要
source=heynote&kind=idea : 一些好的 idea 记录，一些点子，后续可以执行，做成一些产品


手机端
source=qh_note&kind=idea : 一些好的 idea 记录，一些点子，后续可以执行，做成一些产品(手机端记录)
source=qh_note&kind=think : 一些思考，想法
source=qh_note&kind=memo : 备忘录


德州小游戏分析
source=dz-pk&kind=game_log : 游戏日志，分析牌局，复盘牌局。

