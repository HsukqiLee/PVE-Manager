# pyright: reportMissingImports=false
import argparse
import json
import os

from rich.panel import Panel
from rich.table import Table

from .config import default_config, load_config, parse_days, save_config
from .constants import DEFAULT_CONFIG_FILE
from .ops import (
    alert_check,
    apply_nat,
    apply_tc,
    backup_config,
    cleanup_auto,
    dynamic_tc_check,
    dynamic_tc_release,
    dynamic_tc_status,
    ensure_hook_script,
    get_all_vms,
    get_current_limit,
    handle_hook_event,
    export_api_payload,
    monitor_snapshot,
    parse_vms_str,
    node_health,
    power_action,
    sync_all,
    vm_connection_stats,
    vnstat_report,
)
from .policy import vmid_access
from .rules import get_vm_conf, get_vm_ip, preview_rules, to_json, validate_config, validate_port_expr
from .ui import console, format_bw, format_limits, get_os_nickname, has_hook, render_main_menu, render_submenu
from .utils import audit


def cmd_validate(conf, vmids_input="", json_mode=False):
    sample = None
    if vmids_input:
        sample = parse_vms_str(vmids_input, conf, operation="nat").split()
    errors, warnings = validate_config(conf, sample_vmids=sample, get_all_vms_func=lambda: get_all_vms(conf))
    payload = {"errors": errors, "warnings": warnings, "ok": len(errors) == 0}

    if json_mode:
        print(to_json(payload))
        return 0 if payload["ok"] else 2

    if errors:
        console.print("[bold red]错误[/]")
        for e in errors:
            console.print(f" - {e}")
    if warnings:
        console.print("[bold yellow]警告[/]")
        for w in warnings:
            console.print(f" - {w}")
    if not errors and not warnings:
        console.print("[bold green]配置检查通过，无错误无警告[/]")
    return 0 if not errors else 2


def show_config_schema():
    console.print(Panel(to_json(default_config()), title="配置模板", border_style="green"))


def show_features():
    items = [
        "模块化拆分（config/policy/rules/ops/ui/cli）",
        "VMID 策略: vm/template/outside + allow/ignore/deny",
        "操作权限矩阵: scope_allowed_ops + action_allowed_ops 可细化到操作级",
        "模板范围 VM 仅允许 hook，不允许端口转发与流控",
        "批量时自动忽略 ignore/outside/template；单点指定可按策略执行",
        "可命名额外转发 profile（按 VM 启停与范围覆写）",
        "端口冲突策略: priority-skip / priority-remap / strict-error",
        "validate 配置校验 + 冲突检测",
        "preview_rules 规则预览",
        "backup_config 配置备份",
        "动态限速: vnstat 阈值触发 + 冷却 + 手动解除",
        "流量图: vnstati 按小时/日/月导出",
        "告警策略: CPU/内存/磁盘/连接数阈值",
        "自动清理: 历史图表/快照按天保留",
        "API 导出: 统一 schema 便于 Webhook 集成",
        "命令路径可配置（pvesh/iptables/tc/qm/pct）",
        "行为参数可配置（默认 ssh/rdp 端口、postrouting cidr）",
    ]
    console.print(Panel("\n".join([f"- {x}" for x in items]), title="已支持功能", border_style="green"))


def ensure_dyn_tc(conf):
    settings = conf.setdefault("settings", {})
    dyn = settings.setdefault("dynamic_tc", {})
    dyn.setdefault("enabled", False)
    dyn.setdefault("state_file", "/var/lib/vmmgr/dyn_tc_state.json")
    dyn.setdefault("rules", [])
    return dyn


