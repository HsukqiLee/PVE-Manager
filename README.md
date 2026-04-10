# PVE-Manager

PVE 管理脚本，支持菜单化管理 NAT、端口转发、额外端口转发配置、动态限速、昵称、电源控制。

## 新增能力

- 安装机制: 支持指定安装目录与配置路径。
- 更新机制: 根据安装元数据自动定位原安装路径并更新文件。
- 配置模块化: 支持在配置中自定义 ID-IP 解析规则、全局端口转发规则、单 VM 规则覆写。
- 额外转发 Profile: 可配置多个“命名端口转发组”（例如“三网端口”“GPU实验端口”）。
- VMID 精细策略: 支持 vm 范围、模板范围、范围外默认动作、单独 id 动作。
- 配置校验与预演: 支持 `validate`、`preview_rules`、`backup_config`。
- 每分钟自动任务: `sync_all --type tc` + `dyn_tc_check`。
- 动态限速引擎: 基于 `vnstat` 的阈值触发、自动解除、冷却期控制。
- 流量图表导出: 基于 `vnstati` 生成小时/日/月/汇总图。
- 兼容旧配置: 旧版平铺结构会自动迁移到新版结构。
- 多模块架构: 核心逻辑拆分为 `vmmgr_core/config.py`、`vmmgr_core/policy.py`、`vmmgr_core/rules.py`、`vmmgr_core/ops.py`、`vmmgr_core/ui.py`、`vmmgr_core/cli.py`。

## 依赖

- Python3 + pip
- `rich`
- `vnstat`（含 `vnstati`）
- `conntrack`（连接数统计）

`install.sh` 会尝试自动安装缺失依赖；失败时会打印手动安装提示。

## 安装

### 在线下载脚本（raw.githubusercontent.com）

```bash
curl -fsSL -o install.sh https://raw.githubusercontent.com/HsukqiLee/PVE-Manager/main/install.sh
curl -fsSL -o update.sh https://raw.githubusercontent.com/HsukqiLee/PVE-Manager/main/update.sh
chmod +x install.sh update.sh
```

如果你只想下载入口脚本进行查看:

```bash
curl -fsSL -o vmmgr.sh https://raw.githubusercontent.com/HsukqiLee/PVE-Manager/main/vmmgr.sh
curl -fsSL -o vmmgrctl.py https://raw.githubusercontent.com/HsukqiLee/PVE-Manager/main/vmmgrctl.py
```

说明: 运行需要 vmmgr_core 目录，建议优先使用 install.sh 完整安装。

### Release 压缩包安装（推荐）

通过 raw 读取 `RELEASE_TAG`，再从 codeload 下载对应 tag 的压缩包，不依赖 GitHub API，避免 API 限频。

```bash
curl -fsSL -o install.sh https://raw.githubusercontent.com/HsukqiLee/PVE-Manager/main/install.sh
chmod +x install.sh
./install.sh
```

可指定 tag:

```bash
./install.sh --from-release --tag v1.2.3
```

默认安装来源为 release 压缩包；如需本地源码安装:

```bash
./install.sh --local
```

仅预览安装动作（不执行下载/安装）:

```bash
./install.sh --dry-run
```

```bash
chmod +x install.sh update.sh
./install.sh --install-dir /usr/local/bin --config /etc/pve/vmnat_config.json
```

可选参数:

- `--install-dir PATH`: 安装目录。
- `--config PATH`: 配置文件路径。
- `--meta PATH`: 安装元数据路径。
- `--disable-cron`: 不自动注册每分钟任务（tc 同步 + 动态限速检查）。

安装后可直接运行:

```bash
/usr/local/bin/vmmgr
```

## 更新

```bash
./update.sh
```

默认 `update.sh` 会走 release 压缩包更新（raw RELEASE_TAG + codeload zip）。
当远端 RELEASE_TAG 与本地安装记录一致时，会自动跳过更新。

使用本地目录更新:

```bash
./update.sh --local
```

指定 tag 更新:

```bash
./update.sh --tag v1.2.3
```

即使 tag 未变化也强制更新:

```bash
./update.sh --force
```

仅预览更新动作（显示本地 tag、目标 tag、下载地址、是否跳过）:

```bash
./update.sh --dry-run
```

如果你把安装元数据放到了自定义路径:

