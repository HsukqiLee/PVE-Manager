from typing import Dict


def _range_contains(v, ranges):
    for item in ranges or []:
        try:
            if int(item.get("start", 0)) <= v <= int(item.get("end", 0)):
                return True
        except Exception:
            continue
    return False


def vmid_scope(vmid, conf):
    v = int(vmid)
    policy = conf.get("settings", {}).get("vmid_policy", {})
    if _range_contains(v, policy.get("vm_ranges", [])):
        return "vm"
    if _range_contains(v, policy.get("template_ranges", [])):
        return "template"
    return "outside"


def vmid_action(vmid, conf):
    policy = conf.get("settings", {}).get("vmid_policy", {})
    return str(policy.get("id_actions", {}).get(str(vmid), policy.get("outside_default_action", "ignore"))).lower()


def vmid_access(vmid, conf, operation, explicit=False, batch=False) -> Dict[str, object]:
    scope = vmid_scope(vmid, conf)
    action = vmid_action(vmid, conf)
    op_name = str(operation).lower()
    op_policy = conf.get("settings", {}).get("operation_policy", {})
    scope_allowed_ops = op_policy.get("scope_allowed_ops", {})
    vm_allowed_ops = [str(x).lower() for x in scope_allowed_ops.get("vm", ["general", "hook", "nat", "power", "nickname", "xpf", "preview"])]
    template_allowed_ops = [str(x).lower() for x in scope_allowed_ops.get("template", ["hook"])]
    outside_allowed_ops = [str(x).lower() for x in scope_allowed_ops.get("outside", [])]
    action_allowed_ops = op_policy.get("action_allowed_ops", {})
    allow_ops = [str(x).lower() for x in action_allowed_ops.get("allow", vm_allowed_ops)]
    ignore_explicit_ops = [str(x).lower() for x in action_allowed_ops.get("ignore_explicit", allow_ops)]
    ignore_batch_ops = [str(x).lower() for x in action_allowed_ops.get("ignore_batch", outside_allowed_ops)]
    outside_ignore_explicit = bool(op_policy.get("outside_ignore_explicit", True))

    # explicit deny always wins
    if action == "deny":
        return {"allow": False, "reason": "deny", "scope": scope}

    # templates: only hook operations allowed
    if scope == "template":
        if op_name in template_allowed_ops:
            return {"allow": True, "reason": "template-hook", "scope": scope}
        return {"allow": False, "reason": "template-readonly", "scope": scope}

    # in vm ranges: always allowed unless denied above
    if scope == "vm":
        if op_name not in vm_allowed_ops:
            return {"allow": False, "reason": "vm-op-blocked", "scope": scope}
        return {"allow": True, "reason": "vm-range", "scope": scope}

    # outside ranges: allow/ignore/deny behavior
    if action == "allow":
        if op_name not in allow_ops:
            return {"allow": False, "reason": "outside-allow-op-blocked", "scope": scope}
        return {"allow": True, "reason": "outside-allow", "scope": scope}
    if action == "ignore":
        if outside_ignore_explicit and explicit and not batch and op_name in ignore_explicit_ops:
            return {"allow": True, "reason": "outside-ignore-explicit", "scope": scope}
        if batch and op_name in ignore_batch_ops:
            return {"allow": True, "reason": "outside-ignore-batch-op", "scope": scope}
        return {"allow": False, "reason": "outside-ignore", "scope": scope}

    # fallback: conservative deny
    return {"allow": False, "reason": "outside-default", "scope": scope}


def vmid_allowed(vmid, conf, operation, explicit=False, batch=False):
    return bool(vmid_access(vmid, conf, operation, explicit=explicit, batch=batch).get("allow"))
