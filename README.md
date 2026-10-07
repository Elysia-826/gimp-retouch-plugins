# gimp-retouch-plugins

GIMP 3 (3.0 / 3.2) Python 插件集，跨 Linux / Windows。

## 插件
- `fsep_oneclick` — 一键频率分离（尚未人工验证）
- `dnb_setup` — 一键加深减淡搭建（尚未人工验证），详见 `dnb_setup/README.md`
- `raw_to_tiff/raw2tiff.sh` — RAW→16 位 TIFF 批量转换（RawTherapee CLI，尚未人工验证），RAW → raw2tiff → batch_export 流程见 `raw_to_tiff/README.md`
- `batch_export` — 批量导出（尚未人工验证），支持命令行无界面调用，详见 `batch_export/README.md`

## 可选安装 / 一键重装（尚未人工验证）
Linux（GIMP 3.0 apt + GIMP 3.2 Flatpak --user）。逻辑在 `installer/bundle.py`（`install.sh` 只是入口，需要 python3）；
数据全部来自 `components.txt`（组件）、`bundle.lock`（固定版本的构建）、`presets/*.txt`（预设），脚本里不写死组件名。

```bash
./install.sh --list                                   # 离线列出组件和预设
./install.sh --check-catalog                          # 校验 components.txt / bundle.lock / presets 一致、sha/commit 与许可证齐全
./install.sh --preset portrait --gimp all --dry-run   # 预览：列出每个动作（标出需要 sudo 的），不做任何改动
./install.sh --preset portrait --gimp all --yes       # 无人值守安装
./install.sh --preset minimal --add gmic --remove dnb_setup --gimp 3.2 --yes
./install.sh --config my.toml --yes                   # 用配置文件选择
./install.sh --status --json                          # 每个组件、每个 GIMP：installed / version / registered / matches_lock
```
预设：
| 预设 | 组件 | 说明 |
|---|---|---|
| `minimal` | fsep_oneclick, dnb_setup | 不需要 sudo |
| `portrait` | minimal + resynthesizer, adjustment-layer, batch_export | 人像修图常用 |
| `full` | 除 photogimp 外全部 | 不选任何预设/组件时的默认值 |

选择规则：
- 预设加上 `--add`、减去 `--remove`。`--with-raw` 等于 `--add raw2tiff`，`--with-photogimp` 等于 `--add photogimp`。
- `--only ours|third-party|community|all` 按类别过滤。
- requires 会自动加入（raw2tiff → rawtherapee）；recommends 只提示（fsep_oneclick → resynthesizer，raw2tiff → batch_export）。batcher 与 batch_export 功能部分重叠，只提示。
- 当前 GIMP/系统不支持的组件会注明原因跳过，不算失败。

配置文件（TOML 子集，正则解析，只支持以下键）：
```toml
gimp = "3.2"            # 3.0 | 3.2 | all
preset = "portrait"
add = ["gmic"]
remove = ["adjustment-layer"]
photogimp = false
```
命令行参数会覆盖配置文件。安装全部成功后，实际生效的选择保存到 `~/.local/share/gimp-retouch-bundle/last.toml`。

无人值守行为：
- `--yes` 不再提问。没有 `--yes` 且不在终端里时退出码 64（`--dry-run`/`--list`/`--status` 不受影响）。
- 3.0 和 3.2 都已安装但没指定 `--gimp`（或配置里的 `gimp`）时：无人值守报错 64，交互模式会询问。
- 需要 sudo 的步骤会先全部列出，只确认一次。`--yes` 且没有免密 sudo 时，这些步骤记为失败，其余步骤照常进行。
- 退出码：0 成功、1 部分失败、2 失败、64 用法错误。最后一行总是 `STATUS=ok|partial|failed installed=N skipped=N failed=N`。`--json` 输出机器可读结果。
- 幂等：已符合 lock 的组件直接跳过。
- 改动前备份将被修改的 GIMP 配置到 `~/gimp-bundle-backups/`。备份按内容去重：内容完全相同就复用旧备份。
- 不会结束正在运行的 GIMP。只有确实安装了东西的 GIMP 版本，才会用 gimp-console 刷新并检查 pluginrc。

