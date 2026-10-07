# gimp-retouch-plugins

GIMP 3 (3.0 / 3.2) Python 插件集，跨 Linux / Windows。

## 插件
- `fsep_oneclick` — 一键频率分离（尚未人工验证）
- `dnb_setup` — 一键加深减淡搭建（尚未人工验证），详见 `dnb_setup/README.md`
- `raw_to_tiff/raw2tiff.sh` — RAW→16 位 TIFF 批量转换（RawTherapee CLI，尚未人工验证），RAW → raw2tiff → batch_export 流程见 `raw_to_tiff/README.md`
- `batch_export` — 批量导出（尚未人工验证），支持命令行无界面调用，详见 `batch_export/README.md`

## 一键安装 / 重装（尚未人工验证）
Linux（GIMP 3.0 apt + GIMP 3.2 Flatpak --user）：
```bash
./install.sh --dry-run                    # 预览：不改动任何东西，读取现有 pluginrc
./install.sh                              # 安装缺失/版本不符的组件（幂等）
./install.sh --reinstall --gimp 3.2 --only ours
```
参数：`--gimp 3.0|3.2|all`、`--only ours|third-party|all`、`--reinstall`、`--dry-run`、`--with-photogimp`（覆盖配置，默认不装）、`--with-raw`（apt 安装固定版本 RawTherapee 5.11-2+b2，默认不装）、`--no-verify`、`--backup-dir DIR`。
流程：备份 `~/.config/GIMP/<ver>` 到 `~/gimp-bundle-backups/gimp-config-<时间>.tgz` → 安装本仓库插件 → 按 `bundle.lock` 固定版本从原始来源下载并校验 sha256/commit
安装第三方插件 → 无界面启动 gimp-console 刷新并检查 pluginrc → 输出汇总表（失败时退出码 1）。
不会结束正在运行的 GIMP（从不使用 `pkill -f`）；系统级步骤（G'MIC .deb、Resynthesizer 编译安装）需要 sudo。下载缓存：`~/.cache/gimp-retouch-bundle`。

Windows：`powershell -ExecutionPolicy Bypass -File install.ps1 [-Gimp 3.0|3.2|all] [-Only ours] [-Reinstall] [-DryRun]`
（**未测试**；只自动安装本仓库插件，第三方插件按输出的固定版本手动安装）。

### 组件清单（详见 `bundle.lock`）
| 组件 | GIMP 3.0 (apt) | GIMP 3.2 (Flatpak) | 来源 | 许可 |
|---|---|---|---|---|
| fsep_oneclick / dnb_setup / batch_export | 本仓库 | 本仓库 | — | MIT |
| G'MIC-Qt | 4.0.5 .deb (sha256 固定) | Flathub 扩展 4.0.5 (commit 15f4bea) + `gmic_qt_icu77` 包装 (ICU 77 来自 org.freedesktop.Platform 25.08, commit d27f7a6) | gmic.eu / Flathub | CeCILL-2.1 / GPL-3.0 |
| Resynthesizer | v3.0 源码编译 (commit 3846f79；**不要用 v3.0.1**) | Flathub 扩展 3.0.1 (commit f14825c) | github.com/bootchk/resynthesizer | GPL-3.0 |
| Batcher | 1.2.10 zip (sha256) | 1.2.10 zip (sha256) | github.com/kamilburda/batcher | BSD-3-Clause |
| adjustment-layer | commit cc07757 (文件 sha256) | 同左 | github.com/bunnywaffle/adjustment-layer | GPL-3.0 |
| RawTherapee（可选，`--with-raw`） | apt 5.11-2+b2（主机级，供 raw2tiff 使用） | 不使用 Flathub 版；3.2 通过 raw2tiff 生成的 TIFF 处理 | Debian trixie | GPL-3.0 |
| PhotoGIMP（可选） | commit eca3a8f | 同左 | github.com/Diolinux/PhotoGIMP | GPL-3.0 |
| Chuck Henrich FS v3 / D&B v3 | 不包含（站点 TLS 握手失败，无法固定校验和），需手动安装 | 同左 | chuckhenrich.com | — |

## 手动安装
把插件文件夹复制到 GIMP 插件目录（文件夹名与 .py 同名，Linux 需 `chmod +x`），重启 GIMP：
- Linux: `~/.config/GIMP/3.0/plug-ins/` 或 `~/.config/GIMP/3.2/plug-ins/`
- Windows: `%APPDATA%\GIMP\3.0\plug-ins\` 或 `%APPDATA%\GIMP\3.2\plug-ins\`

## License
MIT
