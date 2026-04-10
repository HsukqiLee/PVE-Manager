import os

DEFAULT_CONFIG_FILE = os.environ.get("VMMGR_CONFIG_FILE", "/etc/pve/vmnat_config.json")
LOCK_FILE = "/var/run/pve_nat.lock"
AUDIT_LOG = "/var/log/vmmgr_audit.log"
DEFAULT_IFACE_EXT = "vmbr0"
DEFAULT_IFACE_INT = "homo"
