#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_META_DEFAULT="/etc/pve/vmmgr_install.conf"
INSTALL_META="${VMMGR_INSTALL_META:-$INSTALL_META_DEFAULT}"

if [[ -f "$INSTALL_META" ]]; then
    # shellcheck disable=SC1090
    source "$INSTALL_META"
fi

UTILS="${VMMGR_UTILS:-${UTILS_PATH:-/usr/local/bin/vmmgrctl.py}}"
CONFIG_FILE="${VMMGR_CONFIG_FILE:-${CONFIG_PATH:-/etc/pve/vmnat_config.json}}"
AUTO_CRON="${AUTO_CRON_SYNC_TC:-1}"

if [[ ! -x "$UTILS" ]]; then
    echo "错误: 找不到可执行工具脚本: $UTILS"
    echo "可通过环境变量 VMMGR_UTILS 指定路径，或检查安装元数据: $INSTALL_META"
    exit 1
fi

util() {
    "$UTILS" --config "$CONFIG_FILE" "$@"
}

ensure_cron() {
    [[ "$AUTO_CRON" != "1" ]] && return 0
    local cron_line="0 * * * * $UTILS --config $CONFIG_FILE sync_all --type tc >/dev/null 2>&1"
    if ! crontab -l 2>/dev/null | grep -Fq "$cron_line"; then
        (crontab -l 2>/dev/null; echo "$cron_line") | crontab -
    fi
}

get_term_size() {
    echo "$(tput lines)x$(tput cols)"
}

render_screen() {
    case "${RENDER_VIEW:-menu}" in
        menu) util menu ;;
        list) util list ;;
        hook) util show_menu_hook ;;
        xpf) util show_menu_xpf ;;
        nat) util show_menu_nat ;;
        speed) util show_menu_speed ;;
        nickname) util show_menu_nickname ;;
        power) util show_menu_power ;;
        p_list) util p_list --vmid "${RENDER_VMID:-0}" ;;
        *) util menu ;;
    esac
}

