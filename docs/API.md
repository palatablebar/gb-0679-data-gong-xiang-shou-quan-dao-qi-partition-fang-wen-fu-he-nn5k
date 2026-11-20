# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

## 增量区间

- `GET /api/intervals`：列出全部业务日区间及其当前版本与唯一受理结论。
- `GET /api/intervals/<biz_date>`：区间详情，含不可变版本链（versions）。
- `GET /api/intervals/<biz_date>/versions/<version>`：读取指定历史版本快照。
- `POST /api/intervals/<biz_date>/intake`：body为`{"run_id":...}`，受理已采信批次。开放期并入当前版本且同run_id幂等；收口/复核后受理视为晚到补录，封存旧版并开启新版本。
- `POST /api/intervals/<biz_date>/close`：合并当前版本全部批次，写入唯一受理结论；重复收口不新增结论。
- `POST /api/intervals/<biz_date>/review`：body为`{"version":n,"decision":"已复核"|"退回复核"}`，仅收口版本可复查，陈旧版本返回409且旧版保留。
- `GET /api/intervals/<biz_date>/evidence?version=n`：导出该版本证据（缺省导出当前版本）；证据与复查结论共用同一版本锚点，旧版可独立导出。