安装记录 `~/.local/share/gimp-retouch-bundle/installed.json` 按组件、按 GIMP 版本记录：构建 id、版本/pin、放置的文件，以及系统级安装方式（deb 包名、meson install-log 文件清单、apt 包）。
首次运行会把已经装好的组件（通过同样的检查）“收编”进记录（`adopted: true`）。卸载/恢复、交互菜单、Windows 改进属于后续阶段，尚未实现。

`raw2tiff` 安装为 `~/.local/bin/raw2tiff`（主机级，与 GIMP 版本无关；该目录需在 PATH 中）。
PhotoGIMP 只在显式选择时安装，会覆盖配置。它从压缩包中优先取 `.config/GIMP/<版本>`；上游目前只有 `.config/GIMP/3.0`，所以 3.2 会回退使用它，`--dry-run` 会显示实际选用的目录。

Windows：`powershell -ExecutionPolicy Bypass -File install.ps1 [-Gimp 3.0|3.2|all] [-Only ours] [-Reinstall] [-DryRun]`
（**未测试**；只自动安装本仓库插件，第三方插件按输出的固定版本手动安装）。

### 组件（`components.txt`，`./install.sh --list`）
| 组件 | 类别 | requires / recommends | 说明 |
|---|---|---|---|
| fsep_oneclick | ours | – / resynthesizer | 一键频率分离 |
| dnb_setup | ours | – | 一键加深减淡搭建 |
| batch_export | ours | – | 批量导出，可命令行调用（与 batcher 部分重叠） |
| raw2tiff | ours | rawtherapee / batch_export | RAW→16 位 TIFF，`~/.local/bin/raw2tiff` |
| gmic | third-party | – | G'MIC-Qt |
| resynthesizer | third-party | – | 修复选区/纹理合成 |
| batcher | third-party | – | 批量编辑/导出（与 batch_export 部分重叠） |
| adjustment-layer | community | – | 非破坏调整层 |
| photogimp | community | – | 类 PS 界面配置（覆盖配置，需显式选择） |
| rawtherapee | third-party | – | RawTherapee 5.11（apt，主机级） |

### 构建与固定版本（`bundle.lock`）
| 组件 | GIMP 3.0 (apt) | GIMP 3.2 (Flatpak) | 来源 | 许可 |
|---|---|---|---|---|
| fsep_oneclick / dnb_setup / batch_export | 本仓库 | 本仓库 | — | MIT |
| G'MIC-Qt | 4.0.5 .deb (sha256 固定) | Flathub 扩展 4.0.5 (commit 15f4bea) + `gmic_qt_icu77` 包装 (ICU 77 来自 org.freedesktop.Platform 25.08, commit d27f7a6) | gmic.eu / Flathub | CeCILL-2.1 / GPL-3.0 |
| Resynthesizer | v3.0 源码编译 (commit 3846f79；**不要用 v3.0.1**) | Flathub 扩展 3.0.1 (commit f14825c) | github.com/bootchk/resynthesizer | GPL-3.0 |
| Batcher | 1.2.10 zip (sha256) | 1.2.10 zip (sha256) | github.com/kamilburda/batcher | BSD-3-Clause |
| adjustment-layer | commit cc07757 (文件 sha256) | 同左 | github.com/bunnywaffle/adjustment-layer | GPL-3.0 |
| RawTherapee（`--add rawtherapee` / raw2tiff 依赖） | apt 5.11-2+b2（主机级，供 raw2tiff 使用） | 不使用 Flathub 版；3.2 通过 raw2tiff 生成的 TIFF 处理 | Debian trixie | GPL-3.0 |
| PhotoGIMP（可选） | commit eca3a8f | 同左 | github.com/Diolinux/PhotoGIMP | GPL-3.0 |
| Chuck Henrich FS v3 / D&B v3 | 不包含（站点 TLS 握手失败，无法固定校验和），需手动安装 | 同左 | chuckhenrich.com | — |

## 手动安装
把插件文件夹复制到 GIMP 插件目录（文件夹名与 .py 同名，Linux 需 `chmod +x`），重启 GIMP：
- Linux: `~/.config/GIMP/3.0/plug-ins/` 或 `~/.config/GIMP/3.2/plug-ins/`
- Windows: `%APPDATA%\GIMP\3.0\plug-ins\` 或 `%APPDATA%\GIMP\3.2\plug-ins\`

## License
MIT
