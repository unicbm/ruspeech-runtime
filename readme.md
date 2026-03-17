# Ruspeech Runtime

本仓库现在是一个面向 Windows 的本地语音工具原型，重点是两件事：
- 俄语麦克风实时输入
- 系统音频实时字幕

它最初来自 `vocotype-cli` 的工程骨架，但当前代码路径已经不再等同于原项目的 FunASR 中英输入法定位。现阶段的默认架构是：
- `AudioSource`: 麦克风 / WASAPI loopback
- `ASRBackend`: 默认 `sherpa-onnx`
- `OutputSink`: 直接上屏 / 控制台字幕 / 浮窗字幕

## 仓库地址

当前项目仓库：

```text
https://github.com/unicbm/ruspeech-runtime
```

如果你本地目录还叫 `vocotype-cli`，那只是迁移过程中的旧目录名，不代表项目正式名称。

## 当前能力

- `dictation` 模式：麦克风语音转文本，最终文本直接输入到当前窗口
- `subtitles` 模式：抓系统播放音频，输出实时字幕
- 输入源：
  - `microphone`
  - `loopback`
- 热键交互：
  - `toggle`
  - `push-to-talk`
- 输出端：
  - `type_text`
  - `console_subtitles`
  - `overlay_subtitles`

## 当前状态

这是一个正在重构中的开发者仓库，不是完整打包发布版。

已经完成：
- 新的流式运行时骨架
- 配置迁移层
- `sherpa-onnx` 默认后端接入
- Windows 文本注入输出
- 控制台字幕和 Tk 浮窗字幕

还没完成或还不稳定：
- `Vosk` / `Qwen3-ASR` 后端实现
- 自动下载和管理 sherpa 模型
- 更成熟的字幕 UI
- 更细的 loopback 设备/进程选择

## 目录结构

主要的新运行时文件：

```text
main.py
app/
  audio_sources.py
  asr_backends.py
  controller.py
  output_sinks.py
  runtime_types.py
  config.py
  hotkeys.py
```

仓库里仍保留了一部分旧的 FunASR 代码，当前默认启动路径不会使用它们。

## 依赖

推荐：
- Python 3.12
- Windows 10/11

运行时依赖见 `requirements.txt`，当前默认链路会用到：
- `numpy`
- `keyboard`
- `sounddevice`
- `soundcard`
- `sherpa-onnx`

旧 FunASR 兼容依赖被拆到了：

```text
requirements-legacy-funasr.txt
```

安装：

```bash
git clone https://github.com/unicbm/ruspeech-runtime.git
cd ruspeech-runtime
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

如果你不想手动装环境，可以直接双击：

```text
setup_runtime.bat
```

## 模型准备

默认后端是 `sherpa-onnx`，配置默认指向：

```text
models/sherpa-onnx-ru-streaming
```

当前默认使用官方俄语 streaming 模型 `sherpa-onnx-streaming-t-one-russian-2025-09-08`。

如果你已经运行过：

```text
setup_runtime.bat
```

模型会自动下载到默认目录，不需要手动处理。

## 启动

默认启动：

```bash
python main.py
```

双击启动：

```text
run_dictation.bat
```

切换模式或输入源：

```bash
python main.py --mode subtitles --source loopback
python main.py --mode dictation --source microphone
```

双击字幕模式：

```text
run_subtitles.bat
```

## EXE 打包

仓库里已经提供了打包脚本：

```text
build_exe.bat
```

运行后会生成：

```text
dist\RuspeechRuntime\RuspeechRuntime.exe
```

这个 one-folder 包会把默认俄语模型一起带进 `dist` 目录。

覆盖后端：

```bash
python main.py --backend sherpa-onnx
```

调试单次采集：

```bash
python main.py --once
```

保存最近一次音频和结果数据集：

```bash
python main.py --save-dataset --dataset-dir dataset
```

## 配置

配置文件仍是 JSON。当前默认配置大致如下：

```json
{
  "mode": "dictation",
  "source": {
    "type": "microphone",
    "device": null,
    "sample_rate": 8000,
    "channels": 1,
    "frame_ms": 20
  },
  "hotkeys": {
    "mode": "toggle",
    "toggle": "f2",
    "push_to_talk": "f4"
  },
  "asr": {
    "backend": "sherpa-onnx",
    "language": "ru"
  },
  "output": {
    "sinks": ["type_text"]
  }
}
```

字幕模式常见配置：

```json
{
  "mode": "subtitles",
  "source": {
    "type": "loopback",
    "sample_rate": 8000,
    "channels": 2,
    "frame_ms": 20
  },
  "output": {
    "sinks": ["console_subtitles", "overlay_subtitles"]
  }
}
```

兼容性说明：
- 旧版 `audio.sample_rate` / `audio.block_ms` 配置会自动迁移到新 `source` 结构
- 旧配置默认仍按麦克风输入法处理

## 热键行为

`toggle`：
- 按一次开始
- 再按一次结束

`push-to-talk`：
- 按下组合键开始采集
- 松开任一组成键结束并提交 final 结果

## 测试

当前已添加基础单元测试：

```bash
python -m unittest discover -s tests -v
```

语法检查：

```bash
python -m compileall main.py app tests
```

## 后续建议

如果你准备把它作为独立项目继续做，下一步最值得补的是：
- 在 GitHub 上重命名仓库
- 清理或归档旧 FunASR 路径
- 增加 sherpa 模型下载与校验
- 增加示例配置文件
- 增加真实设备 smoke test 文档

## 致谢

本仓库当前主要借鉴或依赖这些项目：
- `sherpa-onnx`
- `sounddevice`
- `soundcard`
- `keyboard`

历史上它也继承了原 `vocotype-cli` 的交互骨架思路，但当前功能定位已经不同。
