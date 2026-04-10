import json
import os
from copy import deepcopy

from .constants import DEFAULT_IFACE_EXT, DEFAULT_IFACE_INT


def default_config():
    return {
        "meta": {"version": 4},
        "settings": {
            "interfaces": {"ext": DEFAULT_IFACE_EXT, "int": DEFAULT_IFACE_INT},
            "commands": {
                "pvesh": "pvesh",
                "iptables": "iptables",
                "iptables_save": "iptables-save",
                "tc": "tc",
                "qm": "qm",
                "pct": "pct",
            },
            "behavior": {
                "linux_ssh_port": "22",
                "windows_rdp_port": "3389",
                "postrouting_cidr": "10.10.0.0/16",
            },
            "operation_policy": {
                "scope_allowed_ops": {
                    "vm": ["general", "hook", "nat", "tc", "power", "limit", "nickname", "xpf", "preview"],
                    "template": ["hook"],
                    "outside": []
                },
                "action_allowed_ops": {
                    "allow": ["general", "hook", "nat", "tc", "power", "limit", "nickname", "xpf", "preview"],
                    "ignore_explicit": ["general", "hook", "nat", "tc", "power", "limit", "nickname", "xpf", "preview"],
                    "ignore_batch": []
                },
                "outside_ignore_explicit": True
            },
            "port_conflict_policy": {
                "mode": "priority-skip",
                "priority": {
                    "global_rule": 100,
                    "profile": 200,
                    "vm_rule": 300,
                    "custom": 400
                },
                "profile_priority": {},
                "remap_range": {
                    "start": 45000,
                    "end": 65000
                }
            },
            "vmid_policy": {
                "vm_ranges": [{"start": 100, "end": 199}],
                "template_ranges": [{"start": 1000, "end": 1099}],
                "outside_default_action": "ignore",
                "id_actions": {},
            },
            "id_ip_rules": [
                {
                    "name": "default-10.10",
                    "enabled": True,
                    "pattern": "^([1-9]\\d{2})$",
                    "template": "10.10.{id_div_10}.{id_mod_10}",
                }
            ],
            "port_forward_rules": [
                {
                    "name": "default-admin",
                    "enabled": True,
                    "vmid_min": 100,
                    "vmid_max": 199,
                    "protocols": ["tcp", "udp"],
                    "ext": "{base_port}",
                    "int": "{default_ssh_port}",
                },
                {
                    "name": "default-range",
                    "enabled": True,
                    "vmid_min": 100,
                    "vmid_max": 199,
                    "protocols": ["tcp", "udp"],
                    "ext": "{base_port_plus1}:{base_port_plus99}",
                    "int": "{base_port_plus1}-{base_port_plus99}",
                },
            ],
            "extra_forward_profiles": [
                {
                    "id": "trinet",
                    "name": "三网端口",
                    "enabled": True,
                    "vmid_min": 100,
                    "vmid_max": 199,
                    "default_start": 30000,
                    "per_vm_size": 20,
                    "protocols": ["tcp", "udp"],
                    "entries": [
                        {"ext": "{profile_start}", "int": "{default_ssh_port}"},
                        {"ext": "{profile_start_plus1}:{profile_end}", "int": "{profile_start_plus1}-{profile_end}"},
                    ],
                }
            ],
        },
        "global_limits": [],
        "vms": {},
    }


def deep_merge(base, override):
    result = deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def migrate_legacy_config(raw):
    if not isinstance(raw, dict):
        return default_config()

    cfg = default_config()

    if "vms" in raw and isinstance(raw.get("vms"), dict):
        cfg = deep_merge(cfg, raw)

    for k, v in raw.items():
        if str(k).isdigit() and isinstance(v, dict):
            cfg.setdefault("vms", {})[str(k)] = v

    if "global_limits" in raw and isinstance(raw["global_limits"], list):
        cfg["global_limits"] = raw["global_limits"]

    if "settings" in raw and isinstance(raw["settings"], dict):
        cfg["settings"] = deep_merge(cfg["settings"], raw["settings"])

    op = cfg.setdefault("settings", {}).setdefault("operation_policy", {})
    if "template_allowed_ops" in op:
        scope = op.setdefault("scope_allowed_ops", {})
        scope["template"] = list(op.get("template_allowed_ops", ["hook"]))
        op.pop("template_allowed_ops", None)

    policy = cfg.setdefault("settings", {}).setdefault("vmid_policy", {})
    # migrate v3 min/max/allow_list/deny_list
    if "min" in policy or "max" in policy:
        min_v = int(policy.get("min", 1))
        max_v = int(policy.get("max", 999999))
        policy["vm_ranges"] = [{"start": min_v, "end": max_v}]
        policy.pop("min", None)
        policy.pop("max", None)
    if "allow_list" in policy:
        id_actions = policy.setdefault("id_actions", {})
        for i in policy.get("allow_list", []):
            id_actions[str(i)] = "allow"
        policy.pop("allow_list", None)
    if "deny_list" in policy:
        id_actions = policy.setdefault("id_actions", {})
        for i in policy.get("deny_list", []):
            id_actions[str(i)] = "deny"
        policy.pop("deny_list", None)

    for _vmid, vmc in cfg.get("vms", {}).items():
        if vmc.get("enable_tri_net") is not None or vmc.get("overwrite_tri_net_range"):
            vmc.setdefault("profile_overrides", {})
            vmc["profile_overrides"].setdefault("trinet", {})
            vmc["profile_overrides"]["trinet"]["enabled"] = bool(vmc.get("enable_tri_net", False))
            if vmc.get("overwrite_tri_net_range"):
                vmc["profile_overrides"]["trinet"]["range_override"] = vmc.get("overwrite_tri_net_range")

    return cfg


def load_config(config_file):
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return migrate_legacy_config(raw)
        except Exception:
            return default_config()
    return default_config()


def save_config(data, config_file):
    payload = deepcopy(data)
    vms = payload.get("vms", {})
    payload["vms"] = {
        k: v
        for k, v in sorted(
            vms.items(), key=lambda item: int(item[0]) if str(item[0]).isdigit() else 999999
        )
    }
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)


def parse_days(s):
    if not s or str(s).lower() == "all":
        return list(range(1, 8))
    res = set()
    try:
        for part in str(s).split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start, end = map(int, part.split("-", 1))
                res.update(range(start, end + 1))
            else:
                res.add(int(part))
        valid = sorted([d for d in res if 1 <= d <= 7])
        return valid if valid else list(range(1, 8))
    except Exception:
        return list(range(1, 8))
