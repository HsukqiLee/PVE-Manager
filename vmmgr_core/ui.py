# pyright: reportMissingImports=false
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .rules import expand_port_rules, get_profile_status_for_vm, get_vm_conf, get_vm_ip, get_vm_all_ips
from .utils import get_term_width

console = Console()




def get_os_nickname(vm_name, conf_nick):
    if conf_nick:
        return vm_name.split("-", 1)[0] if "-" in vm_name else vm_name, conf_nick
    if "-" in vm_name:
        p = vm_name.split("-", 1)
        return p[0], p[1]
    return vm_name, "未设置"


def has_hook(vmid):
    for p in [f"/etc/pve/lxc/{vmid}.conf", f"/etc/pve/qemu-server/{vmid}.conf"]:
        try:
            text = open(p, "r", encoding="utf-8", errors="ignore").read()
            if "hook.py" in text or "nat_hook.py" in text:
                return True
        except Exception:
            pass
    return False


def render_submenu(title, columns, extractor, opts, conf, all_vms):
    table = Table(title=f"[bold white]{title}[/bold white]", box=box.ROUNDED, border_style="cyan", expand=True)
    compact = get_term_width() < 100
    if compact and len(columns) > 3:
        cols_to_show = [0, 1, len(columns) - 1]
        for c in [columns[i] for i in cols_to_show]:
            table.add_column(c, justify="center")
    else:
        cols_to_show = list(range(len(columns)))
        for c in columns:
            table.add_column(c, justify="center")

    for vm in sorted(all_vms, key=lambda x: x["vmid"]):
        row = extractor(vm, get_vm_conf(conf, str(vm["vmid"])))
        table.add_row(*[row[i] for i in cols_to_show])

    console.print(table)
    if compact:
        console.print(Panel(Columns([Panel(i, box=box.SIMPLE) for i in opts]), border_style="cyan"))
    else:
        console.print(Panel(Columns([Panel(i, box=box.SIMPLE, expand=True) for i in opts], equal=True), border_style="cyan"))


def render_main_menu(conf, all_vms, show_panel=True):
    compact = get_term_width() < 100
    table = Table(
        title="[bold white]虚拟机实时状态汇总[/bold white]",
        box=box.ROUNDED,
        border_style="blue",
        expand=True,
        show_lines=True,
    )

    if compact:
        for h in ["ID", "实例", "IP/端口 (B/M)", "状态"]:
            table.add_column(h, justify="center")
    else:
        for h in ["ID", "系统 / 昵称", "IP (B/M)", "类型 (Hook)", "额外转发 (端口数)", "状态"]:
            table.add_column(h, justify="center")

    for vm in sorted(all_vms, key=lambda x: x["vmid"]):
        vmid = str(vm["vmid"])
        vm_c = get_vm_conf(conf, vmid)
        os_n, nick = get_os_nickname(vm.get("name", "-"), vm_c.get("nickname"))

        rules_cnt = len(expand_port_rules(vmid, conf, vm_c))
        extra_pf = get_profile_status_for_vm(vmid, vm_c, conf)

        # Multi-IP Support
        biz_ip = get_vm_ip(vmid, conf, scope="biz")
        mgmt_ip = get_vm_ip(vmid, conf, scope="mgmt")

        # Optional Audit Info
        audit_res = vm.get("_audit")
        biz_display = biz_ip
        mgmt_display = mgmt_ip

        if audit_res and audit_res["status"] == "mismatch":
            actuals = audit_res.get("actual_ips", [])
            for mis in audit_res.get("mismatches", []):
                if mis["scope"] == "biz":
                    biz_display = f"[bold red]{biz_ip}[/]\n[dim]Actual: {','.join(actuals) or 'None'}[/]"
                if mis["scope"] == "mgmt":
                    mgmt_display = f"[bold red]{mgmt_ip}[/]\n[dim]Actual: {','.join(actuals) or 'None'}[/]"
        elif audit_res and audit_res["status"] == "agent-error":
            biz_display = f"{biz_ip} [dim](Agent?)[/]"
        if compact:
            table.add_row(
                vmid,
                f"{os_n}\n[dim]{nick}[/dim]",
                f"B:{biz_display}\nM:{mgmt_display}",
                "[bold green]Yes[/]" if vm.get("status") == "running" else "[dim]No[/]",
            )
        else:
            table.add_row(
                vmid,
                f"{os_n}\n[dim]{nick}[/dim]",
                f"[bold cyan]B:[/] {biz_display}\n[bold magenta]M:[/] {mgmt_display}",
                f"{vm.get('type', '-').upper()}\n[dim]({'Hook' if has_hook(vmid) else 'No'})[/dim]",
                f"{extra_pf}\n[dim]Ports: {rules_cnt}[/dim]",
                "[bold green]Yes[/]" if vm.get("status") == "running" else "[dim]No[/]",
            )

    console.print(table)
    if show_panel:
        ps = [
            "[bold cyan]1.[/] 状态总览",
            "[bold cyan]2.[/] Hook 管理",
            "[bold cyan]3.[/] 额外转发",
            "[bold cyan]4.[/] 端口转发",
            "[bold cyan]5.[/] 昵称设置",
            "[bold cyan]6.[/] 电源控制",
            "[bold green]7.[/] 规则刷新",
            "[bold yellow]8.[/] 网络重置",
            "[bold magenta]9.[/] 配置校验",
            "[bold magenta]10.[/] 规则预览",
            "[bold white]11.[/] 配置备份",
            "[bold white]12.[/] 系统信息",
            "[bold red]0.[/] 退出系统",
        ]
        if compact:
            console.print(Panel(Columns([Panel(i, box=box.SIMPLE) for i in ps]), border_style="blue"))
        else:
            console.print(Panel(Columns([Panel(i, box=box.SIMPLE, expand=True) for i in ps], equal=True), border_style="blue"))
