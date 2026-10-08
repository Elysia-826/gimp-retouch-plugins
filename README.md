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
./install.sh --uninstall fsep_oneclick --gimp 3.2 --yes   # 卸载（只删安装记录里的文件，先备份）
./install.sh --uninstall gmic --gimp all --purge --dry-run
./install.sh --list-backups                           # 列出 ~/gimp-bundle-backups/ 里的备份
./install.sh --restore ~/gimp-bundle-backups/gimp-3.2-config-….tgz --gimp 3.2 --yes
```
**必须选择**：不给 `--preset`/`--add`/`--config`（或 `--with-*`）时不会默认装 `full`。
在终端里交互运行会打开下面的选择菜单；`--yes` 或非终端时直接退出 64 并提示怎么选。

### 交互菜单（终端里不带选择运行，或加 `--menu`）
```bash
./install.sh                                  # 没有任何选择 -> 菜单
./install.sh --menu --preset portrait         # 已有选择也强制打开菜单，菜单里预选这些
./install.sh --dry-run                        # 菜单选完只预览
```
1. **预设**（单选）：minimal / portrait / full，`last`（上次成功的 `last.toml`，存在时为默认），`given`（命令行/`--config` 给定的选择，用 `--menu` 时为默认），`custom`（从空白开始）。
2. **组件**（多选）：按上一步预勾选，显示 `components.txt` 的中文说明、类别、requires、是否覆盖配置。
3. **GIMP**：两个版本都在时选 3.0 / 3.2 / all（默认取命令行、上次或 all）。
4. 选择先写入 `~/.local/share/gimp-retouch-bundle/menu-selection.toml` 并打印出来，然后**按这个文件执行**（以后可用 `./install.sh --config <该文件>` 无人值守重放）。
5. 确认前列出：动作数、所有 sudo 步骤、自动补上的 requires、recommends 提示、功能重叠提示。取消 = 退出 64，不做任何改动。

有 `whiptail` 时用 whiptail 对话框（空格勾选、回车确认、Esc 取消）；没有就退回编号文本提示（输入编号或 id 切换勾选，可多个，`all`/`none`，直接回车完成）。
`BUNDLE_MENU=text` 可强制文本模式。`--yes`、非终端、或与 `--status/--list/--uninstall/--restore` 同用时 `--menu` 报错 64，绝不会在无人值守时弹出。
测试/隔离用：环境变量 `GIMP_BUNDLE_STATE=<目录>` 改变状态目录（installed.json、last.toml、menu-selection.toml）。
预设：
| 预设 | 组件 | 说明 |
|---|---|---|
| `minimal` | fsep_oneclick, dnb_setup | 不需要 sudo |
| `portrait` | minimal + resynthesizer, adjustment-layer, batch_export | 人像修图常用 |
| `full` | 除 photogimp 外全部 | 需显式选择（不再是默认值） |

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
首次运行会把已经装好的组件（通过同样的检查）“收编”进记录（`adopted: true`）。Windows 改进属于后续阶段，尚未实现。

### 卸载 `--uninstall ID[,ID] [--gimp 3.0|3.2|all] [--force] [--purge] [--dry-run] [--yes] [--json]`
- 只删除 `installed.json` 里记录的、属于该组件和该 GIMP 版本的文件；删除前打包备份到 `~/gimp-bundle-backups/uninstall-<组件>-<版本>-<时间>.tgz`；成功后更新记录。不在记录里的组件不处理（提示“nothing to remove”）。
- 组件在 3.0 和 3.2 都有记录而没给 `--gimp`：交互模式询问，无人值守退出 64。主机级组件（raw2tiff、rawtherapee）不需要 `--gimp`。
- 如果另一个已安装组件 **requires** 它（例如装着 raw2tiff 时卸 rawtherapee），默认拒绝（记为失败），`--force` 可强制；**recommends** 只警告（例如卸 resynthesizer 会提示 fsep_oneclick 的修复选区步骤不可用）。
- 各安装方式的处理：
  | 方式 | 默认 | 说明 |
  |---|---|---|
  | 复制的文件 / zip / 生成的包装（ours、batcher、adjustment-layer、raw2tiff、gmic_qt_icu77） | 删除 | 先备份；空目录与 `__pycache__` 一并清理 |
  | meson install-log（3.0 自编译 Resynthesizer） | 删除 | 按记录的 install-log 清单 `sudo rm`；sudo 步骤预先列出 |
  | deb / apt（3.0 G'MIC-Qt .deb、rawtherapee） | **保留** | 只有 `--purge` 才 `sudo apt-get remove` |
  | Flatpak 扩展（3.2 G'MIC、Resynthesizer） | 删除 | `flatpak uninstall --user`，属于用户级 |
  | 共享运行时（`org.freedesktop.Platform 25.08`，lock 里 `shared=1`） | **保留** | 只有 `--purge` 才卸载（其他应用可能在用） |
  | PhotoGIMP（config-overlay） | 还原 | 用安装时的专用备份把整个配置目录**精确还原**（还原前的状态另存备份） |
- 支持 `--dry-run`、`--json`、退出码（0/1/2/64）与最后一行 `STATUS=… installed=0 skipped=N failed=N removed=N`。删除后刷新对应 GIMP 的 pluginrc 并确认已注销。

### 备份与恢复
- `--list-backups [--json]`：列出备份及类型（profile 配置快照 / photogimp-pre-install / uninstalled-files / 旧 install.sh 的双版本快照）、包含的 GIMP 版本、大小、时间。
- `--restore 备份.tgz [--gimp 3.0|3.2|all] [--dry-run] [--yes]`：先把当前配置备份（按内容去重），再用备份里的 `.config/GIMP/<版本>` **整体替换**当前配置目录（不是合并）。备份里有两个版本而没给 `--gimp` 时：交互询问，无人值守退出 64。只接受包含 `.config/GIMP/<版本>` 的备份；解包使用 tar 的 `data` 过滤器。GIMP 运行中只警告（退出时可能写回设置），不会结束它。

`raw2tiff` 安装为 `~/.local/bin/raw2tiff`（主机级，与 GIMP 版本无关；该目录需在 PATH 中）。
PhotoGIMP 只在显式选择时安装，会覆盖配置。它从压缩包中优先取 `.config/GIMP/<版本>`；上游目前只有 `.config/GIMP/3.0`，所以 3.2 会回退使用它，`--dry-run` 会显示实际选用的目录。
安装前会另做一份**专用完整备份**（`photogimp-pre-<版本>-<时间>.tgz`，不去重，路径写入安装记录）。覆盖后会把你原 `gimprc` 里的这些单行设置写回：
`language`（PhotoGIMP 自带 `(language "")` 会把中文界面改回系统语言）、`theme`、`icon-theme`、`prefer-dark-theme`、`theme-color-scheme`、`font-relative-size`、`override-theme-icon-size`、`custom-icon-size`、`icon-size`、`import-raw-plug-in`（PhotoGIMP 会把 RAW 导入改成占位插件）；
原来没设置的这些键会去掉 PhotoGIMP 的值（回到 GIMP 默认）。列表可在 `bundle.lock` 的 params 里用 `preserve=` 覆盖。`--uninstall photogimp --gimp <版本>` 用专用备份精确还原整个配置目录——安装 PhotoGIMP 之后对该配置做的其他改动也会被还原（还原前状态另有备份）。

Windows（自选组件，和 Linux 一样不会一键全装）：
```
powershell -ExecutionPolicy Bypass -File install.ps1 -List
powershell -ExecutionPolicy Bypass -File install.ps1 -Components fsep_oneclick,gmic,resynthesizer -Gimp 3.2 -BackupDir D:\gimp-bundle-backups [-CacheDir <目录>] [-Reinstall] [-DryRun]
```
- 可选组件：`fsep_oneclick` `dnb_setup` `batch_export`（本仓库）、`gmic` 4.0.5（gmic.eu 官方 GIMP 3.2 版）、`resynthesizer` 3.0.1、`batcher` 1.2.10、`adjustment-layer` cc07757、`photogimp` eca3a8f（必须写明才会装）。`-Only ours|third-party|all` 是快捷组合，不含 photogimp。
- 全部装进 `%APPDATA%\GIMP\<版本>\`，不需要管理员权限。下载文件都按 sha256 校验；`-CacheDir` 里已有且校验通过的文件不会重新下载。GitHub 连不上时，可以自己把文件下载到这个目录再运行。
- **resynthesizer 在 Windows 上用的是社区编译版**（ravik453/resynthesizer-windows-build），官方没有 Windows 版。其中的 .scm 与官方 v3.0.1 一致，只有 resynthesizer.exe 是第三方编译的。G'MIC 和 resynthesizer 只提供 GIMP 3.2 版。
- photogimp 会覆盖布局、快捷键和工具预设。gimprc 里的语言、主题、图标、RAW 导入设置会保留（规则与 Linux 相同）。安装前会另做一份专用备份 `photogimp-pre-*.zip`。GIMP 正在运行时拒绝安装（退出码 75）。
- 已在 Windows 11 + GIMP 3.2.6 上实测安装和无界面注册/运行，插件对话框尚未人工验证。目前还没有卸载功能，要还原请用备份 zip。
- `-Gimp all` 只装到已有配置目录的版本；刚装好、还没启动过的 GIMP 请写明 `-Gimp 3.2`。

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
