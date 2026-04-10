#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_META="/etc/pve/vmmgr_install.conf"

SOURCE_MODE="release"
FORCE_TAG=""
FORCE_UPDATE="0"
DRY_RUN="0"
REPO_OWNER=""
REPO_NAME=""
PREV_RELEASE_TAG=""
SKIP_UPDATE="0"
RESOLVED_REF=""
RESOLVED_ARCHIVE_URL=""

WORK_DIR=""
SRC_DIR=""

usage() {
    cat <<EOF
用法:
  ./update.sh [meta_path] [选项]

选项:
  --local                 从本地目录更新（默认: release）
  --from-release          从 release 压缩包更新
  --tag TAG               指定 release tag（覆盖 RELEASE_TAG）
    --force                 即使 tag 无变化也强制更新
    --dry-run               仅显示将执行的动作，不做任何写入
  --repo-owner NAME       仓库 owner（覆盖元数据）
  --repo-name NAME        仓库名（覆盖元数据）
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

    if [[ "$FORCE_UPDATE" != "1" && -n "$PREV_RELEASE_TAG" && "$ref" == "$PREV_RELEASE_TAG" ]]; then
        echo "release tag 未变化 ($ref)，跳过更新。可使用 --force 强制更新。"
        SKIP_UPDATE="1"
        return
    fi

    if [[ "$DRY_RUN" == "1" ]]; then
        FORCE_TAG="$ref"
        return
    fi

    WORK_DIR="$(mktemp -d)"
    trap cleanup EXIT

    local zip_path="$WORK_DIR/release.zip"
    echo "下载: $RESOLVED_ARCHIVE_URL"
    http_get "$RESOLVED_ARCHIVE_URL" "$zip_path"

    if ! command -v unzip >/dev/null 2>&1; then
        echo "错误: 需要 unzip"
        exit 1
    fi

    unzip -q "$zip_path" -d "$WORK_DIR"
    local extracted
    extracted="$(resolve_extracted_dir "$WORK_DIR" || true)"
    if [[ -z "$extracted" ]]; then
        echo "错误: 解压后未找到目录"
        exit 1
    fi

    SRC_DIR="$extracted"
    FORCE_TAG="$ref"
}

install_files() {
    mkdir -p "$INSTALL_DIR"
    rm -rf "$INSTALL_DIR/vmmgr_core"
    mkdir -p "$INSTALL_DIR/vmmgr_core"

    install -m 0755 "$SRC_DIR/vmmgrctl.py" "$INSTALL_DIR/vmmgrctl.py"
    install -m 0755 "$SRC_DIR/vmmgr.sh" "$INSTALL_DIR/vmmgr"
    cp -r "$SRC_DIR/vmmgr_core/." "$INSTALL_DIR/vmmgr_core/"

    # 清理无用或历史残留文件
    rm -f "$INSTALL_DIR/README.md" "$INSTALL_DIR/vmnat_config.example.json" "$INSTALL_DIR/vmnat_utils.py"
}

ensure_cron() {
    [[ "${AUTO_CRON_SYNC_TC:-1}" != "1" ]] && return 0
    local cron_line="* * * * * $INSTALL_DIR/vmmgrctl.py --config $CONFIG_PATH sync_all --type tc >/dev/null 2>&1; $INSTALL_DIR/vmmgrctl.py --config $CONFIG_PATH dyn_tc_check >/dev/null 2>&1; $INSTALL_DIR/vmmgrctl.py --config $CONFIG_PATH alert_check --json >/dev/null 2>&1; $INSTALL_DIR/vmmgrctl.py --config $CONFIG_PATH cleanup_auto --json >/dev/null 2>&1"
    if ! crontab -l 2>/dev/null | grep -Fq "$cron_line"; then
        (crontab -l 2>/dev/null; echo "$cron_line") | crontab -
    fi
}

write_meta() {
    local final_tag="${FORCE_TAG:-$PREV_RELEASE_TAG}"
    [[ -z "$final_tag" ]] && final_tag="unknown"
    cat > "$INSTALL_META" <<EOF
# vmmgr 安装元数据
INSTALL_DIR="$INSTALL_DIR"
UTILS_PATH="$INSTALL_DIR/vmmgrctl.py"
VMMGR_PATH="$INSTALL_DIR/vmmgr"
CONFIG_PATH="$CONFIG_PATH"
AUTO_CRON_SYNC_TC="${AUTO_CRON_SYNC_TC:-1}"
REPO_OWNER="$REPO_OWNER"
REPO_NAME="$REPO_NAME"
INSTALL_SOURCE="$SOURCE_MODE"
RELEASE_TAG="$final_tag"
EOF
}

# 兼容 update.sh /path/to/meta --tag v1.0.0 的调用
if [[ $# -gt 0 && "$1" != -* ]]; then
    INSTALL_META="$1"
    shift
fi

if [[ ! -f "$INSTALL_META" ]]; then
    echo "错误: 未找到安装元数据: $INSTALL_META"
    echo "请先执行 ./install.sh，或把元数据路径作为第一个参数传入。"
    exit 1
fi

# shellcheck disable=SC1090
source "$INSTALL_META"

if [[ -z "${INSTALL_DIR:-}" || -z "${CONFIG_PATH:-}" ]]; then
    echo "错误: 安装元数据缺少 INSTALL_DIR 或 CONFIG_PATH"
    exit 1
fi

REPO_OWNER="${REPO_OWNER:-HsukqiLee}"
REPO_NAME="${REPO_NAME:-PVE-Manager}"
PREV_RELEASE_TAG="${RELEASE_TAG:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --local)
            SOURCE_MODE="local"
            shift
            ;;
        --from-release)
            SOURCE_MODE="release"
            shift
            ;;
        --tag)
            FORCE_TAG="$2"
            SOURCE_MODE="release"
            shift 2
            ;;
        --force)
            FORCE_UPDATE="1"
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
    echo "[DRY-RUN] update 预览"
    echo "  source_mode: $SOURCE_MODE"
    echo "  repo: ${REPO_OWNER}/${REPO_NAME}"
    echo "  local_release_tag: ${PREV_RELEASE_TAG:-none}"
    echo "  remote_or_target_tag: ${RESOLVED_REF:-unknown}"
    echo "  resolved_archive: ${RESOLVED_ARCHIVE_URL:-unknown}"
    echo "  skip_update: $SKIP_UPDATE"
    echo "  force_update: $FORCE_UPDATE"
    echo "  install_dir: $INSTALL_DIR"
    echo "  config_path: $CONFIG_PATH"
    echo "  meta_path: $INSTALL_META"
    echo "  result: 不会下载/解压/写入任何文件"
    exit 0
fi

if [[ "$SKIP_UPDATE" == "1" ]]; then
    exit 0
fi
install_files
write_meta
ensure_cron

echo "更新完成"
echo "  已更新: $INSTALL_DIR/vmmgr"
echo "  已更新: $INSTALL_DIR/vmmgrctl.py"
echo "  配置仍使用: $CONFIG_PATH"
