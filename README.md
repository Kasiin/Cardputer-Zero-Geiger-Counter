# Cardputer Zero Geiger Counter

用于 M5Stack Cardputer Zero 原厂 Linux APPLaunch 的盖格计数器。在 320×170 LCD 上显示上一完整秒的 CPS、最近 60 秒的 CPM、累计脉冲数和滚动柱状图。首次启动或清零后，CPM 会等待 60 秒完整采样。界面会提示内核事件队列丢失的边沿。

## 配套模块与接线

本 App 配合下图所示的 Cardputer Zero 盖格计数器扩展板使用。模块由顶部扩展口的 5VOUT 供电，并通过 G22 将检测到的脉冲送给 App 计数。

![Cardputer Zero 配套盖格计数器扩展板的 PCB 渲染图](docs/geiger-module.png)

关机后改线。针脚号以 Cardputer Zero 官方 EXT 2.54-14P 图为准。

| 模块 | Cardputer Zero 顶部 EXT |
| --- | --- |
| 电源正极 | 6 脚，5VOUT |
| 电源地和脉冲地 | 4 脚，GND |
| 脉冲输出 | 5 脚，G22 / BCM GPIO22 |

G3（10 脚）是板载键盘、音频编解码器等设备共用的 I²C 时钟。接入 G22 前，用示波器确认模块脉冲符合 3.3 V GPIO 电平，避免将 5 V 脉冲直接接入。5VOUT 默认关闭，开机后在 `Settings > ExtPort` 打开顶部 EXT 的 5 V 输出。

[M5Stack 官方引脚图](https://docs.m5stack.com/en/CardputerZero#ext-254-14p) · [M5Stack 扩展接口使用指南](https://docs.m5stack.com/en/compute/cardputerzero/usage#9-expansion-interfaces) · [Raspberry Pi GPIO 电平](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio)

## 安装和使用

下载 [0.1.0 安装包](dist/cardputer-zero-geiger_0.1.0_all.deb) 并复制到设备。在设备上进入安装包所在目录，再安装。

```sh
sudo apt install ./cardputer-zero-geiger_0.1.0_all.deb
```

回到 APPLaunch，打开 **Geiger Counter**。按 `R` 清零，按 `Esc` 或 `Q` 退出。安装包需要 Python 3 和 Debian 的 `python3-pil`，后者用于绘制字体、数字和趋势图。图形界面使用原厂 APPLaunch 的 Linux framebuffer，键盘使用 evdev。

默认以内部上拉、下降沿计数，沿用 Flipper 参考项目的输入方式。若示波器确认脉冲由低跳高，可在独占 LCD 的调试会话中运行 `cardputer-zero-geiger --edge rising --bias disabled`。在同样的会话里运行 `cardputer-zero-geiger --demo` 可模拟脉冲。如果系统使用不同的 LCD 或键盘路径，可设置 `GEIGER_FB` 或 `LV_LINUX_KEYBOARD_DEVICE`。

应用显示原始计数。剂量率换算需要已确认的管型和校准系数。

[Cardputer Zero 应用模板和本地安装](https://github.com/CardputerZero/Template)

## 致谢

感谢 nmrr 的 Flipper Zero 盖格计数器项目提供参考。本项目借鉴了下降沿计数、CPS、滚动 CPM 和趋势图的设计，Cardputer Zero 版本使用 Python 和 Linux 设备接口独立实现。 [nmrr/flipperzero-geigercounter](https://github.com/nmrr/flipperzero-geigercounter)

## 构建和验证

在 Windows 或 Linux 的项目根目录执行。构建环境需要 Python 3.10+ 和 Pillow 10.1+。

```sh
python -B -m unittest discover -s tests
python -B build_deb.py
```

本地预览可运行 `python -B geiger.py --preview preview.png`，输出 320×170 的模拟界面 PNG。