```bash
./update.sh /path/to/vmmgr_install.conf
```

## 配置说明

默认配置见 [vmnat_config.example.json](vmnat_config.example.json)。

新版配置主结构:

- `settings.id_ip_rules`: ID 到 IP 的解析规则。
- `settings.port_forward_rules`: 全局端口转发模板规则。
- `settings.extra_forward_profiles`: 额外端口转发配置组（可命名、可单独控制）。
- `settings.vmid_policy`: VMID 精细策略（vm/template/outside + allow/ignore/deny）。
- `settings.operation_policy`: 操作语义策略（模板允许哪些操作、ignore 是否允许单点放行）。
- `settings.port_conflict_policy`: 端口冲突策略（优先级、自动避让、严格报错）。
- `settings.dynamic_tc`: 动态限速策略（vnstat 阈值、限速时长、冷却时长、限速值）。
- `settings.monitoring`: 监控策略（告警阈值、快照策略、自动清理、API schema/source）。
- `vms.<vmid>.port_rules`: 单 VM 的规则扩展。
- `vms.<vmid>.custom_ports`: 菜单中维护的自定义映射。
- `vms.<vmid>.profile_overrides`: 针对某个 profile 的启停和范围覆写。

### Hook 脚本

- Hook 绑定文件名为 `local:snippets/hook.py`。
- 在菜单执行 Hook 绑定时，会自动创建/更新 `/var/lib/vz/snippets/hook.py`。
- `hook.py` 会把生命周期事件转发给 `vmmgrctl.py hook --vmid <id> --phase <phase>`。

### VMID 精细策略

`settings.vmid_policy` 示例:

- `vm_ranges`: 正常 VM 范围（可做 NAT/限速/电源等）
- `template_ranges`: 模板范围（默认只允许 Hook 操作）
- `outside_default_action`: 范围外默认动作
- `id_actions`: 对单个 id 指定动作 (`allow` / `ignore` / `deny`)

语义:

- `allow`: 视同合法 VMID。
- `ignore`: 批量操作自动忽略，但单独指定该 ID 时允许执行。
- `deny`: 拒绝对该 ID 执行操作。

模板范围策略:

- 模板范围 ID 默认不允许端口转发和流控等网络规则变更。
- 模板范围仍允许 Hook 管理。

可进一步调整:

- `scope_allowed_ops`: 按 scope 允许的操作集合（vm/template/outside）。
- `action_allowed_ops`: 按 action 允许的操作集合（allow/ignore_explicit/ignore_batch）。
- `outside_ignore_explicit`: 控制范围外 `ignore` 的 ID 是否允许单独指定执行。

### 端口冲突策略

`settings.port_conflict_policy` 关键项:

- `mode`: `priority-skip` / `priority-remap` / `strict-error`
- `priority`: 按来源类型优先级（global_rule/profile/vm_rule/custom）
- `profile_priority`: 对指定 profile 再加权
- `remap_range`: 自动避让时可分配端口区间

### ID-IP 规则

支持两种模式:

1. `map` 直接映射指定 VMID。
2. `pattern + template` 正则与模板。

模板变量示例:

- `{id}`
- `{id_div_10}`
- `{id_mod_10}`
- `{id_hundreds}`
- `{id_tens}`
- `{id_ones}`
- `{g1}`...`{g9}` (正则分组)

### 端口转发规则模板

常用字段:

- `enabled`
- `vmid_min` / `vmid_max`
- `vmid_regex`
- `protocols` (`tcp`/`udp`)
- `ext` / `int` (支持模板变量)

端口模板变量:

- `{base_port}`
- `{base_port_plus1}`
- `{base_port_plus99}`
- `{default_ssh_port}`
- `{profile_start}`
- `{profile_end}`
- `{profile_start_plus1}`

### 额外转发 Profile

通过 `settings.extra_forward_profiles` 定义命名转发组，例如:

- `id`: 内部标识（如 `trinet`）
- `name`: 展示名（如“三网端口”）
- `default_start`: 起始端口
- `per_vm_size`: 每台 VM 分配端口数量
- `entries`: 组内具体转发规则模板

你可以在菜单“额外转发”里按 VM 启用/禁用某个 profile，并单独覆写范围。

### 校验与预览

