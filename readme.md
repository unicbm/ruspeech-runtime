<div align="center">

# Uni Speech Runtime

**A Windows-first local streaming speech runtime for Russian dictation and realtime subtitles.**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows/)
[![Backend](https://img.shields.io/badge/ASR-sherpa--onnx-111111)](https://github.com/k2-fsa/sherpa-onnx)
[![License](https://img.shields.io/github/license/unicbm/uni-speech-runtime)](./LICENSE)

[简体中文](#简体中文) | [English](#english)

</div>

---

<a id="简体中文"></a>
<details open>
<summary><b>简体中文</b></summary>

> `Uni Speech Runtime` 是一个面向 Windows 的本地实时语音运行时，当前主要聚焦多语言本地听写与实时字幕场景：
>
> - 俄语麦克风语音输入
> - 系统音频实时字幕

### 概览

- 本地运行，不依赖在线识别服务
- 默认后端为 `sherpa-onnx`
- 提供最简 Tk GUI 小窗口，支持启动/停止、热键录制和状态提示
- 支持两种工作模式：`dictation` / `subtitles`
- 支持两种输入源：`microphone` / `loopback`
- 支持三种输出方式：`type_text` / `console_subtitles` / `overlay_subtitles`
- 提供一键环境安装、模型下载和 `EXE` 打包脚本

### 功能特性

| 能力 | 说明 |
| --- | --- |
| 实时听写 | 从麦克风采集语音，将最终文本直接输入到当前窗口 |
| 实时字幕 | 抓取系统播放音频并输出控制台字幕或浮窗字幕 |
| 热键控制 | 支持 `toggle` 和 `push-to-talk` 两种交互模式 |
| 本地模型 | 默认使用 `sherpa-onnx-streaming-t-one-russian-2025-09-08` |
| 数据留存 | 可将最近一次音频段落保存到 `logs/recent.wav` |
| 数据集模式 | 支持 `--save-dataset` 保存音频/文本对 |

### 项目定位

这个仓库最初沿用了 `vocotype-cli` 的工程骨架，但当前默认启动路径已经转向新的多语言本地语音运行时架构。  
如果你本地目录仍叫 `vocotype-cli`，这是迁移遗留，不代表项目正式名称。

- 当前仓库地址：`https://github.com/unicbm/uni-speech-runtime`
- 上游历史来源：`https://github.com/233stone/vocotype-cli`

### 架构概念

```text
AudioSource (microphone / loopback)
    -> ASRBackend (sherpa-onnx)
        -> OutputSink (type_text / console_subtitles / overlay_subtitles)
```

主要入口与模块：

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

### 环境要求

- Python `3.12+`
- Windows `10/11`
- 推荐本地可用麦克风或支持 WASAPI loopback 的音频设备

默认运行时依赖见 `requirements.txt`，核心包括：

- `numpy`
- `sounddevice`
- `soundcard`
- `keyboard`
- `pyperclip`
- `sherpa-onnx`

旧的 FunASR 兼容依赖单独放在：

```bash
requirements-legacy-funasr.txt
```

### 快速开始

#### 方式一：自动安装

```powershell
git clone https://github.com/unicbm/uni-speech-runtime.git
cd uni-speech-runtime
.\setup_runtime.bat
```

`setup_runtime.bat` 会执行以下工作：

- 创建 `.venv`
- 安装 `requirements.txt`
- 下载默认俄语 streaming 模型到 `models/sherpa-onnx-ru-streaming`

#### 方式二：手动安装

```powershell
git clone https://github.com/unicbm/uni-speech-runtime.git
cd uni-speech-runtime
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果模型目录不存在，可运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download_russian_model.ps1
```

### 启动方式

#### 听写模式

```powershell
python main.py --mode dictation --source microphone
```

或直接双击：

```text
run_dictation.bat
```

#### 字幕模式

```powershell
python main.py --mode subtitles --source loopback
```

或直接双击：

```text
run_subtitles.bat
```

#### 常用参数

```powershell
python main.py --config .\config.json
python main.py --backend sherpa-onnx
python main.py --backend funasr
python main.py --once
python main.py --save-dataset --dataset-dir .\dataset
```

#### 图形界面

```powershell
python main_gui.py
```

GUI 提供：

- 启动/停止运行时
- 模式和后端切换
- 热键录制时的小提示浮窗
- 最近一次识别结果显示

中文 `funasr` 后端已重新接回主入口，但当前限定为“麦克风听写”，不支持 loopback 字幕。

### 默认行为

| 场景 | 默认热键模式 | 默认热键 | 默认输出 |
| --- | --- | --- | --- |
| `dictation` | `push-to-talk` | `F2` | `type_text` |
| `subtitles` | `toggle` | `F2` | `console_subtitles` + `overlay_subtitles` |

热键说明：

- `toggle`：按一次开始，再按一次结束
- `push-to-talk`：按住热键开始采集，松开后提交最终结果

### 配置示例

默认配置结构如下：

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
    "mode": "auto",
    "toggle": "f2",
    "push_to_talk": "f2"
  },
  "asr": {
    "backend": "sherpa-onnx",
    "language": "ru",
    "provider": "cpu",
    "num_threads": 2,
    "enable_endpoint_detection": true,
    "sherpa": {
      "model_dir": "models/sherpa-onnx-ru-streaming",
      "variant": "t-one-ctc",
      "sample_rate": 8000,
      "feature_dim": 80,
      "decoding_method": "greedy_search"
    }
  },
  "output": {
    "method": "auto",
    "append_newline": false,
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

- 旧版 `audio.sample_rate` / `audio.block_ms` 会自动迁移到新的 `source` 结构
- 保留了部分旧 FunASR 路径，但当前默认运行时不会走这些逻辑
- 当前默认链路要求 `source.sample_rate` 与 `asr.sherpa.sample_rate` 保持一致，默认均为 `8000Hz`

### EXE 打包

项目已内置打包脚本：

```powershell
.\build_exe.bat
```

生成产物：

```text
dist\UniSpeechRuntime\UniSpeechRuntime.exe
dist\UniSpeechRuntime\UniSpeechRuntimeUI.exe
```

这是一个 `one-folder` 打包，默认会把 `models/sherpa-onnx-ru-streaming` 一起带入输出目录。
其中：

- `UniSpeechRuntime.exe` 为 CLI 入口
- `UniSpeechRuntimeUI.exe` 为最简 GUI 入口

### 测试与检查

```powershell
python -m unittest discover -s tests -v
python -m compileall main.py app tests
```

### 当前状态

已完成：

- 新的流式运行时骨架
- `sherpa-onnx` 默认后端接入
- `funasr` 中文听写后端重新接回统一入口
- Windows 文本注入输出
- 控制台字幕与 Tk 浮窗字幕
- 最简 Tk GUI 主控窗与热键录制提示
- 配置迁移层与基础测试

仍在演进：

- `Vosk` / `Qwen3-ASR` 后端尚未实现
- sherpa 模型自动管理仍比较基础
- 字幕 UI 还可以继续优化
- loopback 设备/进程选择还不够细

### 致谢

本项目当前主要基于或参考以下生态：

- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
- [sounddevice](https://python-sounddevice.readthedocs.io/)
- [soundcard](https://github.com/bastibe/SoundCard)
- [keyboard](https://github.com/boppreh/keyboard)

---

<a id="english"></a>
</details>

<details>
<summary><b>English</b></summary>

> `Uni Speech Runtime` is a Windows-first local speech runtime focused on multilingual local dictation and realtime subtitles:
>
> - Russian microphone dictation
> - Realtime subtitles from system audio

### Overview

- Fully local runtime, no online ASR service required
- Default backend: `sherpa-onnx`
- Includes a minimal Tk GUI window with start/stop controls, hotkey capture, and status prompts
- Two runtime modes: `dictation` and `subtitles`
- Two audio sources: `microphone` and `loopback`
- Three output sinks: `type_text`, `console_subtitles`, and `overlay_subtitles`
- Includes setup, model download, and `EXE` packaging scripts

### Highlights

| Feature | Description |
| --- | --- |
| Realtime dictation | Capture microphone audio and type final text into the active window |
| Realtime subtitles | Capture system playback audio and render subtitles in console or overlay |
| Hotkey control | Supports both `toggle` and `push-to-talk` workflows |
| Local model | Uses `sherpa-onnx-streaming-t-one-russian-2025-09-08` by default |
| Session artifacts | Saves the latest captured audio segment to `logs/recent.wav` |
| Dataset mode | Can persist audio/text pairs via `--save-dataset` |

### Project Context

This repository started from the `vocotype-cli` codebase, but the active runtime path has been reshaped into a dedicated Russian streaming runtime.

- Current repo: `https://github.com/unicbm/uni-speech-runtime`
- Historical upstream: `https://github.com/233stone/vocotype-cli`

### Runtime Model

```text
AudioSource (microphone / loopback)
    -> ASRBackend (sherpa-onnx)
        -> OutputSink (type_text / console_subtitles / overlay_subtitles)
```

Main runtime files:

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

### Requirements

- Python `3.12+`
- Windows `10/11`

Core dependencies from `requirements.txt`:

- `numpy`
- `sounddevice`
- `soundcard`
- `keyboard`
- `pyperclip`
- `sherpa-onnx`

Legacy FunASR compatibility dependencies remain in:

```bash
requirements-legacy-funasr.txt
```

### Quick Start

#### Automatic setup

```powershell
git clone https://github.com/unicbm/uni-speech-runtime.git
cd uni-speech-runtime
.\setup_runtime.bat
```

This script will:

- create `.venv`
- install `requirements.txt`
- download the default Russian streaming model into `models/sherpa-onnx-ru-streaming`

#### Manual setup

```powershell
git clone https://github.com/unicbm/uni-speech-runtime.git
cd uni-speech-runtime
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If the model directory is missing:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download_russian_model.ps1
```

### Run

#### Dictation mode

```powershell
python main.py --mode dictation --source microphone
```

Or double-click:

```text
run_dictation.bat
```

#### Subtitle mode

```powershell
python main.py --mode subtitles --source loopback
```

Or double-click:

```text
run_subtitles.bat
```

#### Common commands

```powershell
python main.py --config .\config.json
python main.py --backend sherpa-onnx
python main.py --backend funasr
python main.py --once
python main.py --save-dataset --dataset-dir .\dataset
```

#### GUI

```powershell
python main_gui.py
```

The GUI includes:

- start/stop controls
- mode and backend switching
- a small floating prompt while recording or capturing a hotkey
- the latest recognition result

The Chinese `funasr` backend is wired back into the main app, but currently limited to microphone dictation only.

### Default Behavior

| Scenario | Default hotkey mode | Default key | Default output |
| --- | --- | --- | --- |
| `dictation` | `push-to-talk` | `F2` | `type_text` |
| `subtitles` | `toggle` | `F2` | `console_subtitles` + `overlay_subtitles` |

Hotkey semantics:

- `toggle`: press once to start, press again to stop
- `push-to-talk`: hold the key to capture, release it to submit the final result

### Config Example

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
    "mode": "auto",
    "toggle": "f2",
    "push_to_talk": "f2"
  },
  "asr": {
    "backend": "sherpa-onnx",
    "language": "ru",
    "provider": "cpu",
    "num_threads": 2,
    "enable_endpoint_detection": true,
    "sherpa": {
      "model_dir": "models/sherpa-onnx-ru-streaming",
      "variant": "t-one-ctc",
      "sample_rate": 8000,
      "feature_dim": 80,
      "decoding_method": "greedy_search"
    }
  },
  "output": {
    "method": "auto",
    "append_newline": false,
    "sinks": ["type_text"]
  }
}
```

### Build EXE

```powershell
.\build_exe.bat
```

Output:

```text
dist\UniSpeechRuntime\UniSpeechRuntime.exe
dist\UniSpeechRuntime\UniSpeechRuntimeUI.exe
```

This is a `one-folder` build and includes the default `models/sherpa-onnx-ru-streaming` directory.

- `UniSpeechRuntime.exe` is the CLI entrypoint
- `UniSpeechRuntimeUI.exe` is the GUI entrypoint

### Test

```powershell
python -m unittest discover -s tests -v
python -m compileall main.py app tests
```

### Status

Implemented:

- new streaming runtime skeleton
- `sherpa-onnx` backend integration
- `funasr` Chinese dictation backend reconnected to the unified app entry
- Windows text injection output
- console and Tk overlay subtitles
- minimal Tk control window with hotkey recording prompts
- config migration and baseline tests

Still evolving:

- `Vosk` / `Qwen3-ASR` backends are not implemented yet
- model lifecycle management is still basic
- subtitle UI can be improved further
- loopback device / process targeting is still coarse

### Credits

- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
- [sounddevice](https://python-sounddevice.readthedocs.io/)
- [soundcard](https://github.com/bastibe/SoundCard)
- [keyboard](https://github.com/boppreh/keyboard)

</details>
