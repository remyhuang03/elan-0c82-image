# ELAN 04f3:0c82 指纹图像采集实验

这个仓库从 ELAN 04f3:0c82 指纹传感器读取图像，并保存为 PNG。设备属于 Match-on-Chip 类型。常规的 libfprint 接口只提供录入和匹配功能，但相近型号的协议研究发现了图像采集命令。

当前结论：本机 04f3:0c82 的 USB 接口具有所需端点。尺寸查询返回 **80 × 80 像素**。按住传感器时，采集命令成功返回一帧图像，保存的 PNG 能看到指纹纹路。未放手指时，返回帧的像素值全相同。

## 运行

需要 Linux、Python 3.11 或更新版本，以及 [uv](https://docs.astral.sh/uv/)。下列命令在仓库根目录执行。

```bash
uv sync
sudo .venv/bin/elan0c82 probe
sudo .venv/bin/elan0c82 capture finger.png
sudo .venv/bin/elan0c82 full finger-full.png --passes 4
sudo .venv/bin/elan0c82 mosaic finger-mosaic.png
```

`capture` 会提示你按住传感器，再按 Enter。程序读取一帧、归一化到 8 位灰度，并把 PNG 保存到指定路径。已有文件不会被覆盖。图片权限为 `0600`；通过 `sudo` 运行时，程序会把图片所有权交还给调用者。请勿把真实指纹图片提交到仓库。

`full` 是连续采集入口。每轮按 Enter 后，保持同一根手指接触传感器，缓慢滚动或滑动。结束这一轮时抬起手指。程序会保存采集到的图块，匹配相邻图块，并更新输出 PNG。下一轮可从已扫描区域附近开始，朝尚未覆盖的一侧移动。默认最多 4 轮；在下一轮提示处输入 `q` 可提前结束。

需要分析失败帧时，可加 `--keep-frames /path/to/private-frames`。目录和帧文件只对当前用户开放。帧文件是敏感的生物特征数据，请保存在本机。

`mosaic` 用于采集一根手指的较大区域。先按住指腹中间，按 Enter 采集第一张。之后每次把**同一根手指**平移一点，保持相邻图块至少一半重叠，再按 Enter。可沿指腹上下、左右移动，逐步覆盖边缘。输入 `q` 结束，输入 `u` 撤销最近一张。程序在每次接受图块后更新输出 PNG，你可以同时用图片查看器观察结果。匹配失败时，请移回上一位置，缩小移动幅度，保持相近压力后重试。

拼接图的透明像素表示没有扫描到的数据。程序不会补画这些区域，也无法判断指腹是否已被完整覆盖。你需要根据预览检查覆盖范围。`full` 每轮结束后更新 PNG；`mosaic` 每次接受图块后更新 PNG。

如果系统已有程序占用设备，请先关闭那个程序。`probe` 或 `capture` 若报权限错误，需要以 root 运行。采集失败时，程序会报告 USB 错误、图像长度异常或像素全相同等情况。

## 协议依据

本机通过 `lsusb` 识别到 `04f3:0c82`。USB 接口 0 暴露了 Bulk OUT `0x01`、Bulk IN `0x82` 和 Bulk IN `0x83`。上游 [libfprint 的 elanmoc 驱动](https://gitlab.freedesktop.org/libfprint/libfprint/-/raw/master/libfprint/drivers/elanmoc/elanmoc.c) 将 `0x0c82` 与 `0x0c7e` 放在同一驱动的设备表中。

[depau/elanpoc](https://github.com/depau/elanpoc) 针对其他 ELAN MOC 型号实现了图像导出。本工具仅采用其中两条命令：

| 命令 | 写入端点 | 读取端点 | 用途 |
| --- | --- | --- | --- |
| `00 0c` | `0x01` | `0x83` | 查询图像宽高，返回 4 字节 |
| `00 09` | `0x01` | `0x82` | 读取一帧，每像素 16 位小端序 |

`00 0c` 已在本机返回 `80 × 80`。`00 09` 在按住手指时返回可见纹路，在未放手指时返回像素值全相同的帧。程序没有录入、删除、重置、固件写入或任意命令接口。

拼接使用 OpenCV 的 SIFT 特征匹配、RANSAC 位姿估计和模板匹配，并检查重叠区域的相关性。只有能与已接受图块可靠对齐的新图块才会加入。相邻小图块需要足够重叠；皮肤受压变形也会影响拼接精度。[小面积指纹拼接研究](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/iet-ipr.2018.5972) 同样指出了这些限制。现成方案的适用范围与实测记录见 [研究记录](docs/research.md)。

## 验证范围

运行 `uv run python -m unittest discover -s tests -v` 可检查尺寸解码、像素转换、异常长度处理和合成纹路的平移拼接。本机实测已完成尺寸查询、空载采集、单张按指采集和多帧滚动采集。一次三轮 `full` 测试在首轮连接了 34 张真实图块，输出 141 × 581 像素图像；后两轮未能可靠连接，不能认定为完整指腹。具体结果见[研究记录](docs/research.md)。真实指纹图片只保存在本机，不纳入仓库。

## 致谢与许可

图像命令与返回格式参考 [depau/elanpoc](https://github.com/depau/elanpoc)，其许可为 MIT。本仓库代码按 MIT 许可发布。
