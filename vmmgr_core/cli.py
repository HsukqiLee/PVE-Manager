# pyright: reportMissingImports=false
import argparse
import json

from rich.panel import Panel
from rich.table import Table

from .config import default_config, load_config, parse_days, save_config
from .constants import DEFAULT_CONFIG_FILE
from .ops import (
    apply_nat,
    apply_tc,
    backup_config,
    get_all_vms,
    get_current_limit,
    parse_vms_str,
    power_action,
    sync_all,
)
from .policy import vmid_access
from .rules import get_vm_conf, get_vm_ip, preview_rules, to_json, validate_config
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
        "命令路径可配置（pvesh/iptables/tc/qm/pct）",
        "行为参数可配置（默认 ssh/rdp 端口、postrouting cidr）",
    ]
    console.print(Panel("\n".join([f"- {x}" for x in items]), title="已支持功能", border_style="green"))


def handle_menus(cmd, conf):
    all_vms = get_all_vms(conf)

    if cmd == "menu":
        render_main_menu(conf, all_vms, get_current_limit, True)
        return True
    if cmd == "list":
        render_main_menu(conf, all_vms, get_current_limit, False)
        return True

    if cmd == "show_menu_hook":

        def ext(vm, c):
            o, n = get_os_nickname(vm.get("name", "-"), c.get("nickname"))
            return [str(vm["vmid"]), f"{o} ({n})", "[green]Yes[/]" if has_hook(str(vm["vmid"])) else "[dim]No[/]"]

        render_submenu("Hook 脚本管理", ["ID", "特征", "状态"], ext, ["[bold cyan]1.[/] 绑定", "[bold red]2.[/] 解绑", "[bold white]0.[/] 返回"], conf, all_vms)
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

        render_submenu("动态流控管理", ["ID", "特征", "当前", "专属列表"], ext, ["[bold cyan]1.[/] 全局", "[bold yellow]2.[/] 专属", "[bold red]3.[/] 清实例", "[bold magenta]4.[/] 清全局", "[bold white]0.[/] 返回"], conf, all_vms)
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

        vm = get_vm_conf(conf, args.vmid)
        if args.act == "add":
            vm.setdefault("custom_ports", []).append({"ext": args.ext, "int": args.int_port, "proto": (args.proto or "tcp").lower()})
        elif args.act == "edit":
            p = vm.setdefault("custom_ports", [])
            i = int(args.idx)
            if 0 <= i < len(p):
                if args.ext and args.ext != "-":
                    p[i]["ext"] = args.ext
                if args.int_port and args.int_port != "-":
                    p[i]["int"] = args.int_port
                if args.proto and args.proto != "-":
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
