# pyright: reportMissingImports=false
import argparse
import json
import os

from rich.panel import Panel
from rich.table import Table

from .config import default_config, load_config, parse_days, save_config
from .constants import DEFAULT_CONFIG_FILE
from .ops import (
    apply_nat,
    audit_vm_network,
    ensure_hook_script,
    get_all_vms,
    handle_hook_event,
    power_action,
    sync_all,
    parse_vms_str,
    backup_config,
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
        "模板范围 VM 仅允许 hook，不允许端口转发",
        "批量时自动忽略 ignore/outside/template；单点指定可按策略执行",
        "可命名额外转发 profile（按 VM 启停与范围覆写）",
        "端口冲突策略: priority-skip / priority-remap / strict-error",
        "validate 配置校验 + 冲突检测",
        "preview_rules 规则预览",
        "backup_config 配置备份",
        "多 IP 作用域支持 (biz/mgmt)",
        "实时 Guest Agent 网络审计",
        "策略路由自动注入 (OPNsense 对称路由优化)",
        "命令路径可配置（pvesh/iptables/qm/pct）",
        "行为参数可配置（默认 ssh/rdp 端口、postrouting cidr）",
    ]
    console.print(Panel("\n".join([f"- {x}" for x in items]), title="已支持功能", border_style="green"))




def handle_menus(cmd, conf, audit_mode=False):
    if cmd == "list":
        all_vms = get_all_vms(conf)
        render_main_menu(conf, all_vms, False)
        return True

    if cmd != "menu":
        return False

    while True:
        all_vms = get_all_vms(conf)
        if audit_mode:
            for vm in all_vms:
                if vm.get("status") == "running":
                    vm["_audit"] = audit_vm_network(vm["vmid"], conf)

        render_main_menu(conf, all_vms, True)
        choice = input("\n请选择功能 (0-12): ").strip()

        if choice == "0":
            break
        elif choice == "1":
            audit_mode = not audit_mode
            console.print(f"实时状态审计: {'[bold green]已开启[/]' if audit_mode else '[bold red]已关闭[/]'}")
        elif choice == "2":
            handle_hook_interactive(conf)
        elif choice == "3":
            handle_xpf_interactive(conf)
        elif choice == "4":
            handle_nat_interactive(conf)
        elif choice == "5":
            handle_nickname_interactive(conf)
        elif choice == "6":
            handle_power_interactive(conf)
        elif choice == "7":
            sync_all("all", False, conf)
            input("\n刷新完成，按回车键继续...")
        elif choice == "8":
            sync_all("all", True, conf)
            input("\n重置完成，按回车键继续...")
        elif choice == "9":
            cmd_validate(conf)
            input("\n按回车键继续...")
        elif choice == "10":
            vmid = input("请输入 VMID: ").strip()
            if vmid:
                handle_preview_interactive(conf, vmid)
            input("\n按回车键继续...")
        elif choice == "11":
            out = input("请输入备份路径 (留空则默认): ").strip()
            path = backup_config(DEFAULT_CONFIG_FILE, out)
            console.print(f"[bold green]备份成功:[/] {path}")
            input("\n按回车键继续...")
        elif choice == "12":
            show_features()
            show_config_schema()
            input("\n按回车键继续...")

    return True


def handle_hook_interactive(conf):
    while True:
        hook_vms = get_all_vms(conf, include_templates=True)

        def ext(vm, c):
            o, n = get_os_nickname(vm.get("name", "-"), c.get("nickname"))
            return [str(vm["vmid"]), f"{o} ({n})", "[green]Yes[/]" if has_hook(str(vm["vmid"])) else "[dim]No[/]"]

        render_submenu("Hook 脚本管理", ["ID", "特征", "状态"], ext, ["[bold cyan]1.[/] 绑定", "[bold red]2.[/] 解绑", "[bold white]0.[/] 返回"], conf, hook_vms)
        choice = input("\n请选择 (0-2): ").strip()
        if choice == "0":
            break
        vmid = input("请输入 VMID (支持批量, 如 100-105, 107): ").strip()
        if not vmid:
            continue
        targets = parse_vms_str(vmid, conf, operation="hook").split()
        if choice == "1":
            print(ensure_hook_script(conf))
            for t in targets:
                handle_hook_event(t, "post-start", conf)
        elif choice == "2":
            # Unbind is basically manual in PVE but we can audit or provide instructions
            console.print("[yellow]请手动从 PVE 配置文件中移除 hookscript 行。[/]")
        input("\n操作完成，按回车键继续...")


