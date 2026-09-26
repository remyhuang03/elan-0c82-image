# ELAN 04f3:0c82 多帧采集研究记录

## 现成实现的适用范围

[depau/elanpoc](https://github.com/depau/elanpoc) 提供 `00 0c` 尺寸查询和 `00 09` 原始图像采集命令。它支持其他 ELAN 型号，尚未将 04f3:0c82 列入设备表。本机验证了这两条命令，并在 Python CLI 中只开放探测与图像采集。

[libfprint 的 `elan.c`](https://gitlab.freedesktop.org/libfprint/libfprint/-/raw/master/libfprint/drivers/elan.c) 与 [`fpi-assembling.c`](https://gitlab.freedesktop.org/libfprint/libfprint/-/raw/master/libfprint/fpi-assembling.c) 已实现小传感器的连续滑动采集与帧拼接。它们面向图像型 ELAN 驱动，要求相邻帧重叠，并假设运动主要沿一个方向。本机的 04f3:0c82 归入 `elanmoc` 驱动，无法直接调用上述图像采集接口。当前 CLI 使用已验证的原始命令采集，再调用 OpenCV 做图块配准。

[NIST Fingerprint Registration Library](https://github.com/usnistgov/NFRL) 需要用户给出两对对应控制点。它能配准两张指纹图，但不负责从 USB 连续采集和自动寻找控制点。[FpReconstruction](https://github.com/XiongjunGuan/FpReconstruction) 是 MATLAB 研究原型，公开版本还缺部分依赖。它会重建稠密纹路；本仓库只导出传感器实际扫描到的像素。

本机还用 OpenCV `Stitcher` 的 `PANORAMA` 和 `SCANS` 模式测试了 5 张 80 × 80 的真实图块。两种模式都返回状态码 `1`，未生成拼接图。因此 CLI 使用 OpenCV 提供的 SIFT、RANSAC 和模板匹配函数，另加针对小图块的重叠检查。

## 本机实测

设备通过 USB 报告 80 × 80 像素。单张按指采集成功，灰度图可见纹路。

一次连续平移采集得到 43 张不同帧。帧分成数段，各段内部运动很小。段与段之间失去接触，没有可靠重叠，因此未生成扩大的图像。

一次缓慢滚动采集得到 100 张不同帧。最初采用较宽松的平移匹配，连接 9 张图块，得到 111 × 245 像素图像。其中连接第 12 帧与第 65 帧的候选只有 `0.529` 的相关系数，没有 SIFT 内点。这处连接缺乏证据，不能作为真实指纹结果。

提高平移匹配门槛后，5 张图块通过配准，得到 93 × 169 像素的保守结果。其中 4 次连接有 17～33 个 SIFT 内点。图像纹路连续，但仍有透明的未扫描区域。CLI 会拒绝证据不足的连接，并显示已扫描区域与输出尺寸。

随后运行 `full` 做三轮实测，每轮最多采集 100 张候选帧。第 1 轮滚动有 34 张图块通过配准，生成 141 × 581 像素的图像；其中 55,118 个像素有实测数据，占外接矩形的 67.3%。预览显示较长的纹路带，但两侧仍有未扫描区域。第 2 轮沿指尖到指根方向移动、第 3 轮回到起始位置小幅滚动，各采得 100 张候选帧，却都没有图块能可靠接入第 1 轮的拼接图。这次图像不能认定为完整指腹，也不能把外接矩形的覆盖比例当作指腹覆盖率。第 4 轮未执行，结果仅保存在本机。

这些测试使用用户本机手指。仓库只记录尺寸、帧数和匹配指标；不包含真实指纹图像。