smart_read() {
    local prompt="$1"
    local var_name="$2"
    local last_size
    local curr_size
    local input_buffer=""
    local char=""

    last_size="$(get_term_size)"
    while true; do
        clear
        render_screen
        echo -ne "$prompt"
        while true; do
            if IFS= read -r -s -t 0.3 -n 1 char; then
                if [[ -z "$char" ]]; then
                    printf -v "$var_name" '%s' "$input_buffer"
                    echo ""
                    return 0
                fi
                if [[ "$char" == $'\177' || "$char" == $'\b' ]]; then
                    if [[ ${#input_buffer} -gt 0 ]]; then
                        input_buffer="${input_buffer%?}"
                        echo -ne "\b \b"
                    fi
                else
                    input_buffer+="$char"
                    echo -n "$char"
                fi
            fi
            curr_size="$(get_term_size)"
            if [[ "$curr_size" != "$last_size" ]]; then
                last_size="$curr_size"
                break 2
            fi
        done
    done
}

pause() {
    read -r -n 1 -s -p "按任意键继续..."
    echo ""
}

TARGETS=""
get_targets() {
    local input="$1"
    local op="${2:-general}"
    TARGETS="$(util parse_vms --input "$input" --op "$op")"
    if [[ -z "$TARGETS" ]]; then
        echo "错误: 未找到符合条件的合法实例！"
        sleep 1
        return 1
    fi
    return 0
}

ensure_cron

while true; do
    RENDER_VIEW="menu"
    smart_read "请输入操作选项数字: " choice
    case "$choice" in
        1)
            RENDER_VIEW="list"
            smart_read "按回车键返回主菜单..." _unused
            ;;
        2)
            while true; do
                RENDER_VIEW="hook"
                smart_read "请选择 Hook 操作 (输入对应数字): " h_choice
                [[ "$h_choice" == "0" ]] && break
                if [[ "$h_choice" == "1" || "$h_choice" == "2" ]]; then
                    read -r -p "目标 VMID: " input
                    get_targets "$input" "hook" || continue
                    for v in $TARGETS; do
                        local_conf=""
                        if [[ -f "/etc/pve/lxc/$v.conf" ]]; then
                            local_conf="/etc/pve/lxc/$v.conf"
                        elif [[ -f "/etc/pve/qemu-server/$v.conf" ]]; then
                            local_conf="/etc/pve/qemu-server/$v.conf"
                        fi
                        if [[ -n "$local_conf" ]]; then
                            sed -i '/hookscript:/d' "$local_conf"
                            [[ "$h_choice" == "1" ]] && echo "hookscript: local:snippets/nat_hook.py" >> "$local_conf"
                            echo "已处理实例: $v"
                        fi
                    done
                    sleep 1
                fi
            done
            ;;
        3)
            while true; do
                RENDER_VIEW="xpf"
                smart_read "请选择额外端口转发操作: " t_choice
                [[ "$t_choice" == "0" ]] && break
                if [[ "$t_choice" == "1" || "$t_choice" == "2" ]]; then
                    read -r -p "目标 VMID: " input
                    get_targets "$input" "nat" || continue
                    read -r -p "Profile ID (默认 trinet): " profile
                    [[ -z "$profile" ]] && profile="trinet"
                    for v in $TARGETS; do
                        act="disable"
                        [[ "$t_choice" == "1" ]] && act="enable"
                        util xpf_act --act "$act" --vmid "$v" --profile "$profile"
                    done
                    sleep 1
                elif [[ "$t_choice" == "3" ]]; then
                    read -r -p "目标 VMID (仅支持单台): " input
                    TARGETS="$(util parse_vms --input "$input" --op "nat")"
                    if [[ -z "$TARGETS" ]] || [[ $(wc -w <<< "$TARGETS") -gt 1 ]]; then
                        echo "错误: 仅支持单台！"
                        sleep 1
                        continue
                    fi
                    read -r -p "Profile ID (默认 trinet): " profile
                    [[ -z "$profile" ]] && profile="trinet"
                    read -r -p "覆写范围 (格式如 31000-31019, 直接回车清空): " rng
                    util xpf_act --act modify --vmid "$TARGETS" --profile "$profile" --range "$rng"
                    echo "修改完成！"
                    sleep 1
                fi
            done
            ;;
        4)
            while true; do
                RENDER_VIEW="nat"
                smart_read "请选择映射管理操作: " p_choice
                [[ "$p_choice" == "0" ]] && break
                if [[ "$p_choice" == "1" ]]; then
                    read -r -p "输入 VMID: " v
                    util get_ip --vmid "$v" >/dev/null || {
                        echo "VMID 错误"
                        sleep 1
                        continue
                    }
                    while true; do
                        RENDER_VIEW="p_list"
                        RENDER_VMID="$v"
                        smart_read "操作 (1添/2改/3删/0返): " s
                        [[ "$s" == "0" ]] && break
                        case "$s" in
                            1)
                                read -r -p "外网端: " e
                                read -r -p "内网端: " i
                                read -r -p "协议: " pr
                                util manage_port --vmid "$v" --act add --ext "$e" --int_port "$i" --proto "$pr"
                                util apply_nat --vmid "$v" --act add
                                ;;
                            2)
                                read -r -p "编号: " idx
                                read -r -p "新外: " e
                                read -r -p "新内: " i
                                read -r -p "新协: " pr
                                [[ -z "$e" ]] && e="-"
                                [[ -z "$i" ]] && i="-"
                                [[ -z "$pr" ]] && pr="-"
                                util manage_port --vmid "$v" --act edit --idx "$idx" --ext "$e" --int_port "$i" --proto "$pr"
                                util apply_nat --vmid "$v" --act add
                                ;;
                            3)
                                read -r -p "编号: " idx
                                util manage_port --vmid "$v" --act del --idx "$idx"
                                util apply_nat --vmid "$v" --act add
                                ;;
                        esac
                    done
                fi
            done
            ;;
        5)
            while true; do
                RENDER_VIEW="speed"
                smart_read "请选择限速配置操作: " s_choice
                [[ "$s_choice" == "0" ]] && break
                case "$s_choice" in
                    1|2)
                        if [[ "$s_choice" == "2" ]]; then
                            read -r -p "目标 VMID: " input
                            get_targets "$input" "tc" || continue
                        fi
                        read -r -p "生效星期 (1-7, 如1-5, 直接回车全周): " days
                        read -r -p "起始小时 (0-23, 直接回车全天): " ts
                        read -r -p "结束小时 (1-24, 直接回车全天): " te
                        read -r -p "下行速率 (Mbps, 0为无限制): " dr
                        read -r -p "上行速率 (Mbps, 0为无限制): " ur
                        [[ -z "$days" ]] && days="all"
                        [[ -z "$ts" ]] && ts="0"
                        [[ -z "$te" ]] && te="24"
                        if [[ "$s_choice" == "1" ]]; then
                            util manage_limit --type global --days "$days" --ts "$ts" --te "$te" --dr "$dr" --ur "$ur"
                        else
                            for v in $TARGETS; do
                                util manage_limit --type vm --vmid "$v" --days "$days" --ts "$ts" --te "$te" --dr "$dr" --ur "$ur"
                            done
                        fi
                        util sync_all --type tc
                        pause
                        ;;
                    3)
                        read -r -p "目标 VMID: " input
                        get_targets "$input" "tc" || continue
                        read -r -p "编号 (回车全清): " idx
                        for v in $TARGETS; do
                            util clear_limit --type vm --vmid "$v" --idx "$idx"
                        done
                        util sync_all --type tc
                        sleep 1
                        ;;
                    4)
                        read -r -p "全局规则编号 (回车全清): " idx
                        util clear_limit --type global --idx "$idx"
                        util sync_all --type tc
                        sleep 1
                        ;;
                esac
            done
            ;;
        6)
            while true; do
                RENDER_VIEW="nickname"
                smart_read "昵称操作: " n_choice
                [[ "$n_choice" == "0" ]] && break
                if [[ "$n_choice" == "1" ]]; then
                    read -r -p "目标 VMID: " input
                    get_targets "$input" "general" || continue
                    read -r -p "新昵称 (回车取消): " nick
                    for v in $TARGETS; do
                        if [[ -z "$nick" ]]; then
                            util manage_nick --vmid "$v" --act clear
                        else
                            util manage_nick --vmid "$v" --act set --nick "$nick"
                        fi
                    done
                    echo "完成"
                    sleep 1
                fi
            done
            ;;
        7)
            while true; do
                RENDER_VIEW="power"
                smart_read "电源操作: " p_choice
                [[ "$p_choice" == "0" ]] && break
                if [[ "$p_choice" == "1" || "$p_choice" == "2" || "$p_choice" == "3" ]]; then
                    read -r -p "目标 VMID: " input
                    get_targets "$input" "power" || continue
                    for v in $TARGETS; do
                        act="start"
                        [[ "$p_choice" == "2" ]] && act="stop"
                        [[ "$p_choice" == "3" ]] && act="reboot"
                        util power --vmid "$v" --act "$act"
                    done
                    pause
                fi
            done
            ;;
        8)
            echo "规则刷新中..."
            util sync_all --type all
            echo "刷新完成"
            sleep 1
            ;;
        9)
            echo "重置网络中..."
            util sync_all --type all --reset
            sleep 1
            ;;
        10)
            echo "配置校验中..."
            util validate
            pause
            ;;
        11)
            read -r -p "预览 VMID: " v
            util preview_rules --vmid "$v"
            pause
            ;;
        0)
            clear
            exit 0
            ;;
    esac
done