def handle_xpf_interactive(conf):
    while True:
        all_vms = get_all_vms(conf)

        def ext(vm, c):
            vmid = str(vm["vmid"])
            o, n = get_os_nickname(vm.get("name", "-"), c.get("nickname"))
            from .rules import get_profile_status_for_vm
            return [vmid, f"{o} ({n})", get_profile_status_for_vm(vmid, c, conf)]

        render_submenu("额外端口转发", ["ID", "特征", "Profiles"], ext, ["[bold cyan]1.[/] 启用", "[bold red]2.[/] 禁用", "[bold yellow]3.[/] 改范围", "[bold white]0.[/] 返回"], conf, all_vms)
        choice = input("\n请选择 (0-3): ").strip()
        if choice == "0":
            break
        vmid = input("请输入 VMID: ").strip()
        profile = input("请输入 Profile ID: ").strip()
        if choice == "1":
            run_cmd_args(["xpf_act", "--act", "enable", "--vmid", vmid, "--profile", profile], conf)
        elif choice == "2":
            run_cmd_args(["xpf_act", "--act", "disable", "--vmid", vmid, "--profile", profile], conf)
        elif choice == "3":
            rng = input("请输入新的范围 (如 31000-31019): ").strip()
            run_cmd_args(["xpf_act", "--act", "modify", "--vmid", vmid, "--profile", profile, "--range", rng], conf)
        input("\n操作完成，按回车键继续...")


def handle_nat_interactive(conf):
    while True:
        all_vms = get_all_vms(conf)

        def ext(vm, c):
            v = str(vm["vmid"])
            o, n = get_os_nickname(vm.get("name", "-"), c.get("nickname"))
            biz = get_vm_ip(v, conf, scope="biz")
            mgmt = get_vm_ip(v, conf, scope="mgmt")
            return [v, f"{o} ({n})", f"B:{biz}\nM:{mgmt}", str(len(c.get("custom_ports", [])))]

        render_submenu("端口转发管理", ["ID", "特征", "内网IP (B/M)", "自定义数"], ext, ["[bold cyan]1.[/] 设置 IP", "[bold yellow]2.[/] 管理自定义端口", "[bold white]0.[/] 返回"], conf, all_vms)
        choice = input("\n请选择 (0-2): ").strip()
        if choice == "0":
            break
        vmid = input("请输入 VMID: ").strip()
        if choice == "1":
            biz = input("请输入业务 IP (biz): ").strip()
            mgmt = input("请输入管理 IP (mgmt): ").strip()
            run_cmd_args(["set_ip", "--vmid", vmid, "--biz", biz, "--mgmt", mgmt], conf)
        elif choice == "2":
            handle_custom_ports_interactive(conf, vmid)
        input("\n操作完成，按回车键继续...")


