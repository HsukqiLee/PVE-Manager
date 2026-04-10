import datetime
import fcntl
import os
import shutil

from .constants import LOCK_FILE
from .policy import vmid_access, vmid_allowed
from .rules import expand_port_rules, get_vm_conf, get_vm_ip
from .utils import audit, run_cmd


def cfg_cmd(conf, name, default):
    return str(conf.get("settings", {}).get("commands", {}).get(name, default))


def get_all_vms(conf):
    pvesh = cfg_cmd(conf, "pvesh", "pvesh")
    raw = run_cmd(f"{pvesh} get /cluster/resources --type vm --output-format json").stdout
    try:
        import json

        items = json.loads(raw or "[]")
    except Exception:
        items = []
    return [v for v in items if v.get("template") == 0]


def get_net_device(vmid):
    for dev in [f"tap{vmid}i0", f"veth{vmid}i0"]:
        if os.path.exists(f"/sys/class/net/{dev}"):
            return dev
    return None


def parse_vms_str(input_str, conf, operation="general"):
    all_vms = {int(v["vmid"]): v for v in get_all_vms(conf)}
    result = set()

    for token in (input_str or "").split(","):
        token = token.strip().lower()
        if not token:
            continue

        if token == "all":
            for vmid in sorted(all_vms.keys()):
                if vmid_allowed(vmid, conf, operation=operation, explicit=False, batch=True):
                    result.add(vmid)
            continue

        if "-" in token:
            try:
                s, e = map(int, token.split("-", 1))
                for vmid in range(s, e + 1):
                    if vmid in all_vms and vmid_allowed(vmid, conf, operation=operation, explicit=False, batch=True):
                        result.add(vmid)
            except Exception:
                pass
            continue

        if token.isdigit():
            vmid = int(token)
            if vmid in all_vms and vmid_allowed(vmid, conf, operation=operation, explicit=True, batch=False):
                result.add(vmid)

    return " ".join(map(str, sorted(result)))


def apply_nat(vmid, action, conf, explicit=True, batch=False):
    vmid_str = str(vmid)
    access = vmid_access(vmid_str, conf, operation="nat", explicit=explicit, batch=batch)
    if not access["allow"]:
        return access["reason"]

    vm_conf = get_vm_conf(conf, vmid_str)
    target_ip = get_vm_ip(vmid_str, conf)
    if target_ip == "None":
        return "no-ip"

    iptables = cfg_cmd(conf, "iptables", "iptables")
    iptables_save = cfg_cmd(conf, "iptables_save", "iptables-save")

    tag = f"PVENAT-{vmid_str}"
    with open(LOCK_FILE, "w", encoding="utf-8") as lockfile:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX)
            run_cmd(f"{iptables_save} -t nat | grep -F '{tag}' | sed 's/^-A/{iptables} -t nat -D/' | bash")
            if action == "del":
                return "deleted"

            try:
                expanded_rules = expand_port_rules(vmid_str, conf, vm_conf)
            except ValueError:
                return "conflict-error"

            for _name, ext_p, int_p, proto in expanded_rules:
                run_cmd(
                    f"{iptables} -t nat -A PREROUTING "
                    f"-p {proto} --dport {ext_p} "
                    f"-m comment --comment \"{tag}\" "
                    f"-j DNAT --to-destination {target_ip}:{int_p}"
                )
        finally:
            fcntl.flock(lockfile, fcntl.LOCK_UN)
    return "ok"


def get_current_limit(vmid, vm_conf, conf):
    now = datetime.datetime.now()
    curr_hour, curr_day = now.hour, now.isoweekday()
    limits = vm_conf.get("limits")
    if limits is None:
        limits = conf.get("global_limits", [])
    for rule in limits:
        days = rule.get("days", list(range(1, 8)))
        if curr_day in days and int(rule["s"]) <= curr_hour < int(rule["e"]):
            return rule["dn"], rule["up"]
    return "-", "-"


def apply_tc(vmid, action, conf, explicit=True, batch=False):
    access = vmid_access(vmid, conf, operation="tc", explicit=explicit, batch=batch)
    if not access["allow"]:
        return access["reason"]

    cif = get_net_device(vmid)
    if not cif:
        return "no-dev"

    tc = cfg_cmd(conf, "tc", "tc")

    run_cmd(f"{tc} qdisc del dev {cif} root 2>/dev/null")
    run_cmd(f"{tc} qdisc del dev {cif} ingress 2>/dev/null")
    if action == "del":
        return "deleted"

    vm_conf = get_vm_conf(conf, str(vmid))
    dr, ur = get_current_limit(str(vmid), vm_conf, conf)
    if dr not in ["-", "0mbit", "unlimited"]:
        run_cmd(f"{tc} qdisc add dev {cif} root handle 1: htb default 10")
        run_cmd(f"{tc} class add dev {cif} parent 1: classid 1:1 htb rate 10000mbit")
        run_cmd(f"{tc} class add dev {cif} parent 1: classid 1:10 htb rate {dr} burst 50mb")
    if ur not in ["-", "0mbit", "unlimited"]:
        run_cmd(f"{tc} qdisc add dev {cif} handle ffff: ingress")
        run_cmd(
            f"{tc} filter add dev {cif} parent ffff: protocol ip prio 50 u32 "
            f"match ip dst 0.0.0.0/0 police rate {ur} burst 5mb drop"
        )
    return "ok"


def sync_all(sync_type, full_reset, conf):
    iface_ext = conf.get("settings", {}).get("interfaces", {}).get("ext", "vmbr0")
    cidr = conf.get("settings", {}).get("behavior", {}).get("postrouting_cidr", "10.10.0.0/16")
    iptables = cfg_cmd(conf, "iptables", "iptables")
    iptables_save = cfg_cmd(conf, "iptables_save", "iptables-save")

    if full_reset:
        run_cmd(
            f"{iptables} -t nat -C POSTROUTING -s {cidr} -o {iface_ext} -j MASQUERADE "
            f"|| {iptables} -t nat -A POSTROUTING -s {cidr} -o {iface_ext} -j MASQUERADE"
        )
        with open(LOCK_FILE, "w", encoding="utf-8") as lockfile:
            fcntl.flock(lockfile, fcntl.LOCK_EX)
            run_cmd(f"{iptables_save} -t nat | grep 'PVENAT-' | sed 's/^-A/{iptables} -t nat -D/' | bash")
            fcntl.flock(lockfile, fcntl.LOCK_UN)
        audit("Network full reset performed.")

    for vm in get_all_vms(conf):
        if vm.get("status") != "running":
            continue
        vmid = vm["vmid"]
        if sync_type in ["nat", "all"]:
            apply_nat(vmid, "add", conf, explicit=False, batch=True)
        if sync_type in ["tc", "all"]:
            apply_tc(vmid, "add", conf, explicit=False, batch=True)


def power_action(vmid, act, conf):
    access = vmid_access(vmid, conf, operation="power", explicit=True, batch=False)
    if not access["allow"]:
        return False

    vms = {str(v["vmid"]): v["type"] for v in get_all_vms(conf)}
    if str(vmid) not in vms:
        return False

    qm = cfg_cmd(conf, "qm", "qm")
    pct = cfg_cmd(conf, "pct", "pct")
    run_cmd(f"{pct if vms[str(vmid)] == 'lxc' else qm} {act} {vmid}")
    audit(f"Power action {act} on VM {vmid}")
    return True


def backup_config(config_file, output_file=""):
    if not os.path.exists(config_file):
        raise FileNotFoundError(config_file)
    if not output_file:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"{config_file}.bak.{ts}"
    shutil.copyfile(config_file, output_file)
    return output_file