def handle_menus(cmd, conf):
    all_vms = get_all_vms(conf)

    if cmd == "menu":
        render_main_menu(conf, all_vms, get_current_limit, True)
        return True
    if cmd == "list":
        render_main_menu(conf, all_vms, get_current_limit, False)
        return True

    if cmd == "show_menu_hook":
        hook_vms = get_all_vms(conf, include_templates=True)

        def ext(vm, c):
            o, n = get_os_nickname(vm.get("name", "-"), c.get("nickname"))
            return [str(vm["vmid"]), f"{o} ({n})", "[green]Yes[/]" if has_hook(str(vm["vmid"])) else "[dim]No[/]"]

        render_submenu("Hook 脚本管理", ["ID", "特征", "状态"], ext, ["[bold cyan]1.[/] 绑定", "[bold red]2.[/] 解绑", "[bold white]0.[/] 返回"], conf, hook_vms)
        return True

    if cmd == "show_menu_xpf":

        def ext(vm, c):
            vmid = str(vm["vmid"])
            o, n = get_os_nickname(vm.get("name", "-"), c.get("nickname"))
            from .rules import get_profile_status_for_vm

            return [vmid, f"{o} ({n})", get_profile_status_for_vm(vmid, c, conf)]

        render_submenu("额外端口转发", ["ID", "特征", "Profiles"], ext, ["[bold cyan]1.[/] 启用", "[bold red]2.[/] 禁用", "[bold yellow]3.[/] 改范围", "[bold white]0.[/] 返回"], conf, all_vms)
        return True

    if cmd == "show_menu_speed":
        console.print(Panel(f"{format_limits(conf.get('global_limits', []))}", title="[bold yellow]全局流控规则[/]", border_style="yellow"))

        def ext(vm, c):
            o, n = get_os_nickname(vm.get("name", "-"), c.get("nickname"))
            dn, up = get_current_limit(str(vm["vmid"]), c, conf)
            return [
                str(vm["vmid"]),
                f"{o} ({n})",
                f"{format_bw(dn)} / {format_bw(up)}",
                format_limits(c.get("limits")) if "limits" in c else "[dim]随全局[/]",
            ]

        render_submenu(
            "动态流控管理",
            ["ID", "特征", "当前", "专属列表"],
            ext,
            [
                "[bold cyan]1.[/] 全局",
                "[bold yellow]2.[/] 专属",
                "[bold red]3.[/] 清实例",
                "[bold magenta]4.[/] 清全局",
                "[bold green]5.[/] 动态检查",
                "[bold green]6.[/] 解除动态限速",
                "[bold blue]7.[/] 生成流量图",
                "[bold blue]8.[/] 连接数统计",
                "[bold white]0.[/] 返回",
            ],
            conf,
            all_vms,
        )
        return True

    if cmd == "show_menu_nat":

        def ext(vm, c):
            v = str(vm["vmid"])
            o, n = get_os_nickname(vm.get("name", "-"), c.get("nickname"))
            return [v, f"{o} ({n})", get_vm_ip(v, conf), str(len(c.get("custom_ports", [])))]

        render_submenu("端口转发管理", ["ID", "特征", "内网IP", "自定义数"], ext, ["[bold cyan]1.[/] 管理", "[bold white]0.[/] 返回"], conf, all_vms)
        return True

    if cmd == "show_menu_nickname":

        def ext(vm, c):
            r = vm.get("name", "-")
            o, n = get_os_nickname(r, c.get("nickname"))
            return [str(vm["vmid"]), r, o, n, "[bold green]已配[/]" if c.get("nickname") else "[dim]默认[/]"]

        render_submenu("实例昵称设置", ["ID", "原始名", "OS", "昵称", "状态"], ext, ["[bold cyan]1.[/] 修改", "[bold white]0.[/] 返回"], conf, all_vms)
        return True

    if cmd == "show_menu_power":

        def ext(vm, c):
            o, n = get_os_nickname(vm.get("name", "-"), c.get("nickname"))
            return [str(vm["vmid"]), f"{o} ({n})", "[bold green]Running[/]" if vm.get("status") == "running" else "[bold red]Stopped[/]"]

        render_submenu("电源控制", ["ID", "特征", "状态"], ext, ["[bold green]1.[/] 启动", "[bold red]2.[/] 关闭", "[bold yellow]3.[/] 重启", "[bold white]0.[/] 返回"], conf, all_vms)
        return True

    if cmd == "show_menu_monitor":
        dyn_rows = dynamic_tc_status(conf)
        dyn_map = {}
        for r in dyn_rows:
            dyn_map.setdefault(str(r.get("vmid", "")), 0)
            dyn_map[str(r.get("vmid", ""))] += 1

        def ext(vm, c):
            vmid = str(vm["vmid"])
            o, n = get_os_nickname(vm.get("name", "-"), c.get("nickname"))
            cnt = dyn_map.get(vmid, 0)
            dyn_s = f"{cnt} 条" if cnt > 0 else "无"
            return [vmid, f"{o} ({n})", dyn_s, "运行" if vm.get("status") == "running" else "停止"]

        render_submenu(
            "监控中心",
            ["ID", "特征", "动态限速", "状态"],
            ext,
            [
                "[bold cyan]1.[/] 规则列表",
                "[bold cyan]2.[/] 新增规则",
                "[bold yellow]3.[/] 修改规则",
                "[bold red]4.[/] 删除规则",
                "[bold green]5.[/] 启停规则",
                "[bold green]6.[/] 启停引擎",
                "[bold green]7.[/] 快速预设",
                "[bold magenta]8.[/] 立即检查",
                "[bold magenta]9.[/] 状态查看",
                "[bold blue]10.[/] 单台流量图",
                "[bold blue]11.[/] 单台连接统计",
                "[bold blue]12.[/] 批量流量图",
                "[bold blue]13.[/] 批量连接统计",
                "[bold white]14.[/] 节点健康",
                "[bold white]15.[/] 导出快照",
                "[bold white]16.[/] 概览",
                "[bold red]17.[/] 告警检查",
                "[bold yellow]18.[/] 自动清理",
                "[bold cyan]19.[/] API 导出",
                "[bold white]0.[/] 返回",
            ],
            conf,
            all_vms,
        )
        return True

    return False


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=DEFAULT_CONFIG_FILE, help="配置文件路径")
    subparsers = parser.add_subparsers(dest="cmd")

    for c in [
        "menu",
        "list",
        "show_menu_hook",
        "show_menu_xpf",
        "show_menu_speed",
        "show_menu_monitor",
        "show_menu_nat",
        "show_menu_nickname",
        "show_menu_power",
        "show_config_schema",
        "show_features",
    ]:
        subparsers.add_parser(c)

    p = subparsers.add_parser("p_list")
    p.add_argument("--vmid", required=True)

    p = subparsers.add_parser("manage_limit")
    p.add_argument("--type", required=True, choices=["global", "vm"])
    p.add_argument("--vmid")
    p.add_argument("--days")
    p.add_argument("--ts")
    p.add_argument("--te")
    p.add_argument("--dr")
    p.add_argument("--ur")

    p = subparsers.add_parser("clear_limit")
    p.add_argument("--type", required=True, choices=["global", "vm"])
    p.add_argument("--vmid")
    p.add_argument("--idx", default="")

    p = subparsers.add_parser("manage_port")
    p.add_argument("--vmid", required=True)
    p.add_argument("--act", required=True, choices=["add", "edit", "del"])
    p.add_argument("--idx")
    p.add_argument("--ext")
    p.add_argument("--int_port")
    p.add_argument("--proto")

    p = subparsers.add_parser("manage_nick")
    p.add_argument("--vmid", required=True)
    p.add_argument("--act", required=True, choices=["set", "clear"])
    p.add_argument("--nick")

    p = subparsers.add_parser("parse_vms")
    p.add_argument("--input", required=True)
    p.add_argument("--op", default="general")

    p = subparsers.add_parser("get_ip")
    p.add_argument("--vmid", required=True)

    p = subparsers.add_parser("apply_nat")
    p.add_argument("--vmid", required=True)
    p.add_argument("--act", required=True)

    p = subparsers.add_parser("apply_tc")
    p.add_argument("--vmid", required=True)
    p.add_argument("--act", required=True)

    p = subparsers.add_parser("sync_all")
    p.add_argument("--type", required=True)
    p.add_argument("--reset", action="store_true")

    p = subparsers.add_parser("power")
    p.add_argument("--vmid", required=True)
    p.add_argument("--act", required=True)

    p = subparsers.add_parser("xpf_act")
    p.add_argument("--act", required=True, choices=["enable", "disable", "modify"])
    p.add_argument("--vmid", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--range", default="")

    p = subparsers.add_parser("validate")
    p.add_argument("--vmids", default="")
    p.add_argument("--json", action="store_true")

    p = subparsers.add_parser("preview_rules")
    p.add_argument("--vmid", required=True)
    p.add_argument("--json", action="store_true")

    p = subparsers.add_parser("backup_config")
    p.add_argument("--out", default="")

    p = subparsers.add_parser("dyn_tc_check")

    p = subparsers.add_parser("dyn_tc_status")
    p.add_argument("--vmid", default="")
    p.add_argument("--json", action="store_true")

    p = subparsers.add_parser("dyn_tc_release")
    p.add_argument("--vmid", required=True)

    p = subparsers.add_parser("dyn_engine")
    p.add_argument("--enabled", required=True, choices=["0", "1"])

    p = subparsers.add_parser("dyn_rule_list")
    p.add_argument("--json", action="store_true")

    p = subparsers.add_parser("dyn_rule_add")
    p.add_argument("--name", required=True)
    p.add_argument("--vmid-min", required=True)
    p.add_argument("--vmid-max", required=True)
    p.add_argument("--window", required=True)
    p.add_argument("--rx", required=True)
    p.add_argument("--tx", required=True)
    p.add_argument("--throttle", required=True)
    p.add_argument("--cooldown", required=True)
    p.add_argument("--dn", required=True)
    p.add_argument("--up", required=True)
    p.add_argument("--enabled", default="1", choices=["0", "1"])

    p = subparsers.add_parser("dyn_rule_edit")
    p.add_argument("--idx", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--vmid-min", default="")
    p.add_argument("--vmid-max", default="")
    p.add_argument("--window", default="")
    p.add_argument("--rx", default="")
    p.add_argument("--tx", default="")
    p.add_argument("--throttle", default="")
    p.add_argument("--cooldown", default="")
    p.add_argument("--dn", default="")
    p.add_argument("--up", default="")
    p.add_argument("--enabled", default="", choices=["", "0", "1"])

    p = subparsers.add_parser("dyn_rule_del")
    p.add_argument("--idx", required=True)

    p = subparsers.add_parser("dyn_rule_toggle")
    p.add_argument("--idx", required=True)
    p.add_argument("--enabled", required=True, choices=["0", "1"])

    p = subparsers.add_parser("dyn_rule_preset")
    p.add_argument("--preset", required=True, choices=["home", "idc", "night"])
    p.add_argument("--vmid-min", required=True)
    p.add_argument("--vmid-max", required=True)
    p.add_argument("--enabled", default="1", choices=["0", "1"])

    p = subparsers.add_parser("monitor_overview")
    p.add_argument("--json", action="store_true")

    p = subparsers.add_parser("node_health")
    p.add_argument("--json", action="store_true")

    p = subparsers.add_parser("batch_vnstat_report")
    p.add_argument("--input", required=True)
    p.add_argument("--mode", default="summary", choices=["summary", "hour", "day", "month", "top"])
    p.add_argument("--limit", default="24")
    p.add_argument("--out-dir", required=True)

    p = subparsers.add_parser("batch_conn_stats")
    p.add_argument("--input", required=True)
    p.add_argument("--json", action="store_true")

    p = subparsers.add_parser("monitor_snapshot")
    p.add_argument("--out", default="")

    p = subparsers.add_parser("alert_check")
    p.add_argument("--json", action="store_true")

    p = subparsers.add_parser("cleanup_auto")
    p.add_argument("--json", action="store_true")

    p = subparsers.add_parser("api_export")
    p.add_argument("--type", required=True, choices=["overview", "node", "alerts", "conn", "snapshot"])
    p.add_argument("--vmid", default="")
    p.add_argument("--input", default="")
    p.add_argument("--out", default="")

    p = subparsers.add_parser("vnstat_report")
    p.add_argument("--vmid", required=True)
    p.add_argument("--mode", default="summary", choices=["summary", "hour", "day", "month", "top"])
    p.add_argument("--limit", default="24")
    p.add_argument("--out", required=True)

    p = subparsers.add_parser("conn_stats")
    p.add_argument("--vmid", required=True)
    p.add_argument("--json", action="store_true")

    p = subparsers.add_parser("ensure_hook_script")

    p = subparsers.add_parser("hook")
    p.add_argument("--vmid", required=True)
    p.add_argument("--phase", required=True)

    return parser


def run():
    parser = build_parser()
    args = parser.parse_args()
    if not args.cmd:
        return

    conf = load_config(args.config)

    if handle_menus(args.cmd, conf):
        return

    if args.cmd == "show_config_schema":
        show_config_schema()
        return
    if args.cmd == "show_features":
        show_features()
        return

    if args.cmd == "p_list":
        vmid = args.vmid
        vm_c = get_vm_conf(conf, vmid)
        table = Table(title=f"VM {vmid} 映射", expand=True)
        for h in ["编号", "名称", "协议", "外网", "内网"]:
            table.add_column(h)
        from .rules import expand_port_rules

        for idx, (name, ext_port, int_port, proto) in enumerate(expand_port_rules(vmid, conf, vm_c)):
            table.add_row(str(idx), str(name), proto, ext_port.replace(":", "-"), int_port.replace(":", "-"))
        console.print(table)
        return

    if args.cmd == "manage_limit":
        days = parse_days(args.days)
        try:
            ts, te = int(args.ts), int(args.te)
        except Exception:
            ts, te = 0, 24
        dn = f"{args.dr}mbit" if args.dr not in ["0", "-", "", None] else "-"
        up = f"{args.ur}mbit" if args.ur not in ["0", "-", "", None] else "-"

        if args.type == "global":
            conf.setdefault("global_limits", []).append({"days": days, "s": ts, "e": te, "dn": dn, "up": up})
        else:
            access = vmid_access(args.vmid, conf, operation="tc", explicit=True, batch=False)
            if not access["allow"]:
                print(f"拒绝: {access['reason']}")
                raise SystemExit(2)
            vm = get_vm_conf(conf, args.vmid)
            vm.setdefault("limits", []).append({"days": days, "s": ts, "e": te, "dn": dn, "up": up})
        save_config(conf, args.config)
        return

    if args.cmd == "clear_limit":
        if args.type == "global":
            if args.idx == "":
                conf.pop("global_limits", None)
            else:
                try:
                    conf.setdefault("global_limits", []).pop(int(args.idx))
                except Exception:
                    pass
        else:
            access = vmid_access(args.vmid, conf, operation="tc", explicit=True, batch=False)
            if not access["allow"]:
                print(f"拒绝: {access['reason']}")
                raise SystemExit(2)
            vm = get_vm_conf(conf, args.vmid)
            if args.idx == "":
                vm.pop("limits", None)
            else:
                try:
                    vm.setdefault("limits", []).pop(int(args.idx))
                except Exception:
                    pass
        save_config(conf, args.config)
        return

    if args.cmd == "manage_port":
        access = vmid_access(args.vmid, conf, operation="nat", explicit=True, batch=False)
        if not access["allow"]:
            print(f"拒绝: {access['reason']}")
            raise SystemExit(2)

        if args.act == "add":
            if not validate_port_expr(args.ext):
                print("错误: 外网端口格式非法")
                raise SystemExit(2)
            if not validate_port_expr(args.int_port):
                print("错误: 内网端口格式非法")
                raise SystemExit(2)
            if str(args.proto or "tcp").lower() not in ["tcp", "udp"]:
                print("错误: 协议仅支持 tcp/udp")
                raise SystemExit(2)

        vm = get_vm_conf(conf, args.vmid)
        if args.act == "add":
            vm.setdefault("custom_ports", []).append({"ext": args.ext, "int": args.int_port, "proto": (args.proto or "tcp").lower()})
        elif args.act == "edit":
            p = vm.setdefault("custom_ports", [])
            i = int(args.idx)
            if 0 <= i < len(p):
                if args.ext and args.ext != "-":
                    if not validate_port_expr(args.ext):
                        print("错误: 外网端口格式非法")
                        raise SystemExit(2)
                    p[i]["ext"] = args.ext
                if args.int_port and args.int_port != "-":
                    if not validate_port_expr(args.int_port):
                        print("错误: 内网端口格式非法")
                        raise SystemExit(2)
                    p[i]["int"] = args.int_port
                if args.proto and args.proto != "-":
                    if str(args.proto).lower() not in ["tcp", "udp"]:
                        print("错误: 协议仅支持 tcp/udp")
                        raise SystemExit(2)
                    p[i]["proto"] = args.proto.lower()
        elif args.act == "del":
            try:
                vm.setdefault("custom_ports", []).pop(int(args.idx))
            except Exception:
                pass
        save_config(conf, args.config)
        return

    if args.cmd == "manage_nick":
        vm = get_vm_conf(conf, args.vmid)
        if args.act == "set":
            vm["nickname"] = args.nick
        else:
            vm.pop("nickname", None)
        save_config(conf, args.config)
        return

    if args.cmd == "parse_vms":
        print(parse_vms_str(args.input, conf, operation=args.op))
        return

    if args.cmd == "get_ip":
        print(get_vm_ip(args.vmid, conf))
        return

    if args.cmd == "apply_nat":
        status = apply_nat(args.vmid, args.act, conf, explicit=True, batch=False)
        if status not in ["ok", "deleted"]:
            raise SystemExit(2)
        return

    if args.cmd == "apply_tc":
        status = apply_tc(args.vmid, args.act, conf, explicit=True, batch=False)
        if status not in ["ok", "deleted"]:
            raise SystemExit(2)
        return

    if args.cmd == "sync_all":
        sync_all(args.type, args.reset, conf)
        return

    if args.cmd == "power":
        if not power_action(args.vmid, args.act, conf):
            raise SystemExit(2)
        return

    if args.cmd == "xpf_act":
        access = vmid_access(args.vmid, conf, operation="nat", explicit=True, batch=False)
        if not access["allow"]:
            print(f"拒绝: {access['reason']}")
            raise SystemExit(2)

        vm = get_vm_conf(conf, args.vmid)
        vm.setdefault("profile_overrides", {})
        vm["profile_overrides"].setdefault(args.profile, {})
        if args.act in ["enable", "disable"]:
            vm["profile_overrides"][args.profile]["enabled"] = args.act == "enable"
            audit(f"Extra profile {args.profile} {args.act} for VM {args.vmid}")
        elif args.act == "modify":
            vm["profile_overrides"][args.profile]["range_override"] = args.range
            audit(f"Extra profile {args.profile} range modified for VM {args.vmid}: {args.range}")

        save_config(conf, args.config)
        apply_nat(args.vmid, "add", conf, explicit=True, batch=False)
        return

    if args.cmd == "validate":
        raise SystemExit(cmd_validate(conf, args.vmids, args.json))

    if args.cmd == "preview_rules":
        access = vmid_access(args.vmid, conf, operation="nat", explicit=True, batch=False)
        if not access["allow"]:
            print(f"拒绝: {access['reason']}")
            raise SystemExit(2)
        rows = preview_rules(args.vmid, conf)
        if args.json:
            print(to_json(rows))
        else:
            table = Table(title=f"VM {args.vmid} NAT 规则预览", expand=True)
            for h in ["编号", "名称", "协议", "外网", "内网", "目标IP"]:
                table.add_column(h)
            for r in rows:
                table.add_row(str(r["idx"]), r["name"], r["proto"], r["ext"], r["int"], r["ip"])
            console.print(table)
        return

    if args.cmd == "backup_config":
        print(backup_config(args.config, args.out))
        return

    if args.cmd == "dyn_tc_check":
        events = dynamic_tc_check(conf)
        for e in events:
            print(e)
        return

    if args.cmd == "dyn_tc_status":
        rows = dynamic_tc_status(conf, args.vmid)
        if args.json:
            print(to_json(rows))
        else:
            table = Table(title="动态限速状态", expand=True)
            for h in ["VMID", "规则", "限速至", "冷却至", "最近RX(MiB)", "最近TX(MiB)"]:
                table.add_column(h)
            for r in rows:
                table.add_row(
                    str(r.get("vmid", "")),
                    str(r.get("rule", "")),
                    str(r.get("throttled_until", "")),
                    str(r.get("cooldown_until", "")),
                    str(r.get("last_rx_mib", "")),
                    str(r.get("last_tx_mib", "")),
                )
            console.print(table)
        return

    if args.cmd == "dyn_tc_release":
        ok = dynamic_tc_release(args.vmid, conf)
        if not ok:
            raise SystemExit(2)
        print(f"已解除动态限速: VM {args.vmid}")
        return

    if args.cmd == "dyn_engine":
        dyn = ensure_dyn_tc(conf)
        dyn["enabled"] = args.enabled == "1"
        save_config(conf, args.config)
        print(f"动态限速引擎: {'启用' if dyn['enabled'] else '禁用'}")
        return

    if args.cmd == "dyn_rule_list":
        dyn = ensure_dyn_tc(conf)
        rules = dyn.get("rules", [])
        if args.json:
            print(to_json(rules))
        else:
            table = Table(title="动态限速规则", expand=True)
            for h in ["编号", "名称", "范围", "窗口", "阈值(RX/TX MiB)", "限速(dn/up)", "限速时长", "冷却", "启用"]:
                table.add_column(h)
            for i, r in enumerate(rules):
                table.add_row(
                    str(i),
                    str(r.get("name", "")),
                    f"{r.get('vmid_min','-')}-{r.get('vmid_max','-')}",
                    f"{r.get('window_minutes','-')}m",
                    f"{r.get('rx_threshold_mib','-')}/{r.get('tx_threshold_mib','-')}",
                    f"{r.get('throttle_dn_mbit','-')}/{r.get('throttle_up_mbit','-')}",
                    f"{r.get('throttle_minutes','-')}m",
                    f"{r.get('cooldown_minutes','-')}m",
                    "Yes" if r.get("enabled", False) else "No",
                )
            console.print(table)
        return

    if args.cmd == "dyn_rule_add":
        dyn = ensure_dyn_tc(conf)
        dyn.setdefault("rules", []).append(
            {
                "name": args.name,
                "enabled": args.enabled == "1",
                "vmid_min": int(args.vmid_min),
                "vmid_max": int(args.vmid_max),
                "window_minutes": int(args.window),
                "rx_threshold_mib": float(args.rx),
                "tx_threshold_mib": float(args.tx),
                "throttle_minutes": int(args.throttle),
                "cooldown_minutes": int(args.cooldown),
                "throttle_dn_mbit": str(args.dn),
                "throttle_up_mbit": str(args.up),
            }
        )
        save_config(conf, args.config)
        print("动态限速规则已新增")
        return

    if args.cmd == "dyn_rule_edit":
        dyn = ensure_dyn_tc(conf)
        rules = dyn.setdefault("rules", [])
        idx = int(args.idx)
        if idx < 0 or idx >= len(rules):
            raise SystemExit(2)
        r = rules[idx]
        if args.name:
            r["name"] = args.name
        if args.vmid_min:
            r["vmid_min"] = int(args.vmid_min)
        if args.vmid_max:
            r["vmid_max"] = int(args.vmid_max)
        if args.window:
            r["window_minutes"] = int(args.window)
        if args.rx:
            r["rx_threshold_mib"] = float(args.rx)
        if args.tx:
            r["tx_threshold_mib"] = float(args.tx)
        if args.throttle:
            r["throttle_minutes"] = int(args.throttle)
        if args.cooldown:
            r["cooldown_minutes"] = int(args.cooldown)
        if args.dn:
            r["throttle_dn_mbit"] = str(args.dn)
        if args.up:
            r["throttle_up_mbit"] = str(args.up)
        if args.enabled in ["0", "1"]:
            r["enabled"] = args.enabled == "1"
        save_config(conf, args.config)
        print("动态限速规则已修改")
        return

    if args.cmd == "dyn_rule_del":
        dyn = ensure_dyn_tc(conf)
        rules = dyn.setdefault("rules", [])
        idx = int(args.idx)
        if idx < 0 or idx >= len(rules):
            raise SystemExit(2)
        rules.pop(idx)
        save_config(conf, args.config)
        print("动态限速规则已删除")
        return

    if args.cmd == "dyn_rule_toggle":
        dyn = ensure_dyn_tc(conf)
        rules = dyn.setdefault("rules", [])
        idx = int(args.idx)
        if idx < 0 or idx >= len(rules):
            raise SystemExit(2)
        rules[idx]["enabled"] = args.enabled == "1"
        save_config(conf, args.config)
        print(f"规则 {idx} 已{'启用' if rules[idx]['enabled'] else '禁用'}")
        return

    if args.cmd == "dyn_rule_preset":
        dyn = ensure_dyn_tc(conf)
        presets = {
            "home": {
                "name": "preset-home",
                "window_minutes": 15,
                "rx_threshold_mib": 2048,
                "tx_threshold_mib": 1024,
                "throttle_minutes": 30,
                "cooldown_minutes": 30,
                "throttle_dn_mbit": "60mbit",
                "throttle_up_mbit": "20mbit",
            },
            "idc": {
                "name": "preset-idc",
                "window_minutes": 5,
                "rx_threshold_mib": 4096,
                "tx_threshold_mib": 4096,
                "throttle_minutes": 15,
                "cooldown_minutes": 15,
                "throttle_dn_mbit": "200mbit",
                "throttle_up_mbit": "200mbit",
            },
            "night": {
                "name": "preset-night",
                "window_minutes": 20,
                "rx_threshold_mib": 1024,
                "tx_threshold_mib": 512,
                "throttle_minutes": 45,
                "cooldown_minutes": 20,
                "throttle_dn_mbit": "30mbit",
                "throttle_up_mbit": "10mbit",
            },
        }
        base = dict(presets[args.preset])
        base["enabled"] = args.enabled == "1"
        base["name"] = f"{base['name']}-{args.vmid_min}-{args.vmid_max}"
        base["vmid_min"] = int(args.vmid_min)
        base["vmid_max"] = int(args.vmid_max)
        dyn.setdefault("rules", []).append(base)
        save_config(conf, args.config)
        print(f"已添加预设规则: {base['name']}")
        return

    if args.cmd == "vnstat_report":
        print(vnstat_report(args.vmid, args.mode, args.limit, args.out, conf))
        return

    if args.cmd == "conn_stats":
        data = vm_connection_stats(args.vmid, conf)
        if args.json:
            print(to_json(data))
        else:
            table = Table(title=f"VM {args.vmid} 连接统计", expand=True)
            for h in ["VMID", "IP", "入站", "出站", "总计"]:
                table.add_column(h)
            table.add_row(str(data["vmid"]), str(data["ip"]), str(data["inbound"]), str(data["outbound"]), str(data["total"]))
            console.print(table)
        return

    if args.cmd == "monitor_overview":
        rows = export_api_payload(conf, "overview").get("data", {}).get("overview", [])

        if args.json:
            print(to_json(rows))
        else:
            table = Table(title="监控总览", expand=True)
            for h in ["VMID", "状态", "IP", "动态规则数", "当前限速(dn/up)"]:
                table.add_column(h)
            for r in rows:
                table.add_row(str(r["vmid"]), str(r["status"]), str(r["ip"]), str(r["dyn_rules"]), f"{r['limit_dn']}/{r['limit_up']}")
            console.print(table)
        return

    if args.cmd == "node_health":
        data = node_health(conf)
        if args.json:
            print(to_json(data))
        else:
            table = Table(title="节点健康", expand=True)
            for h in ["Node", "状态", "CPU%", "内存%", "磁盘%", "Uptime(s)", "LoadAvg"]:
                table.add_column(h)
            for n in data.get("nodes", []):
                mem_total = int(n.get("mem_total", 0) or 0)
                mem_used = int(n.get("mem_used", 0) or 0)
                root_total = int(n.get("root_total", 0) or 0)
                root_used = int(n.get("root_used", 0) or 0)
                mem_pct = (mem_used * 100.0 / mem_total) if mem_total > 0 else 0.0
                disk_pct = (root_used * 100.0 / root_total) if root_total > 0 else 0.0
                load = n.get("loadavg", [0, 0, 0])
                table.add_row(
                    str(n.get("node", "")),
                    str(n.get("status", "")),
                    f"{float(n.get('cpu', 0))*100:.1f}",
                    f"{mem_pct:.1f}",
                    f"{disk_pct:.1f}",
                    str(n.get("uptime", 0)),
                    f"{load[0]},{load[1]},{load[2]}" if isinstance(load, list) and len(load) >= 3 else "-",
                )
            console.print(table)
        return

    if args.cmd == "batch_vnstat_report":
        targets = parse_vms_str(args.input, conf, operation="general").split()
        created = []
        for vmid in targets:
            out = os.path.join(args.out_dir, f"vnstati_{vmid}_{args.mode}.png")
            try:
                os.makedirs(args.out_dir, exist_ok=True)
                vnstat_report(vmid, args.mode, args.limit, out, conf)
                created.append({"vmid": vmid, "out": out, "ok": True})
            except Exception as ex:
                created.append({"vmid": vmid, "out": out, "ok": False, "error": str(ex)})
        print(to_json(created))
        return

    if args.cmd == "batch_conn_stats":
        targets = parse_vms_str(args.input, conf, operation="general").split()
        rows = []
        for vmid in targets:
            try:
                rows.append(vm_connection_stats(vmid, conf))
            except Exception as ex:
                rows.append({"vmid": str(vmid), "error": str(ex)})
        if args.json:
            print(to_json(rows))
        else:
            table = Table(title="批量连接统计", expand=True)
            for h in ["VMID", "IP", "入站", "出站", "总计", "错误"]:
                table.add_column(h)
            for r in rows:
                table.add_row(
                    str(r.get("vmid", "")),
                    str(r.get("ip", "")),
                    str(r.get("inbound", "")),
                    str(r.get("outbound", "")),
                    str(r.get("total", "")),
                    str(r.get("error", "")),
                )
            console.print(table)
        return

    if args.cmd == "monitor_snapshot":
        print(monitor_snapshot(conf, args.out))
        return

    if args.cmd == "alert_check":
        rows = alert_check(conf)
        if args.json:
            print(to_json(rows))
        else:
            table = Table(title="告警列表", expand=True)
            for h in ["时间", "级别", "来源", "ID", "指标", "值", "阈值", "说明"]:
                table.add_column(h)
            for r in rows:
                table.add_row(
                    str(r.get("ts", "")),
                    str(r.get("severity", "")),
                    str(r.get("source", "")),
                    str(r.get("id", "")),
                    str(r.get("metric", "")),
                    str(r.get("value", "")),
                    str(r.get("threshold", "")),
                    str(r.get("message", "")),
                )
            console.print(table)
        return

    if args.cmd == "cleanup_auto":
        deleted = cleanup_auto(conf)
        if args.json:
            print(to_json(deleted))
        else:
            table = Table(title="自动清理结果", expand=True)
            table.add_column("已删除文件")
            if deleted:
                for p in deleted:
                    table.add_row(str(p))
            else:
                table.add_row("无")
            console.print(table)
        return

    if args.cmd == "api_export":
        payload = export_api_payload(conf, args.type, vmid=args.vmid, input_expr=args.input)
        if args.out:
            os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            print(args.out)
        else:
            print(to_json(payload))
        return

    if args.cmd == "ensure_hook_script":
        print(ensure_hook_script(conf))
        return

    if args.cmd == "hook":
        handle_hook_event(args.vmid, args.phase, conf)
        return
