# pyright: reportMissingImports=false
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .rules import expand_port_rules, get_profile_status_for_vm, get_vm_conf, get_vm_ip
from .utils import get_term_width

console = Console()


def format_bw(bw, direction=""):
    if not bw or bw in ["-", "unlimited"]:
        return f"{direction} 无".strip()
    v = str(bw).replace("mbit", "")
    if v == "0":
        return "无"
    try:
        vi = int(v)
        val = f"{vi // 1000}G" if vi >= 1000 and vi % 1000 == 0 else f"{vi}m"
    except Exception:
        val = bw
    return f"{direction} {val}".strip()


def format_limits(limits):
    if not limits:
        return "[dim]未设置[/]"
    res = []
    d_m = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "日"}
    for i, r in enumerate(limits):
        days = r.get("days", list(range(1, 8)))
        d_s = "全周" if len(days) == 7 else "周" + ",".join([d_m[d] for d in days])
        res.append(f"\\[{i}] {d_s} {r['s']}-{r['e']}点: ↓{format_bw(r['dn'])} ↑{format_bw(r['up'])}")
    return "\n".join(res)


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
            if "nat_hook.py" in open(p, "r", encoding="utf-8", errors="ignore").read():
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


def render_main_menu(conf, all_vms, current_limit_func, show_panel=True):
    compact = get_term_width() < 100
    table = Table(
        title="[bold white]虚拟机实时状态汇总[/bold white]",
        box=box.ROUNDED,
        border_style="blue",
        expand=True,
        show_lines=True,
    )

    if compact:
        for h in ["ID", "实例", "IP/端口", "流控(↓/↑)", "状态"]:
            table.add_column(h, justify="center")
    else:
        for h in ["ID", "系统 / 昵称", "IP (规则数)", "类型 (Hook)", "额外转发", "当前实时流控", "状态"]:
            table.add_column(h, justify="center")

    for vm in sorted(all_vms, key=lambda x: x["vmid"]):
        vmid = str(vm["vmid"])
        vm_c = get_vm_conf(conf, vmid)
        os_n, nick = get_os_nickname(vm.get("name", "-"), vm_c.get("nickname"))

        rules_cnt = len(expand_port_rules(vmid, conf, vm_c))
        extra_pf = get_profile_status_for_vm(vmid, vm_c, conf)
        dn, up = current_limit_func(vmid, vm_c, conf)

        if compact:
            table.add_row(
                vmid,
                f"{os_n}\n[dim]{nick}[/dim]",
                f"{get_vm_ip(vmid, conf)}\n[dim]({rules_cnt})[/dim]",
                f"{format_bw(dn,'↓')}\n{format_bw(up,'↑')}",
                "[bold green]Yes[/]" if vm.get("status") == "running" else "[dim]No[/]",
            )
        else:
            table.add_row(
                vmid,
                f"{os_n}\n[dim]{nick}[/dim]",
                f"{get_vm_ip(vmid, conf)}\n[dim]({rules_cnt})[/dim]",
                f"{vm.get('type', '-').upper()}\n[dim]({'Hook' if has_hook(vmid) else 'No'})[/dim]",
                extra_pf,
                f"{format_bw(dn,'↓')}\n{format_bw(up,'↑')}",
                "[bold green]Yes[/]" if vm.get("status") == "running" else "[dim]No[/]",
            )

    console.print(table)
    if show_panel:
        ps = [
            "[bold cyan]1.[/] 状态总览",
            "[bold cyan]2.[/] Hook 管理",
            "[bold cyan]3.[/] 额外转发",
            "[bold cyan]4.[/] 端口转发",
            "[bold cyan]5.[/] 动态限速",
            "[bold cyan]6.[/] 昵称设置",
            "[bold cyan]7.[/] 电源控制",
            "[bold green]8.[/] 规则刷新",
            "[bold yellow]9.[/] 网络重置",
            "[bold magenta]10.[/] 配置校验",
            "[bold magenta]11.[/] 规则预览",
            "[bold red]0.[/] 退出系统",
        ]
        if compact:
            console.print(Panel(Columns([Panel(i, box=box.SIMPLE) for i in ps]), border_style="blue"))
        else:
            console.print(Panel(Columns([Panel(i, box=box.SIMPLE, expand=True) for i in ps], equal=True), border_style="blue"))
