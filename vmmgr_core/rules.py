import json
import os
import re

from .policy import vmid_allowed


def get_vm_conf(conf, vmid):
    return conf.setdefault("vms", {}).setdefault(str(vmid), {})


def build_context(vmid, groups=None, default_ssh_port="22", profile_start="0", profile_end="0"):
    v = int(vmid)
    groups = groups or []
    context = {
        "id": str(v),
        "id_div_10": str(v // 10),
        "id_mod_10": str(v % 10),
        "id_hundreds": str(v // 100),
        "id_tens": str((v // 10) % 10),
        "id_ones": str(v % 10),
        "base_port": str(v * 100),
        "base_port_plus1": str(v * 100 + 1),
        "base_port_plus99": str(v * 100 + 99),
        "default_ssh_port": str(default_ssh_port),
        "profile_start": str(profile_start),
        "profile_end": str(profile_end),
        "profile_start_plus1": str(int(profile_start) + 1),
    }
    for i, g in enumerate(groups, start=1):
        context[f"g{i}"] = g
    return context


def render_template(text, context):
    if text is None:
        return ""

    def repl(match):
        key = match.group(1)
        return context.get(key, "")

    return re.sub(r"\{([a-zA-Z0-9_]+)\}", repl, str(text))


def parse_range_expr(expr):
    s = str(expr).strip()
    if ":" in s:
        a, b = s.split(":", 1)
        return int(a), int(b)
    if "-" in s:
        a, b = s.split("-", 1)
        return int(a), int(b)
    n = int(s)
    return n, n


def expand_ports(expr):
    a, b = parse_range_expr(expr)
    if b < a:
        a, b = b, a
    return set(range(a, b + 1))


def validate_port_expr(expr, allow_template=False):
    s = str(expr).strip()
    if not s:
        return False
    if allow_template and "{" in s and "}" in s:
        return True
    return bool(re.match(r"^\d+([:-]\d+)?$", s))


def apply_ip_rule(rule, vmid):
    if not rule.get("enabled", True):
        return None

    if "map" in rule and isinstance(rule["map"], dict):
        mapped = rule["map"].get(str(vmid))
        if mapped:
            return mapped

    pattern = rule.get("pattern")
    template = rule.get("template")
    if pattern and template:
        m = re.match(pattern, str(vmid))
        if m:
            ctx = build_context(vmid, list(m.groups()))
            return render_template(template, ctx)

    return None


def get_vm_ip(vmid, conf):
    if not vmid_allowed(vmid, conf, operation="hook", explicit=True, batch=False):
        return "None"

    vm_conf = get_vm_conf(conf, vmid)
    if vm_conf.get("ip"):
        return vm_conf["ip"]

    rules = vm_conf.get("id_ip_rules") or conf.get("settings", {}).get("id_ip_rules", [])
    for rule in rules:
        ip = apply_ip_rule(rule, vmid)
        if ip:
            return ip

    return "None"


def detect_default_ssh_port(vmid, conf):
    behavior = conf.get("settings", {}).get("behavior", {})
    linux_ssh = str(behavior.get("linux_ssh_port", "22"))
    windows_rdp = str(behavior.get("windows_rdp_port", "3389"))

    pconf = f"/etc/pve/qemu-server/{vmid}.conf"
    if os.path.exists(pconf):
        try:
            text = open(pconf, "r", encoding="utf-8", errors="ignore").read().lower()
            if "ostype: win" in text:
                return windows_rdp
        except Exception:
            pass
    return linux_ssh


def rule_condition_match(rule, vmid):
    v = int(vmid)
    vmid_min = int(rule.get("vmid_min", -10**9))
    vmid_max = int(rule.get("vmid_max", 10**9))
    if v < vmid_min or v > vmid_max:
        return False

    vmid_regex = rule.get("vmid_regex")
    if vmid_regex:
        try:
            if not re.match(vmid_regex, str(vmid)):
                return False
        except re.error:
            return False

    return True


def profile_enabled_for_vm(profile, vm_conf):
    default_enabled = bool(profile.get("enabled", True))
    override = vm_conf.get("profile_overrides", {}).get(str(profile.get("id")), {})
    if "enabled" in override:
        return bool(override["enabled"])
    return default_enabled


def get_profile_range(vmid, profile, vm_conf):
    override = vm_conf.get("profile_overrides", {}).get(str(profile.get("id")), {})
    rng = override.get("range_override", "")
    if "-" in str(rng):
        try:
            a, b = map(int, str(rng).split("-", 1))
            return a, b
        except Exception:
            pass

    start = int(profile.get("default_start", 30000))
    size = int(profile.get("per_vm_size", 20))
    idx = max(int(vmid) - int(profile.get("vmid_min", 100)), 0)
    pstart = start + idx * size
    pend = pstart + size - 1
    return pstart, pend


def expand_extra_profile_rules(vmid, conf, vm_conf):
    out = []
    profiles = conf.get("settings", {}).get("extra_forward_profiles", [])
    default_ssh = detect_default_ssh_port(vmid, conf)

    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        if not profile_enabled_for_vm(profile, vm_conf):
            continue
        if not rule_condition_match(profile, vmid):
            continue

        pstart, pend = get_profile_range(vmid, profile, vm_conf)
        ctx = build_context(vmid, default_ssh_port=default_ssh, profile_start=pstart, profile_end=pend)
        entries = profile.get("entries", [])
        protocols = profile.get("protocols", ["tcp", "udp"])

        for ent in entries:
            ext_raw = ent.get("ext")
            int_raw = ent.get("int")
            ext_port = render_template(ext_raw, ctx)
            int_port = render_template(int_raw, ctx)
            if not ext_port or not int_port:
                continue
            for proto in protocols:
                proto_l = str(proto).lower()
                if proto_l in ["tcp", "udp"]:
                    out.append(
                        {
                            "name": profile.get("name", profile.get("id", "profile")),
                            "ext": ext_port,
                            "int": int_port,
                            "proto": proto_l,
                            "source_type": "profile",
                            "profile_id": str(profile.get("id", "profile")),
                        }
                    )

    return out


def expand_port_rules(vmid, conf, vm_conf):
    default_ssh = detect_default_ssh_port(vmid, conf)
    ctx = build_context(vmid, default_ssh_port=default_ssh)

    rules = conf.get("settings", {}).get("port_forward_rules", [])
    vm_rules = vm_conf.get("port_rules", [])
    combined = list(rules) + list(vm_rules)

    candidates = []
    for rule in combined:
        if not isinstance(rule, dict):
            continue
        if not rule.get("enabled", True):
            continue
        if not rule_condition_match(rule, vmid):
            continue

        ext_raw = rule.get("ext")
        int_raw = rule.get("int")
        protocols = rule.get("protocols", ["tcp"])
        ext_port = render_template(ext_raw, ctx)
        int_port = render_template(int_raw, ctx)
        if not ext_port or not int_port:
            continue

        for proto in protocols:
            proto_l = str(proto).lower()
            if proto_l not in ["tcp", "udp"]:
                continue
            source_type = "vm_rule" if rule in vm_rules else "global_rule"
            candidates.append(
                {
                    "name": rule.get("name", "rule"),
                    "ext": ext_port,
                    "int": int_port,
                    "proto": proto_l,
                    "source_type": source_type,
                    "profile_id": "",
                }
            )

    candidates.extend(expand_extra_profile_rules(vmid, conf, vm_conf))

    for c in vm_conf.get("custom_ports", []):
        ext = str(c.get("ext", "")).replace("-", ":")
        intp = str(c.get("int", c.get("int_port", ""))).replace(":", "-")
        proto = str(c.get("proto", "tcp")).lower()
        if ext and intp and proto in ["tcp", "udp"]:
            candidates.append(
                {
                    "name": "custom",
                    "ext": ext,
                    "int": intp,
                    "proto": proto,
                    "source_type": "custom",
                    "profile_id": "",
                }
            )

    resolved = resolve_port_conflicts(candidates, conf)
    return [(r["name"], r["ext"], r["int"], r["proto"]) for r in resolved]


def _entry_priority(entry, conf):
    policy = conf.get("settings", {}).get("port_conflict_policy", {})
    priority = policy.get("priority", {})
    ptype = str(entry.get("source_type", "global_rule"))
    base = int(priority.get(ptype, 0))
    if ptype == "profile":
        pid = str(entry.get("profile_id", ""))
        base += int(policy.get("profile_priority", {}).get(pid, 0))
    return base


def _find_free_block(size, occupied, start, end):
    if size <= 0:
        return None
    for s in range(start, end - size + 2):
        block = set(range(s, s + size))
        if block.isdisjoint(occupied):
            return s, s + size - 1
    return None


def resolve_port_conflicts(candidates, conf):
    policy = conf.get("settings", {}).get("port_conflict_policy", {})
    mode = str(policy.get("mode", "priority-skip")).lower()
    remap = policy.get("remap_range", {})
    remap_start = int(remap.get("start", 45000))
    remap_end = int(remap.get("end", 65000))

    work = list(candidates)
    if mode in ["priority-skip", "priority-remap", "strict-error"]:
        work = sorted(
            list(enumerate(work)),
            key=lambda x: (_entry_priority(x[1], conf), -x[0]),
            reverse=True,
        )
        work = [x[1] for x in work]

    accepted = []
    occupied = {"tcp": set(), "udp": set()}

    for ent in work:
        ext = str(ent.get("ext", ""))
        proto = str(ent.get("proto", "tcp")).lower()
        if proto not in ["tcp", "udp"]:
            continue

        try:
            ports = expand_ports(ext)
        except Exception:
            accepted.append(ent)
            continue

        overlap = not ports.isdisjoint(occupied[proto])
        if not overlap:
            occupied[proto].update(ports)
            accepted.append(ent)
            continue

        if mode == "strict-error":
            raise ValueError(f"端口冲突: {proto} {ext} ({ent.get('name')})")

        if mode == "priority-remap":
            size = len(ports)
            block = _find_free_block(size, occupied[proto], remap_start, remap_end)
            if block:
                s, e = block
                ent2 = dict(ent)
                ent2["ext"] = str(s) if s == e else f"{s}:{e}"
                occupied[proto].update(set(range(s, e + 1)))
                accepted.append(ent2)
            continue

        # priority-skip / first-wins default behavior
        continue

    return accepted


def get_profile_status_for_vm(vmid, vm_conf, conf):
    items = []
    for p in conf.get("settings", {}).get("extra_forward_profiles", []):
        if not rule_condition_match(p, vmid):
            continue
        name = str(p.get("name", p.get("id", "profile")))
        enabled = profile_enabled_for_vm(p, vm_conf)
        if enabled:
            ps, pe = get_profile_range(vmid, p, vm_conf)
            items.append(f"{name}({ps}-{pe})")
    return "\n".join(items) if items else "[dim]No[/]"


def validate_config(conf, sample_vmids=None, get_all_vms_func=None):
    errors = []
    warnings = []

    policy = conf.get("settings", {}).get("vmid_policy", {})
    if not isinstance(policy.get("vm_ranges", []), list):
        errors.append("vmid_policy.vm_ranges 必须是列表")
    if not isinstance(policy.get("template_ranges", []), list):
        errors.append("vmid_policy.template_ranges 必须是列表")

    for rule in conf.get("settings", {}).get("id_ip_rules", []):
        if not isinstance(rule, dict):
            errors.append("id_ip_rules 存在非对象项")
            continue
        if "pattern" in rule:
            try:
                re.compile(str(rule.get("pattern")))
            except re.error as ex:
                errors.append(f"id_ip_rules[{rule.get('name','?')}] 正则错误: {ex}")

    def check_rule_ports(rules, where):
        for r in rules:
            if not isinstance(r, dict):
                errors.append(f"{where} 存在非对象项")
                continue
            ext = r.get("ext")
            intp = r.get("int")
            if ext is None or intp is None:
                errors.append(f"{where}[{r.get('name','?')}] 缺少 ext/int")
                continue
            if not validate_port_expr(ext, allow_template=True):
                errors.append(f"{where}[{r.get('name','?')}] ext 非法: {ext}")
            if not validate_port_expr(intp, allow_template=True):
                errors.append(f"{where}[{r.get('name','?')}] int 非法: {intp}")

    check_rule_ports(conf.get("settings", {}).get("port_forward_rules", []), "port_forward_rules")

    profiles = conf.get("settings", {}).get("extra_forward_profiles", [])
    seen_ids = set()
    for p in profiles:
        pid = str(p.get("id", ""))
        if not pid:
            errors.append("extra_forward_profiles 存在空 id")
            continue
        if pid in seen_ids:
            errors.append(f"extra_forward_profiles id 重复: {pid}")
        seen_ids.add(pid)
        if "entries" not in p or not isinstance(p["entries"], list) or not p["entries"]:
            errors.append(f"profile[{pid}] 缺少 entries")
            continue
        check_rule_ports(p["entries"], f"profile[{pid}].entries")

    dyn = conf.get("settings", {}).get("dynamic_tc", {})
    dyn_rules = dyn.get("rules", [])
    if dyn and not isinstance(dyn_rules, list):
        errors.append("dynamic_tc.rules 必须是列表")
    for idx, r in enumerate(dyn_rules if isinstance(dyn_rules, list) else []):
        if not isinstance(r, dict):
            errors.append(f"dynamic_tc.rules[{idx}] 必须是对象")
            continue
        if not str(r.get("name", "")).strip():
            errors.append(f"dynamic_tc.rules[{idx}] 缺少 name")
        for k in ["window_minutes", "throttle_minutes", "cooldown_minutes"]:
            try:
                v = int(r.get(k, 0))
                if v < 0:
                    errors.append(f"dynamic_tc.rules[{idx}].{k} 不能为负数")
            except Exception:
                errors.append(f"dynamic_tc.rules[{idx}].{k} 必须是整数")
        for k in ["rx_threshold_mib", "tx_threshold_mib"]:
            try:
                float(r.get(k, 0))
            except Exception:
                errors.append(f"dynamic_tc.rules[{idx}].{k} 必须是数字")
        for k in ["throttle_dn_mbit", "throttle_up_mbit"]:
            val = str(r.get(k, ""))
            if val and not re.match(r"^\d+(\.\d+)?mbit$", val):
                errors.append(f"dynamic_tc.rules[{idx}].{k} 必须是类似 50mbit 的格式")

    mon = conf.get("settings", {}).get("monitoring", {})
    if mon and not isinstance(mon, dict):
        errors.append("monitoring 必须是对象")
    alerts_cfg = mon.get("alerts", {}) if isinstance(mon, dict) else {}
    cleanup_cfg = mon.get("cleanup", {}) if isinstance(mon, dict) else {}
    snapshot_cfg = mon.get("snapshot", {}) if isinstance(mon, dict) else {}

    for k in ["node_cpu_pct", "node_mem_pct", "node_disk_pct"]:
        if k in alerts_cfg:
            try:
                v = float(alerts_cfg.get(k, 0))
                if v < 0 or v > 100:
                    errors.append(f"monitoring.alerts.{k} 必须在 0-100")
            except Exception:
                errors.append(f"monitoring.alerts.{k} 必须是数字")

    for k in ["vm_conn_total", "vm_conn_inbound", "vm_conn_outbound"]:
        if k in alerts_cfg:
            try:
                v = int(alerts_cfg.get(k, 0))
                if v < 0:
                    errors.append(f"monitoring.alerts.{k} 不能为负数")
            except Exception:
                errors.append(f"monitoring.alerts.{k} 必须是整数")

    for k in ["report_keep_days", "snapshot_keep_days"]:
        if k in cleanup_cfg:
            try:
                v = int(cleanup_cfg.get(k, 0))
                if v < 0:
                    errors.append(f"monitoring.cleanup.{k} 不能为负数")
            except Exception:
                errors.append(f"monitoring.cleanup.{k} 必须是整数")

    if "keep_days" in snapshot_cfg:
        try:
            v = int(snapshot_cfg.get("keep_days", 0))
            if v < 0:
                errors.append("monitoring.snapshot.keep_days 不能为负数")
        except Exception:
            errors.append("monitoring.snapshot.keep_days 必须是整数")

    for vmid, vmc in conf.get("vms", {}).items():
        if not str(vmid).isdigit():
            errors.append(f"vms 存在非法键: {vmid}")
            continue
        check_rule_ports(vmc.get("port_rules", []), f"vms.{vmid}.port_rules")

    if sample_vmids is None:
        sample_vmids = []
        if get_all_vms_func:
            sample_vmids = [str(v.get("vmid")) for v in get_all_vms_func()]

    for vmid in sample_vmids:
        vmc = get_vm_conf(conf, vmid)
        used = {}
        try:
            expanded = expand_port_rules(vmid, conf, vmc)
        except ValueError as ex:
            errors.append(f"vm {vmid} 规则冲突: {ex}")
            continue

        for rname, ext, _intp, proto in expanded:
            if "{" in str(ext):
                continue
            try:
                for p in expand_ports(ext):
                    key = f"{proto}:{p}"
                    if key in used:
                        warnings.append(f"vm {vmid} 外网端口冲突 {key}: {used[key]} vs {rname}")
                    else:
                        used[key] = rname
            except Exception:
                warnings.append(f"vm {vmid} 规则端口无法展开: {rname} ext={ext}")

    return errors, warnings


def preview_rules(vmid, conf):
    vmid = str(vmid)
    vmc = get_vm_conf(conf, vmid)
    rows = []
    for idx, (name, ext, intp, proto) in enumerate(expand_port_rules(vmid, conf, vmc)):
        rows.append({"idx": idx, "name": name, "proto": proto, "ext": ext, "int": intp, "ip": get_vm_ip(vmid, conf)})
    return rows


def to_json(data):
    return json.dumps(data, ensure_ascii=False, indent=2)
