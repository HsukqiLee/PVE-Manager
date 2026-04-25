import subprocess
import json

# 1. 定义你提供的数据
# 格式: 主机名: (管理IP/mgmt, 业务IP/biz)
data = {
    "iStoreOS-Erectus": ("10.10.0.2", ""),
    "OPNsense-Habilis": ("10.10.0.3", ""),
    "ubuntu24-lxq": ("10.10.10.0", "100.112.247.227"),
    "debian13-syl": ("10.10.10.1", "100.112.247.228"),
    "nixos-hafnon": ("10.10.10.2", "100.112.247.229"),
    "ubuntu24-steve": ("10.10.10.3", "100.112.247.230"),
    "debian13-ajgamma": ("10.10.10.5", "100.112.247.231"),
    "ubuntu24-yy": ("10.10.10.6", "100.112.247.232"),
    "debian13-sz": ("10.10.10.7", "100.112.247.233"),
    "ubuntu24-dreemurr": ("10.10.10.8", "100.112.247.234"),
    "ubuntu24-orange": ("10.10.11.0", "100.112.247.235"),
    "ubuntu24-sean": ("10.10.11.1", "100.112.247.236"),
    "debian13-fy": ("10.10.11.4", "100.112.247.237"),
    "fnos-wulixi8": ("10.10.11.7", "100.112.247.238"),
}

def run_vmmgr_set_ip(vmid, name, mgmt, biz):
    cmd = ["vmmgr", "set_ip", "--vmid", str(vmid)]
    if mgmt: cmd.extend(["--mgmt", mgmt])
    if biz: cmd.extend(["--biz", biz])
    print(f"正在设置 VM {vmid} ({name}): mgmt={mgmt}, biz={biz}")
    subprocess.run(cmd)

# 2. 获取当前 PVE 所有的 VM/LXC 列表
try:
    vms_raw = subprocess.check_output(["pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"])
    vms = json.loads(vms_raw)
except Exception as e:
    print(f"获取 PVE 资源列表失败: {e}")
    exit(1)

# 3. 遍历并匹配设置
found_count = 0
for name, (mgmt, biz) in data.items():
    matched_vmid = None
    for vm in vms:
        if vm.get("name") == name:
            matched_vmid = vm.get("vmid")
            break
    
    if matched_vmid:
        run_vmmgr_set_ip(matched_vmid, name, mgmt, biz)
        found_count += 1
    else:
        print(f"警告: 未在 PVE 中找到名为 '{name}' 的虚拟机，跳过。")

print(f"\n批量设置完成！共成功匹配并设置了 {found_count} 个虚拟机。")