def handle_custom_ports_interactive(conf, vmid):
    while True:
        vm_c = get_vm_conf(conf, vmid)
        table = Table(title=f"VM {vmid} 自定义端口转发", expand=True)
        for h in ["编号", "协议", "外网", "内网"]:
            table.add_column(h)
        ports = vm_c.get("custom_ports", [])
        for i, p in enumerate(ports):
            table.add_row(str(i), p["proto"], p["ext"], p["int"])
        console.print(table)

        console.print("\n[bold cyan]1.[/] 新增 [bold yellow]2.[/] 修改 [bold red]3.[/] 删除 [bold white]0.[/] 返回")
        choice = input("\n请选择 (0-3): ").strip()
        if choice == "0":
            break
        if choice == "1":
            ext = input("外网端口 (如 80 或 80:90): ").strip()
            intp = input("内网端口: ").strip()
            proto = input("协议 (tcp/udp): ").strip() or "tcp"
            run_cmd_args(["manage_port", "--act", "add", "--vmid", vmid, "--ext", ext, "--int_port", intp, "--proto", proto], conf)
        elif choice == "2":
            idx = input("请输入编号: ").strip()
            ext = input("外网端口 (保持不变按回车): ").strip() or "-"
            intp = input("内网端口 (保持不变按回车): ").strip() or "-"
            proto = input("协议 (保持不变按回车): ").strip() or "-"
            run_cmd_args(["manage_port", "--act", "edit", "--vmid", vmid, "--idx", idx, "--ext", ext, "--int_port", intp, "--proto", proto], conf)
        elif choice == "3":
            idx = input("请输入编号: ").strip()
            run_cmd_args(["manage_port", "--act", "del", "--vmid", vmid, "--idx", idx], conf)


def handle_nickname_interactive(conf):
    while True:
        all_vms = get_all_vms(conf)

        def ext(vm, c):
            r = vm.get("name", "-")
            o, n = get_os_nickname(r, c.get("nickname"))
            return [str(vm["vmid"]), r, o, n, "[bold green]已配[/]" if c.get("nickname") else "[dim]默认[/]"]

        render_submenu("实例昵称设置", ["ID", "原始名", "OS", "昵称", "状态"], ext, ["[bold cyan]1.[/] 修改", "[bold red]2.[/] 清除", "[bold white]0.[/] 返回"], conf, all_vms)
        choice = input("\n请选择 (0-2): ").strip()
        if choice == "0":
            break
        vmid = input("请输入 VMID: ").strip()
        if choice == "1":
            nick = input("请输入新昵称: ").strip()
            run_cmd_args(["manage_nick", "--act", "set", "--vmid", vmid, "--nick", nick], conf)
        elif choice == "2":
            run_cmd_args(["manage_nick", "--act", "clear", "--vmid", vmid], conf)
        input("\n操作完成，按回车键继续...")


def handle_power_interactive(conf):
    while True:
        all_vms = get_all_vms(conf)

        def ext(vm, c):
            o, n = get_os_nickname(vm.get("name", "-"), c.get("nickname"))
            return [str(vm["vmid"]), f"{o} ({n})", "[bold green]Running[/]" if vm.get("status") == "running" else "[bold red]Stopped[/]"]

        render_submenu("电源控制", ["ID", "特征", "状态"], ext, ["[bold green]1.[/] 启动", "[bold red]2.[/] 关闭", "[bold yellow]3.[/] 重启", "[bold white]0.[/] 返回"], conf, all_vms)
        choice = input("\n请选择 (0-3): ").strip()
        if choice == "0":
            break
        vmid = input("请输入 VMID: ").strip()
        if choice == "1":
            power_action(vmid, "start", conf)
        elif choice == "2":
            power_action(vmid, "stop", conf)
        elif choice == "3":
            power_action(vmid, "reboot", conf)
        input("\n操作完成，按回车键继续...")


def handle_preview_interactive(conf, vmid):
    rows = preview_rules(vmid, conf)
    table = Table(title=f"VM {vmid} NAT 规则预览", expand=True)
    for h in ["编号", "名称", "协议", "外网", "内网", "目标IP"]:
        table.add_column(h)
    for r in rows:
        table.add_row(str(r["idx"]), r["name"], r["proto"], r["ext"], r["int"], r["ip"])
    console.print(table)


