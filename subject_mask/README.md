# 选出主体 / Select Subject

（尚未人工验证）

滤镜 → 修图工具 → 选出主体。（装了人像面板时，菜单里不再单独显示，在人像面板的「选择主体」里。）对当前图层做选区，不改像素。一次操作是一步撤销。

两种模式：

- **主体**：把人从背景里圈出来，边缘羽化大约 2 像素，不是硬切。优先用本目录自带的 `seg_mnv3s.onnx`（MobileNetV3-Small + LR-ASPP，三类 background / sky / person）出整个人的掩码；模型缺失或结果不可用时，再回退到认脸 GrabCut，或（没认到脸、背景较平）按边框颜色分离。
- **皮肤**：只圈脸部皮肤，给加深减淡和修复用，不用手涂。头发不进。认到眼睛和嘴时会把它们挖掉。羽化最多 1 像素，免得眼睛又被糊上。仍只用 mesh_liquify 自带的 YuNet 认脸模型，不绑分割网。

通道面板里会留下隐藏通道「主体选区」或「皮肤选区」，照片上看不到。选区本身已经设好。

## 做不到的

这不是发丝抠图。碎发只是从轮廓往外扩大约十来个像素的深色，而且要挨着已经选中的头发。逆光、头发贴在亮窗户上时，那一侧头发仍会被切掉。复杂背景、没认到脸时也可能分不出来，这时画面不动。皮肤蒙版跟着脸颊颜色，强光和深阴影处会有缺口，鼻子两侧的暗部尽量补上了，但不保证每一块皮肤都在里面。

在一键频率分离或一键加深减淡搭建生成的图层上运行时，会先换成它们下面的原照片图层再算（按这两个插件建的组名 Frequency Separation / Dodge & Burn 判断）。


## 分割权重与训练数据署名

主体模式自带的 `seg_mnv3s.onnx` 随插件分发。训练数据与许可：

- VideoMatte240K — MIT，Background Matting V2，https://github.com/PeterL1n/BackgroundMattingV2
- SkyFinder — Mihail et al.，CC-BY-4.0，https://doi.org/10.5281/zenodo.5884485

插件本身仍是 MIT。权重也可按 MIT 使用，但分发或改用时须保留上述数据署名。未混入 CelebAMask-HQ 等仅研究 / NC 数据。

## 运行环境

OpenCV 在插件外面的一个 Python 里跑（`subject_select.py`）。Linux 用本机的 `python3`（要装 OpenCV）。Windows 上 GIMP 自带的 Python 装不了 OpenCV，用 `install.ps1` 的 `helper-python` 组件装一个独立的（选 subject_mask 会自动带上）。插件先看环境变量 `RETOUCH_HELPER_PYTHON`，再看 GIMP 配置目录里的 `retouch-helper-python.txt`，再找常见位置。
