# ELAN 04f3:0c82 指纹图像采集实验

这个仓库尝试从 ELAN 04f3:0c82 指纹传感器读取图像，并保存为 PNG。设备属于 Match-on-Chip 类型。常规的 libfprint 接口只提供录入和匹配功能，但相近型号的协议研究发现了图像采集命令。

当前结论：本机 04f3:0c82 的 USB 接口具有所需端点。尺寸查询返回 **80 × 80 像素**。按住传感器时，采集命令成功返回一帧图像，保存的 PNG 能看到指纹纹路。未放手指时，返回帧的像素值全相同。

## 运行

需要 Linux、Python 3.11 或更新版本，以及 [uv](https://docs.astral.sh/uv/)。下列命令在仓库根目录执行。

```bash
uv sync
sudo .venv/bin/python elan0c82.py probe
sudo .venv/bin/python elan0c82.py capture finger.png
```

`capture` 会提示你按住传感器，再按 Enter。程序读取一帧、归一化到 8 位灰度，并把 PNG 保存到指定路径。已有文件不会被覆盖。图片权限为 `0600`；通过 `sudo` 运行时，程序会把图片所有权交还给调用者。请勿把真实指纹图片提交到仓库。

如果系统已有程序占用设备，请先关闭那个程序。`probe` 或 `capture` 若报权限错误，需要以 root 运行。采集失败时，程序会报告 USB 错误、图像长度异常或像素全相同等情况。

## 协议依据

本机通过 `lsusb` 识别到 `04f3:0c82`。USB 接口 0 暴露了 Bulk OUT `0x01`、Bulk IN `0x82` 和 Bulk IN `0x83`。上游 [libfprint 的 elanmoc 驱动](https://gitlab.freedesktop.org/libfprint/libfprint/-/raw/master/libfprint/drivers/elanmoc/elanmoc.c) 将 `0x0c82` 与 `0x0c7e` 放在同一驱动的设备表中。

[depau/elanpoc](https://github.com/depau/elanpoc) 针对其他 ELAN MOC 型号实现了图像导出。本工具仅采用其中两条命令：

| 命令 | 写入端点 | 读取端点 | 用途 |
| --- | --- | --- | --- |
| `00 0c` | `0x01` | `0x83` | 查询图像宽高，返回 4 字节 |
| `00 09` | `0x01` | `0x82` | 读取一帧，每像素 16 位小端序 |

`00 0c` 已在本机返回 `80 × 80`。`00 09` 在按住手指时返回可见纹路，在未放手指时返回像素值全相同的帧。程序没有录入、删除、重置、固件写入或任意命令接口。

## 验证范围

运行 `uv run python -m unittest discover -s tests -v` 可检查尺寸解码、像素转换和异常长度处理。测试使用构造数据。本机实测已完成尺寸查询、空载采集和按指采集。按指采集生成了 80 × 80 的 8 位灰度 PNG；人工查看能辨认纹路。真实指纹图片只保存在本机，不纳入仓库。

## 致谢与许可

图像命令与返回格式参考 [depau/elanpoc](https://github.com/depau/elanpoc)，其许可为 MIT。本仓库代码按 MIT 许可发布。
