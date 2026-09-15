---
name: host-healthcheck
description: 当用户询问服务器/宿主机健康状态（CPU 负载、内存占用、磁盘空间、开机时长、进程数、温度等），或怀疑机器人卡顿、服务器宕机、内存不足时使用。激活后运行自带采集脚本获得结构化 JSON 并如实转述：每个指标组都标注来源视图，汇报必须区分 proc 直读的宿主机整机值、容器自身 cgroup 限额、data 卷磁盘与宿主机 cron 采集文件，不得把容器视角说成宿主机实测，缺失或陈旧的数据如实说明。
---

# host-healthcheck 宿主机健康检查

用只读采集脚本回答"服务器/机器人现在运行状态如何"类问题。全部能力在
`scripts/collect.py`（纯 Python 3 标准库，只读探测，一秒内完成）。

## 工作方式

1. 用 `run_skill_script` 执行 `scripts/collect.py`，无需 `args`。
2. 首次执行前可用 `read_skill_resource` 查看脚本源码确认行为。
3. stdout 是单个 JSON 文档，解析后按本手册转述；不要把整段 JSON 原样贴给用户。

## 输出契约

顶层字段：

- `schema` / `generated_at` / `platform`：报告版本、生成时间、运行平台。
- `levels`：三层增强探测结果。`L0` 恒真（零配置默认可用）；`L1` 表示检测到
  宿主机 cron 采集文件；`L2` 表示检测到部署者只读挂载的 `/host/proc`。
- `views`：四种来源视图的语义说明，转述来源时以它为准。
- `groups`：指标组，每组都有 `status`（`ok` / `stale` / `unavailable`）与
  `view`（来源视图）字段。
- `reporting_rule`：转述纪律，必须遵守。

指标组：

| 组 | 内容 | 视图 |
|---|---|---|
| `load` | 1/5/15 分钟负载、线程数、CPU 核数 | host-proc |
| `memory` | 整机内存总量/可用量/占用比、swap | host-proc |
| `uptime` | 开机时长 | host-proc |
| `cpu` | 核数、开机时间、开机以来累计忙/闲占比 | host-proc |
| `container` | 本容器的 cgroup 内存/CPU 限额与用量 | cgroup |
| `disk` | data 卷的磁盘用量（df 语义） | host-mount |
| `host_metrics` | 宿主机 cron 采集的进程数、全量磁盘、温度等 | host-metrics-file |

## 来源视图与诚实条款

Linux 容器对 loadavg/meminfo/uptime/stat 不做命名空间隔离，`/proc` 直读即
宿主机整机值；被遮住的只是进程表、网络接口与未挂载磁盘。转述时遵守：

- `host-proc`：宿主机整机实测。`source` 以 `/host/proc` 开头时取自部署者
  显式只读挂载的宿主机 proc（L2）。
- `cgroup`：容器自身限额视角，只约束机器人进程；回答"机器人自己还剩多少
  内存/CPU"时用它，回答"整台服务器"时用 host-proc 组。
- `host-mount`：data 卷位于宿主机真实磁盘分区，用量为该分区的 df 值。
- `host-metrics-file`：宿主机实测（cron 每分钟写入）。`stale` 说明采集器
  可能已停止，给出 `age_seconds` 并提示部署者检查；`unavailable` 说明未部署，
  此时进程数、全量磁盘、温度无从得知，如实说明即可。

缺失（unavailable）与陈旧（stale）必须明说，不得推测补全数字。

## 解读指引

- 负载高低对照 `load.cpu_count`（核数）：load1 持续超过核数才算吃紧。
- 内存占用以 `memory.used_percent`（基于 MemAvailable）为准。
- `container.memory` 接近限额时机器人自己有 OOM 风险，与整机内存余量是两回事。
- `disk` 只是 data 卷所在分区；全盘视图看 `host_metrics.metrics.disks`。

## 禁止事项

- 只跑 `scripts/collect.py`；不要借 run_skill_script 执行与采集无关的命令。
- 脚本只读；不要尝试修改任何系统或容器状态。
- 不要向用户粘贴原始 JSON 或冗长字段，转述关键数字即可。
