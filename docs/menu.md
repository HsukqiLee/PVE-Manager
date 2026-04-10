# 菜单与功能说明

本文档说明 `vmmgr` 交互菜单中每个编号的具体作用，以及对应调用的核心命令。

## 主菜单

### 1. 状态总览
- 功能: 仅查看当前虚拟机状态、IP、规则数量、限速状态、运行状态。
- 等价命令: `vmmgrctl.py list`

### 2. Hook 管理
- 功能: 为 VM/LXC 绑定或解绑 Hook 脚本（`local:snippets/hook.py`）。
- 子菜单:
1. 绑定: 自动确保 hook.py 存在并写入实例配置。
2. 解绑: 删除实例配置中的 `hookscript:` 行。
0. 返回

### 3. 额外转发
- 功能: 按 Profile（如 `trinet`）启用/禁用/覆写某台 VM 的额外端口转发。
- 子菜单:
1. 启用: `xpf_act --act enable`
2. 禁用: `xpf_act --act disable`
3. 改范围: `xpf_act --act modify --range START-END`
0. 返回

### 4. 端口转发
- 功能: 管理单 VM 自定义端口映射（增/改/删）并应用 NAT 规则。
- 子菜单:
1. 管理
: 进入后支持:
- 新增映射: `manage_port --act add` + `apply_nat --act add`
- 修改映射: `manage_port --act edit` + `apply_nat --act add`
- 删除映射: `manage_port --act del` + `apply_nat --act add`
0. 返回

### 5. 动态限速
- 功能: 管理全局/单 VM 限速时段，触发动态限速检查、解除动态限速、查看流量图和连接统计。
- 子菜单:
1. 全局: 新增全局限速时段（`manage_limit --type global`）
2. 专属: 为指定 VM 新增限速时段（`manage_limit --type vm`）
3. 清实例: 清理 VM 专属限速（`clear_limit --type vm`）
4. 清全局: 清理全局限速（`clear_limit --type global`）
5. 动态检查: 立即执行一次 `dyn_tc_check`
6. 解除动态限速: `dyn_tc_release --vmid`
7. 生成流量图: `vnstat_report --vmid ...`
8. 连接数统计: `conn_stats --vmid ...`
0. 返回

### 6. 昵称设置
- 功能: 批量或单台设置/清空昵称。
- 子菜单:
1. 修改: `manage_nick --act set/clear`
0. 返回

### 7. 电源控制
- 功能: 启动/关闭/重启实例（按 VMID 或范围）。
- 子菜单:
1. 启动: `power --act start`
2. 关闭: `power --act stop`
3. 重启: `power --act reboot`
0. 返回

### 8. 规则刷新
- 功能: 立即重建并同步 NAT + TC 规则。
- 等价命令: `sync_all --type all`

### 9. 网络重置
- 功能: 先清理再重建网络规则。
- 等价命令: `sync_all --type all --reset`

### 10. 配置校验
- 功能: 校验配置结构与冲突。
- 等价命令: `validate`

### 11. 规则预览
- 功能: 预览指定 VM 最终展开的规则。
- 等价命令: `preview_rules --vmid <id>`

### 12. 监控中心
- 功能: 动态限速规则运维、节点监控、快照与 API 导出。
- 子菜单:
1. 规则列表: `dyn_rule_list`
2. 新增规则: `dyn_rule_add`
3. 修改规则: `dyn_rule_edit`
4. 删除规则: `dyn_rule_del`
5. 启停规则: `dyn_rule_toggle`
6. 启停引擎: `dyn_engine`
7. 快速预设: `dyn_rule_preset --preset home|idc|night`
8. 立即检查: `dyn_tc_check`
9. 状态查看: `dyn_tc_status`
10. 单台流量图: `vnstat_report --vmid ...`
11. 单台连接统计: `conn_stats --vmid ...`
12. 批量流量图: `batch_vnstat_report --input ...`
13. 批量连接统计: `batch_conn_stats --input ...`
14. 节点健康: `node_health`
15. 导出快照: `monitor_snapshot --out ...`
16. 概览: `monitor_overview`
17. 告警检查: `alert_check`
18. 自动清理: `cleanup_auto`
19. API 导出: `api_export --type ...`
0. 返回

### 0. 退出系统
- 功能: 退出 `vmmgr`。

## 命令行入口

- 交互菜单: `vmmgr`
- 功能列表: `vmmgrctl.py show_features`
- 配置模板: `vmmgrctl.py show_config_schema`
