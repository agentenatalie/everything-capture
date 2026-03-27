#!/bin/bash
set -euo pipefail

REPO_URL="https://github.com/agentenatalie/everything-capture"
REPO_DIR="everything-capture"

# 1. 检查并安装 Python3
if ! command -v python3 &>/dev/null; then
  echo "⚙️  未检测到 Python3，正在尝试自动安装..."

  OS="$(uname -s)"
  case "$OS" in
    Darwin)
      # macOS: 优先 brew，没有 brew 则先装 brew
      if ! command -v brew &>/dev/null; then
        echo "📦 正在安装 Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Apple Silicon vs Intel
        if [ -f /opt/homebrew/bin/brew ]; then
          eval "$(/opt/homebrew/bin/brew shellenv)"
        else
          eval "$(/usr/local/bin/brew shellenv)"
        fi
      fi
      echo "📦 正在通过 Homebrew 安装 Python3..."
      brew install python3
      ;;
    Linux)
      if command -v apt-get &>/dev/null; then
        echo "📦 正在通过 apt 安装 Python3..."
        sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
      elif command -v dnf &>/dev/null; then
        echo "📦 正在通过 dnf 安装 Python3..."
        sudo dnf install -y python3 python3-pip
      elif command -v yum &>/dev/null; then
        echo "📦 正在通过 yum 安装 Python3..."
        sudo yum install -y python3 python3-pip
      elif command -v pacman &>/dev/null; then
        echo "📦 正在通过 pacman 安装 Python3..."
        sudo pacman -Sy --noconfirm python python-pip
      else
        echo "❌ 无法自动安装 Python3，请手动安装后重新运行本脚本"
        echo "   下载地址: https://www.python.org/downloads/"
        exit 1
      fi
      ;;
    *)
      echo "❌ 不支持的系统: $OS"
      echo "   请手动安装 Python3: https://www.python.org/downloads/"
      exit 1
      ;;
  esac

  # 验证安装成功
  if ! command -v python3 &>/dev/null; then
    echo "❌ Python3 安装失败，请手动安装后重新运行本脚本"
    echo "   下载地址: https://www.python.org/downloads/"
    exit 1
  fi
  echo "✅ Python3 安装成功: $(python3 --version)"
fi

# 2. 检查并安装 ffmpeg（视频转录和字幕提取需要）
if ! command -v ffmpeg &>/dev/null; then
  echo "⚙️  未检测到 ffmpeg，正在尝试自动安装..."
  OS="$(uname -s)"
  case "$OS" in
    Darwin)
      if command -v brew &>/dev/null; then
        brew install ffmpeg
      else
        echo "⚠️  未找到 Homebrew，跳过 ffmpeg 安装（视频转录功能将不可用）"
      fi
      ;;
    Linux)
      if command -v apt-get &>/dev/null; then
        sudo apt-get install -y ffmpeg
      elif command -v dnf &>/dev/null; then
        sudo dnf install -y ffmpeg
      elif command -v pacman &>/dev/null; then
        sudo pacman -Sy --noconfirm ffmpeg
      else
        echo "⚠️  无法自动安装 ffmpeg，跳过（视频转录功能将不可用）"
      fi
      ;;
  esac
  if command -v ffmpeg &>/dev/null; then
    echo "✅ ffmpeg 安装成功"
  fi
else
  echo "✅ ffmpeg 已安装"
fi

# 3. 下载代码（git > curl > wget）
if [ ! -d "$REPO_DIR" ]; then
  if command -v git &>/dev/null; then
    git clone "$REPO_URL"
  elif command -v curl &>/dev/null; then
    echo "未检测到 git，使用 curl 下载..."
    curl -L "$REPO_URL/archive/refs/heads/main.zip" -o ec.zip
    unzip ec.zip && mv everything-capture-main "$REPO_DIR" && rm ec.zip
  elif command -v wget &>/dev/null; then
    echo "未检测到 git，使用 wget 下载..."
    wget "$REPO_URL/archive/refs/heads/main.zip" -O ec.zip
    unzip ec.zip && mv everything-capture-main "$REPO_DIR" && rm ec.zip
  else
    echo "❌ 需要 git、curl 或 wget 中的任意一个"
    echo "  macOS:   xcode-select --install  (自带 git 和 curl)"
    echo "  Ubuntu:  sudo apt install git"
    exit 1
  fi
else
  echo "✅ $REPO_DIR 已存在，跳过下载"
fi

# 4. 创建虚拟环境 + 安装依赖
cd "$REPO_DIR"
if [ ! -d backend/venv ]; then
  python3 -m venv backend/venv
fi
backend/venv/bin/pip install -r requirements.txt

# 5. 启动
./run