def run_cmd_args(args_list, conf):
    # This is a helper to simulate command line execution for internal interactive calls
    parser = build_parser()
    args = parser.parse_args(args_list)
    # We need to manually dispatch because run() is the entry point
    # but we are already inside a running session.
    # For now, we can just call the logic directly if we restructure run() or just use simple logic here.
    # Better: just call the specific logic here.
    if args_list[0] == "set_ip":
        vm = get_vm_conf(conf, args.vmid)
        ips = vm.setdefault("ips", {})
        if args.biz: ips["biz"] = args.biz
        if args.mgmt: ips["mgmt"] = args.mgmt
        save_config(conf, DEFAULT_CONFIG_FILE)
    elif args_list[0] == "manage_port":
        vm = get_vm_conf(conf, args.vmid)
        if args.act == "add":
            vm.setdefault("custom_ports", []).append({"ext": args.ext, "int": args.int_port, "proto": args.proto})
        elif args.act == "edit":
            p = vm.setdefault("custom_ports", [])
            i = int(args.idx)
            if 0 <= i < len(p):
                if args.ext != "-": p[i]["ext"] = args.ext
                if args.int_port != "-": p[i]["int"] = args.int_port
                if args.proto != "-": p[i]["proto"] = args.proto
        elif args.act == "del":
            try: vm.setdefault("custom_ports", []).pop(int(args.idx))
            except: pass
        save_config(conf, DEFAULT_CONFIG_FILE)
    elif args_list[0] == "manage_nick":
        vm = get_vm_conf(conf, args.vmid)
        if args.act == "set": vm["nickname"] = args.nick
        else: vm.pop("nickname", None)
        save_config(conf, DEFAULT_CONFIG_FILE)
    elif args_list[0] == "xpf_act":
        vm = get_vm_conf(conf, args.vmid)
        vm.setdefault("profile_overrides", {})
        vm["profile_overrides"].setdefault(args.profile, {})
        if args.act in ["enable", "disable"]:
            vm["profile_overrides"][args.profile]["enabled"] = args.act == "enable"
        elif args.act == "modify":
            vm["profile_overrides"][args.profile]["range_override"] = args.range
        save_config(conf, DEFAULT_CONFIG_FILE)
        apply_nat(args.vmid, "add", conf, explicit=True, batch=False)


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
        "show_menu_power",
        "show_config_schema",
        "show_features",
        "audit_all",
    ]:
        subparsers.add_parser(c)

    p = subparsers.add_parser("p_list")
    p.add_argument("--vmid", required=True)

    p = subparsers.add_parser("get_ip")
    p.add_argument("--vmid", required=True)
    p.add_argument("--scope", default="biz")

    p = subparsers.add_parser("set_ip")
    p.add_argument("--vmid", required=True)
    p.add_argument("--biz", default="")
    p.add_argument("--mgmt", default="")

    p = subparsers.add_parser("apply_nat")
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

    p = subparsers.add_parser("ensure_hook_script")

    p = subparsers.add_parser("hook")
    p.add_argument("--vmid", required=True)
    p.add_argument("--phase", required=True)

    return parser


def run():
    parser = build_parser()
    args = parser.parse_args()
    if not args.cmd:
        args.cmd = "menu"

    conf = load_config(args.config)

    if handle_menus(args.cmd, conf, audit_mode=(args.cmd == "audit_all")):
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
        print(get_vm_ip(args.vmid, conf, scope=args.scope))
        return

    if args.cmd == "set_ip":
        vm = get_vm_conf(conf, args.vmid)
        ips = vm.setdefault("ips", {})
        if args.biz:
            ips["biz"] = args.biz
        if args.mgmt:
            ips["mgmt"] = args.mgmt
        save_config(conf, args.config)
        print(f"VM {args.vmid} IP 已更新")
        return

    if args.cmd == "apply_nat":
        status = apply_nat(args.vmid, args.act, conf, explicit=True, batch=False)
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

    if args.cmd == "ensure_hook_script":
        print(ensure_hook_script(conf))
        return

    if args.cmd == "hook":
        handle_hook_event(args.vmid, args.phase, conf)
        return
