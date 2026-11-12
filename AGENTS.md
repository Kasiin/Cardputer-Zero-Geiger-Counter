# Cardputer Zero Geiger Counter

本项目是 Cardputer Zero 原厂 Linux APPLaunch 的盖格计数器。

- `geiger.py` 负责计数、显示、键盘输入和预览。
- `linux_devices.py` 封装 Linux GPIO 字符设备、framebuffer 和 evdev。
- `build_deb.py` 和 `packaging/` 负责本地 Debian 打包。
- `tests/` 保存计数和 Linux 接口的回归验证。验证入口为 `python -m unittest discover -s tests`。
- 接线和安装见 [README.md](README.md)，项目状态见 [ROADMAP.md](ROADMAP.md)。
- 脉冲输入使用 BCM GPIO22。G3 接有板载 I²C 设备，程序不能申请该引脚。读 GPIO 只申请输入，不切换系统引脚复用或电源。
