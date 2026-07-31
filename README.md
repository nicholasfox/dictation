# 听写助手 (Dictation Reader)

一款中文听写/听写练习辅助工具，支持逐字朗读、田字格显示、实时字数统计。

## 功能特点

- **逐字朗读** - 将文本逐字用 TTS 语音朗读，支持从开头或光标位置开始
- **标点朗读** - 中英文标点符号自动转为语音提示（如"逗号"、"句号"）
- **田字格显示** - 右侧实时显示当前字符的田字格临摹格
- **高亮跟踪** - 当前朗读字符黄色背景高亮
- **字数统计** - 实时显示总字数和剩余字数（所有非空白字符）
- **暂停/继续** - 支持暂停和继续朗读，可随时停止
- **可配置** - 字体大小、朗读间隔、提示语等均可通过 config.json 自定义
- **便携式** - 所有配置和日志存储在 exe 同目录，无需安装

## 适合操作系统

- **Windows 10/11**（仅支持 Windows，依赖 SAPI5 TTS 引擎）

## 使用说明

### 直接运行 Python 脚本

```bash
pip install pyttsx3 simpleaudio
python dictation.py
```

### 操作方式

| 操作 | 说明 |
|------|------|
| 从开头朗读 | 从文本第一字开始朗读 |
| 从光标朗读 | 从鼠标点击位置开始朗读 |
| 暂停朗读 | 暂停当前朗读，可随时继续 |
| 停止朗读 | 停止朗读并回到初始状态 |
| 空格键 | 快捷暂停/继续 |
| ESC 键 | 快捷停止 |
| 字体大小 | 输入数值后点击"更新" |
| 朗读间隔 | 拖动滑动条调整字符间停顿时间（0.5-10秒） |

### 配置文件

首次运行后会在 exe 同目录生成 `config.json`，可手动编辑：

```json
{
  "title": "听写",
  "font_family": "STKaiti",
  "font_size": 32,
  "tts_rate": 150,
  "tts_volume": 1.0,
  "char_interval": 0.5,
  "intro_text": "你好，同学，请认真听，现在开始",
  "outro_text": "日记完成，你很努力，加油！"
}
```

| 字段 | 说明 |
|------|------|
| `title` | 窗口标题 |
| `font_family` | 字体名称（需系统已安装） |
| `font_size` | 默认字体大小 |
| `tts_rate` | TTS 语速（150 = 正常） |
| `tts_volume` | 音量（0.0 - 1.0） |
| `char_interval` | 字符间默认停顿秒数 |
| `intro_text` | 开头提示语 |
| `outro_text` | 结尾提示语 |

## 构建 Windows EXE

### 使用 PyInstaller

```bash
pip install pyinstaller pyttsx3 simpleaudio
pyinstaller --onedir --strip --noconsole --name dictation dictation.py
```

构建产物在 `dist/dictation/` 目录。

### 使用 GitHub Actions（自动构建）

1. 打 tag 触发自动构建：
```bash
git tag v5.0
git push --tags
```

2. 在 Actions → Artifacts 下载构建产物。

## 目录结构

```
dictation/
├── dictation.py          # 主程序
├── config.json           # 配置文件（自动生成）
├── logs/
│   ├── dictation.log     # 运行日志
│   └── audio_cache/      # 临时音频（运行时自动清理）
└── README.md
```

## 依赖

- Python 3.10+
- pyttsx3（TTS 引擎）
- simpleaudio（音频播放）
- tkinter（GUI，Python 内置）

## License

MIT