```bash
# 配置结构和冲突检查
/usr/local/bin/vmmgrctl.py validate

# 仅按指定 VM 检查冲突样本
/usr/local/bin/vmmgrctl.py validate --vmids "101,105-110"

# 预览某台 VM 最终展开的 NAT 规则
/usr/local/bin/vmmgrctl.py preview_rules --vmid 101

# 批量解析时指定操作语义（用于策略过滤）
/usr/local/bin/vmmgrctl.py parse_vms --input "all,101,1000-1002" --op nat

# 备份配置
/usr/local/bin/vmmgrctl.py backup_config

# 动态限速: 立即执行一次检查
/usr/local/bin/vmmgrctl.py dyn_tc_check

# 查看动态限速状态
/usr/local/bin/vmmgrctl.py dyn_tc_status

# 手动解除某台 VM 的动态限速
/usr/local/bin/vmmgrctl.py dyn_tc_release --vmid 101

# 动态引擎开关
/usr/local/bin/vmmgrctl.py dyn_engine --enabled 1

# 动态规则 CRUD
/usr/local/bin/vmmgrctl.py dyn_rule_list
/usr/local/bin/vmmgrctl.py dyn_rule_add --name burst-protect --vmid-min 100 --vmid-max 199 --window 10 --rx 3072 --tx 1536 --throttle 30 --cooldown 20 --dn 80mbit --up 30mbit --enabled 1
/usr/local/bin/vmmgrctl.py dyn_rule_edit --idx 0 --rx 4096 --tx 2048
/usr/local/bin/vmmgrctl.py dyn_rule_toggle --idx 0 --enabled 0
/usr/local/bin/vmmgrctl.py dyn_rule_del --idx 0

# 动态规则预设模板（home/idc/night）
/usr/local/bin/vmmgrctl.py dyn_rule_preset --preset home --vmid-min 100 --vmid-max 199 --enabled 1

# 生成 vnstat 图表（summary/hour/day/month/top）
/usr/local/bin/vmmgrctl.py vnstat_report --vmid 101 --mode day --limit 7 --out /tmp/vm101_day.png

# 查看连接数统计（基于 conntrack）
/usr/local/bin/vmmgrctl.py conn_stats --vmid 101

# 批量流量图导出
/usr/local/bin/vmmgrctl.py batch_vnstat_report --input "all,101,105-110" --mode day --limit 7 --out-dir /tmp/vnstati_batch

# 批量连接统计
/usr/local/bin/vmmgrctl.py batch_conn_stats --input "all,101,105-110"

# 节点健康（CPU/内存/磁盘/load）
/usr/local/bin/vmmgrctl.py node_health

# 监控快照导出（总览+动态状态+节点健康）
/usr/local/bin/vmmgrctl.py monitor_snapshot --out /tmp/vmmgr_snapshot.json

# 告警检查（命中阈值将写入审计日志；可自动生成告警快照）
/usr/local/bin/vmmgrctl.py alert_check

# 自动清理（按保留天数清理历史图表/快照）
/usr/local/bin/vmmgrctl.py cleanup_auto

# 统一 API 导出（schema 固定，便于对接 Telegram/企业微信/Webhook）
/usr/local/bin/vmmgrctl.py api_export --type overview --out /tmp/vmmgr_api_overview.json
/usr/local/bin/vmmgrctl.py api_export --type alerts --out /tmp/vmmgr_api_alerts.json
/usr/local/bin/vmmgrctl.py api_export --type conn --input "all,101,105-110" --out /tmp/vmmgr_api_conn.json

# 监控总览
/usr/local/bin/vmmgrctl.py monitor_overview
```

## 交互优化

- 主菜单新增 `12. 监控中心`。
- 监控中心内置动态规则增删改查、预设模板、引擎开关、立即检查、状态查看、单台/批量图表、单台/批量连接统计、节点健康、快照导出、告警检查、自动清理、API 导出、总览。
- 限速菜单保留快捷操作，监控中心用于完整运维管理。

### 功能清单

```bash
/usr/local/bin/vmmgrctl.py show_features
```

## 兼容性

- 旧版本配置中的顶层 VMID 键会自动迁移到 `vms`。
- 原有命令行子命令保持可用。
- `vmmgr.sh` 会优先读取安装元数据中的路径配置。