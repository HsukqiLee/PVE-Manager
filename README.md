# PVE-Manager

PVE 管理脚本，支持菜单化管理 NAT、端口转发、额外端口转发、动态限速、昵称、电源控制与监控中心。

## 一键安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/HsukqiLee/PVE-Manager/main/install.sh)
```

指定安装参数示例:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/HsukqiLee/PVE-Manager/main/install.sh) --install-dir /usr/local/bin --config /etc/pve/vmnat_config.json
```

## 一键更新

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/HsukqiLee/PVE-Manager/main/update.sh)
```

强制更新:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/HsukqiLee/PVE-Manager/main/update.sh) --force
```

指定版本更新:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/HsukqiLee/PVE-Manager/main/update.sh) --tag v1.2.3
```

## 脚本方式（下载后执行）

```bash
curl -fsSL -o install.sh https://raw.githubusercontent.com/HsukqiLee/PVE-Manager/main/install.sh
curl -fsSL -o update.sh https://raw.githubusercontent.com/HsukqiLee/PVE-Manager/main/update.sh
chmod +x install.sh update.sh
./install.sh
./update.sh
```

## 文档

- 菜单与功能说明: [docs/menu.md](docs/menu.md)
- 配置示例: [vmnat_config.example.json](vmnat_config.example.json)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=HsukqiLee/PVE-Manager&type=Date)](https://star-history.com/#HsukqiLee/PVE-Manager&Date)
