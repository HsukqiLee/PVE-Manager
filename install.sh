#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/usr/local/bin"
CONFIG_PATH="/etc/pve/vmnat_config.json"
INSTALL_META="/etc/pve/vmmgr_install.conf"

REPO_OWNER="HsukqiLee"
REPO_NAME="PVE-Manager"
SOURCE_MODE="release"
FORCE_TAG=""
DRY_RUN="0"
RESOLVED_REF=""
RESOLVED_ARCHIVE_URL=""

WORK_DIR=""
SRC_DIR=""

usage() {
    cat <<EOF
用法:
  ./install.sh [选项]

选项:
  --install-dir PATH      安装目录 (默认: /usr/local/bin)
  --config PATH           配置文件路径 (默认: /etc/pve/vmnat_config.json)
  --meta PATH             安装元数据路径 (默认: /etc/pve/vmmgr_install.conf)
    --local                 从本地源码安装
  --from-release          从 release 压缩包安装
    --dry-run               仅显示将执行的动作，不做任何写入
  --repo-owner NAME       仓库 owner (默认: HsukqiLee)
  --repo-name NAME        仓库名 (默认: PVE-Manager)
  --tag TAG               指定 release tag (默认从 raw RELEASE_TAG 获取)
  -h, --help              显示帮助
EOF
}

cleanup() {
    if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
        rm -rf "$WORK_DIR"
    fi
}

