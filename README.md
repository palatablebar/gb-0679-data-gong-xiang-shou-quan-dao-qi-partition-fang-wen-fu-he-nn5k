# 数据共享授权到期与分区访问复核

供企业数据共享审计专员核对原始记录、处理差异并封存证据。

## 启动

```sh
docker compose up --build -d
docker compose exec -T app pytest -q
```

打开 http://localhost:18248 。首次进入自动运行仓内脏样例。工具条可重跑、切换样例或上传CSV。SQLite保存在命名卷records中，重建服务保留批次。

## 模块

- 1. 访问采信：`/accesses`，`/api/accesses`。
- 2. 资源映射：`/resources`，`/api/resources`。
- 3. 授权定版：`/grants`，`/api/grants`。
- 4. 冲突裁决：`/conflicts`，`/api/conflicts`。
- 5. 分区判定：`/partitions`，`/api/partitions`。
- 6. 访问对账：`/audit`，`/api/audit`。
- 7. 审计归档：`/seals`，`/api/seals`。
- 8. 增量复核：`/intervals`，`/api/intervals`。按业务日形成增量区间，收口产生唯一受理结论，晚到记录以新版本回看且旧版永久留存。

## 核心规则

拒绝规则优先于允许，授权必须同时命中资源、分区和生效窗；显式拒绝不得被宽授权覆盖。

## 演示

1. 打开首页，核对当次计算、差异和隔离原因。
2. 切换模块查看源行及裁决依据。
3. 重跑相同样例，批次号与行数保持一致。
4. 复核后导出一份证据CSV。版本已变化的复核提交返回409。

## 输入与输出

输入列见 `docs/DATA-DICTIONARY.md`。项目包含dirty.csv、clean.csv、legacy.csv，统一走实际导入路径。上传限制4MB，拒绝不带时区的时间。业务键按字符串保留，Decimal参与计算，空值不会当零。

`POST /api/runs` 接收sample或csv；`GET /api/runs`返回历史批次；`POST /api/runs/<id>/review`需要version与decision；`GET /api/runs/<id>/archive`返回唯一证据导出。

## 增量区间复核

每个业务日一个区间（`/intervals`）。受理窗口开放时，多个已采信批次按run_id并入同一版本，重复run_id直接复用不占位；`POST /api/intervals/<date>/close` 合并全部已受理批次，形成该区间**唯一受理结论**（锚定一个合并批次与输入摘要）。授权复查（review）与证据导出（evidence）始终锚定同一版本，不会出现同区间多结论。

收口后才送达的晚到记录不允许改写旧版：再次受理会把旧版标记superseded并整体封存，开启v2等新版本回看；新版本收口后成为当前结论，旧版结论、复查意见与原始依据仍可按`?version=n`单独导出。同一区间重跑同内容幂等不新增结论；基于陈旧版本的复查返回409，失败事务不改写任何旧版数据。流程上选择**先关闭已完成部分、再回看晚到记录**，而不是无限等待落定。

## 范围

样例均为虚构。单机复核工具不连接生产系统；不提供登录、远端数据库或自动支付。内存计算按4MB输入上限控制，SQLite事务保证结果完整写入。

## 目录

app为服务与规则，sample_data为输入，tests为测试，docs为定义与深度登记。