resolve_extracted_dir() {
    local base_dir="$1"
    local candidate=""
    for candidate in "$base_dir"/*; do
        [[ -d "$candidate" ]] || continue
        if [[ -f "$candidate/vmmgrctl.py" && -d "$candidate/vmmgr_core" ]]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "错误: 缺少命令: $1"
        exit 1
    }
}

http_get() {
    local url="$1"
    local out="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$out"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$out" "$url"
    else
        echo "错误: 需要 curl 或 wget"
        exit 1
    fi
}

fetch_release_tag() {
    local tag_url="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/RELEASE_TAG"
    local tag
    if command -v curl >/dev/null 2>&1; then
        tag="$(curl -fsSL "$tag_url" 2>/dev/null || true)"
    elif command -v wget >/dev/null 2>&1; then
        tag="$(wget -qO- "$tag_url" 2>/dev/null || true)"
    else
        echo ""
        return 0
    fi
    echo "${tag//$'\r'/}"
}

resolve_archive_url() {
    local ref="$1"
    if [[ -z "$ref" || "$ref" == "main" ]]; then
        echo "https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/zip/refs/heads/main"
    else
        echo "https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/zip/refs/tags/${ref}"
    fi
}

prepare_source() {
    if [[ "$SOURCE_MODE" == "local" ]]; then
        SRC_DIR="$SCRIPT_DIR"
        RESOLVED_REF="local"
        RESOLVED_ARCHIVE_URL="local:$SCRIPT_DIR"
        return
    fi

    local ref="$FORCE_TAG"
    if [[ -z "$ref" ]]; then
        ref="$(fetch_release_tag)"
    fi
    [[ -z "$ref" ]] && ref="main"
    RESOLVED_REF="$ref"
    RESOLVED_ARCHIVE_URL="$(resolve_archive_url "$ref")"

    if [[ "$DRY_RUN" == "1" ]]; then
        return
    fi

    WORK_DIR="$(mktemp -d)"
    trap cleanup EXIT

    local zip_path="$WORK_DIR/release.zip"
    echo "下载: $RESOLVED_ARCHIVE_URL"
    http_get "$RESOLVED_ARCHIVE_URL" "$zip_path"

    need_cmd unzip
    unzip -q "$zip_path" -d "$WORK_DIR"

    local extracted
    extracted="$(resolve_extracted_dir "$WORK_DIR" || true)"
    if [[ -z "$extracted" ]]; then
        echo "错误: 解压后未找到目录"
        exit 1
    fi

    SRC_DIR="$extracted"
}

install_files() {
    mkdir -p "$INSTALL_DIR"
    rm -rf "$INSTALL_DIR/vmmgr_core"
    mkdir -p "$INSTALL_DIR/vmmgr_core"
    mkdir -p "$(dirname "$CONFIG_PATH")"
    mkdir -p "$(dirname "$INSTALL_META")"

    install -m 0755 "$SRC_DIR/vmmgrctl.py" "$INSTALL_DIR/vmmgrctl.py"
    install -m 0755 "$SRC_DIR/vmmgr.sh" "$INSTALL_DIR/vmmgr"
    cp -r "$SRC_DIR/vmmgr_core/." "$INSTALL_DIR/vmmgr_core/"

    # 清理无用或历史残留文件
    rm -f "$INSTALL_DIR/README.md" "$INSTALL_DIR/vmnat_config.example.json" "$INSTALL_DIR/vmnat_utils.py"
}

ensure_rich_dep() {
    local py_cmd=""
    if command -v python3 >/dev/null 2>&1; then
        py_cmd="python3"
    elif command -v python >/dev/null 2>&1; then
        py_cmd="python"
    else
        echo "警告: 未找到 python 解释器，跳过 rich 依赖检查"
        return 0
    fi

    if "$py_cmd" -c "import rich" >/dev/null 2>&1; then
        return 0
    fi

    echo "检测到缺少 rich，尝试自动安装..."
    if "$py_cmd" -m pip install -q rich; then
        echo "已安装 rich"
        return 0
    fi

    echo "警告: 自动安装 rich 失败，请手动执行: $py_cmd -m pip install rich"
    return 0
}


write_default_config() {
    [[ -f "$CONFIG_PATH" ]] && return 0
    cat > "$CONFIG_PATH" <<'JSON'
{
    "meta": {
        "version": 4
    },
    "settings": {
        "interfaces": {
            "ext": "vmbr0",
            "int": "homo"
        },
        "commands": {
            "pvesh": "pvesh",
            "iptables": "iptables",
            "iptables_save": "iptables-save",
            "qm": "qm",
            "pct": "pct"
        },
        "behavior": {
            "linux_ssh_port": "22",
            "windows_rdp_port": "3389",
            "postrouting_cidr": "10.10.0.0/16"
        },
        "operation_policy": {
            "scope_allowed_ops": {
                "vm": ["general", "hook", "nat", "power", "nickname", "xpf", "preview"],
                "template": ["hook"],
                "outside": []
            },
            "action_allowed_ops": {
                "allow": ["general", "hook", "nat", "power", "nickname", "xpf", "preview"],
                "ignore_explicit": ["general", "hook", "nat", "power", "nickname", "xpf", "preview"],
                "ignore_batch": []
            },
            "outside_ignore_explicit": true
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
            "vm_ranges": [
                {
                    "start": 100,
                    "end": 199
                }
            ],
            "template_ranges": [
                {
                    "start": 1000,
                    "end": 1099
                }
            ],
            "outside_default_action": "ignore",
            "id_actions": {}
        },
        "id_ip_rules": [
            {
                "name": "default-10.10",
                "enabled": true,
                "pattern": "^([1-9]\\d{2})$",
                "template": "10.10.{id_div_10}.{id_mod_10}"
            }
        ],
        "port_forward_rules": [
            {
                "name": "default-admin",
                "enabled": true,
                "vmid_min": 100,
                "vmid_max": 199,
                "protocols": ["tcp", "udp"],
                "ext": "{base_port}",
                "int": "{default_ssh_port}"
            },
            {
                "name": "default-range",
                "enabled": true,
                "vmid_min": 100,
                "vmid_max": 199,
                "protocols": ["tcp", "udp"],
                "ext": "{base_port_plus1}:{base_port_plus99}",
                "int": "{base_port_plus1}-{base_port_plus99}"
            }
        ],
        "extra_forward_profiles": [
            {
                "id": "trinet",
                "name": "三网端口",
                "enabled": true,
                "vmid_min": 100,
                "vmid_max": 199,
                "default_start": 30000,
                "per_vm_size": 20,
                "protocols": ["tcp", "udp"],
                "entries": [
                    {
                        "ext": "{profile_start}",
                        "int": "{default_ssh_port}"
                    },
                    {
                        "ext": "{profile_start_plus1}:{profile_end}",
                        "int": "{profile_start_plus1}-{profile_end}"
                    }
                ]
            }
        ]
    },
    "vms": {}
}
JSON
}

write_meta() {
    cat > "$INSTALL_META" <<EOF
# vmmgr 安装元数据
INSTALL_DIR="$INSTALL_DIR"
UTILS_PATH="$INSTALL_DIR/vmmgrctl.py"
VMMGR_PATH="$INSTALL_DIR/vmmgr"
CONFIG_PATH="$CONFIG_PATH"
REPO_OWNER="$REPO_OWNER"
REPO_NAME="$REPO_NAME"
INSTALL_SOURCE="$SOURCE_MODE"
RELEASE_TAG="${FORCE_TAG:-auto}"
EOF
}


init_hook_script() {
    local hook_path=""
    local err_file=""
    err_file="$(mktemp)"
    if hook_path="$("$INSTALL_DIR/vmmgrctl.py" --config "$CONFIG_PATH" ensure_hook_script 2>"$err_file")"; then
        rm -f "$err_file"
        echo "已初始化 Hook 脚本: ${hook_path}"
        return 0
    fi

    local err_out=""
    err_out="$(cat "$err_file" 2>/dev/null || true)"
    rm -f "$err_file"

    echo "警告: Hook 脚本初始化失败，可稍后手动执行:"
    echo "  $INSTALL_DIR/vmmgrctl.py --config $CONFIG_PATH ensure_hook_script"
    [[ -n "$err_out" ]] && echo "  详情: $err_out"
    return 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --config)
            CONFIG_PATH="$2"
            shift 2
            ;;
        --meta)
            INSTALL_META="$2"
            shift 2
            ;;
        --local)
            SOURCE_MODE="local"
            shift
            ;;
        --from-release)
            SOURCE_MODE="release"
            shift
            ;;
        --dry-run)
            DRY_RUN="1"
            shift
            ;;
        --repo-owner)
            REPO_OWNER="$2"
            shift 2
            ;;
        --repo-name)
            REPO_NAME="$2"
            shift 2
            ;;
        --tag)
            FORCE_TAG="$2"
            SOURCE_MODE="release"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            usage
            exit 1
            ;;
    esac
done

prepare_source

if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY-RUN] install 预览"
    echo "  source_mode: $SOURCE_MODE"
    echo "  repo: ${REPO_OWNER}/${REPO_NAME}"
    echo "  resolved_ref: ${RESOLVED_REF:-unknown}"
    echo "  resolved_archive: ${RESOLVED_ARCHIVE_URL:-unknown}"
    echo "  install_dir: $INSTALL_DIR"
    echo "  config_path: $CONFIG_PATH"
    echo "  meta_path: $INSTALL_META"
    echo "  result: 不会下载/解压/写入任何文件"
    exit 0
fi

install_files
write_default_config
write_meta
ensure_rich_dep
init_hook_script

echo "安装完成"
echo "  vmmgr: $INSTALL_DIR/vmmgr"
echo "  utils: $INSTALL_DIR/vmmgrctl.py"
echo "  配置: $CONFIG_PATH"
echo "  元数据: $INSTALL_META"
