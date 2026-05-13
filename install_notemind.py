#!/usr/bin/env python3
"""
NoteMind 一键安装脚本 — 跨平台（Windows / Linux / macOS）

功能：
  1. 创建 Python 虚拟环境
  2. pip 安装 NoteMind 核心 + 可选依赖
  3. 优先离线安装 minimind-v 模型，失败则从网络下载

用法：
  python install_notemind.py                          # 交互式
  python install_notemind.py --no-vlm                 # 跳过 VLM
  python install_notemind.py --offline model.tar.gz   # 指定离线模型包
  python install_notemind.py --yes                    # 非交互式（全部接受默认）
  python install_notemind.py --yes --no-vlm           # 非交互式 + 跳过 VLM
"""

import os
import sys
import platform
import subprocess
import argparse
import json
from pathlib import Path

# 颜色输出（Windows cmd 不支持 ANSI 时用纯文本回退）
_USE_COLOR = sys.stdout.isatty() and platform.system() != "Windows"


def c(color_code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{color_code}m{text}\033[0m"


def ok(t: str) -> str: return c("32", f"  ✓ {t}")
def fail(t: str) -> str: return c("31", f"  ✗ {t}")
def info(t: str) -> str: return c("36", t)
def warn(t: str) -> str: return c("33", f"  ⚠ {t}")


def run_cmd(cmd: list[str], cwd: str = None, quiet: bool = False) -> tuple[bool, str]:
    """运行命令，返回 (是否成功, 输出)。"""
    if not quiet:
        print(f"  > {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, timeout=300
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "命令超时（300s）"
    except Exception as e:
        return False, str(e)


def check_python() -> bool:
    """检查 Python 版本。"""
    v = sys.version_info
    if v.major == 3 and v.minor >= 10:
        print(ok(f"Python {v.major}.{v.minor}.{v.micro}"))
        return True
    print(fail(f"需要 Python 3.10+，当前 {v.major}.{v.minor}"))
    return False


def create_venv(venv_dir: Path) -> tuple[bool, Path]:
    """创建虚拟环境。"""
    if venv_dir.exists() and (venv_dir / "pyvenv.cfg").exists():
        print(warn(f"虚拟环境已存在: {venv_dir}"))
        return True, get_python_in_venv(venv_dir)

    print(info("创建虚拟环境..."))
    ok, _ = run_cmd([sys.executable, "-m", "venv", str(venv_dir)])
    if not ok:
        print(fail("虚拟环境创建失败"))
        return False, None
    print(ok("虚拟环境已创建"))
    return True, get_python_in_venv(venv_dir)


def get_python_in_venv(venv_dir: Path) -> Path:
    """返回虚拟环境中 python 的路径。"""
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def get_pip_in_venv(venv_dir: Path) -> Path:
    """返回虚拟环境中 pip 的路径。"""
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "pip.exe"
    return venv_dir / "bin" / "pip"


def install_deps(python_exe: Path, extras: list[str], project_dir: Path) -> bool:
    """安装 NoteMind 依赖。"""
    extras_str = f"[{','.join(extras)}]" if extras else ""
    target = f"{project_dir}{extras_str}"

    print(info("安装 NoteMind 核心及依赖..."))
    ok, _ = run_cmd([str(python_exe), "-m", "pip", "install", "--upgrade", "pip"], quiet=True)
    ok, out = run_cmd([str(python_exe), "-m", "pip", "install", "-e", target])
    if not ok:
        print(fail("依赖安装失败"))
        print(out[-500:] if len(out) > 500 else out)
        return False
    print(ok("依赖安装完成"))
    return True


def install_vlm_offline(venv_python: Path, archive_path: str, project_dir: Path) -> bool:
    """离线安装 VLM 模型。"""
    if not os.path.exists(archive_path):
        print(fail(f"离线模型包不存在: {archive_path}"))
        return False

    # 安装 torch + transformers + Pillow
    print(info("安装 VLM 依赖 (torch, transformers, Pillow)..."))
    ok, _ = run_cmd([str(venv_python), "-m", "pip", "install", "torch", "transformers>=4.40", "Pillow"])
    if not ok:
        print(fail("VLM 依赖安装失败"))
        return False

    # 解压模型
    minimind_dir = project_dir / "minimind-v"
    print(info(f"解压模型包: {archive_path}"))
    os.makedirs(minimind_dir, exist_ok=True)
    import tarfile
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(minimind_dir)
        print(ok("模型解压完成"))
    except Exception as e:
        print(fail(f"解压失败: {e}"))
        return False

    return verify_vlm(project_dir)


def install_vlm_online(venv_python: Path, project_dir: Path) -> bool:
    """在线安装 VLM 模型。"""
    # 安装 VLM Python 依赖
    print(info("安装 VLM 依赖 (torch, transformers, Pillow, modelscope)..."))
    ok, _ = run_cmd([str(venv_python), "-m", "pip", "install", "torch", "transformers>=4.40", "Pillow", "modelscope"])
    if not ok:
        print(fail("VLM 依赖安装失败"))
        return False

    minimind_dir = project_dir / "minimind-v"

    # 下载 SigLIP2 视觉编码器
    vision_path = minimind_dir / "model" / "siglip2-base-p32-256-ve"
    if (vision_path / "model.safetensors").exists():
        print(ok(f"SigLIP2 已存在: {vision_path}"))
    else:
        print(info("下载 SigLIP2 视觉编码器 (~180MB)..."))
        os.makedirs(vision_path, exist_ok=True)
        ok, out = run_cmd([
            "modelscope", "download",
            "--model", "gongjy/siglip2-base-p32-256-ve",
            "--local_dir", str(vision_path)
        ])
        if not ok:
            print(fail("SigLIP2 下载失败"))
            return False
        print(ok("SigLIP2 下载完成"))

    # 下载 MiniMind-V SFT 权重
    weight_path = minimind_dir / "out" / "sft_vlm.pth"
    if weight_path.exists():
        print(ok(f"SFT 权重已存在: {weight_path}"))
    else:
        print(info("下载 MiniMind-V SFT 权重 (~125MB)..."))
        os.makedirs(weight_path.parent, exist_ok=True)
        cache_dir = minimind_dir / "modelscope_cache_weights"
        ok, _ = run_cmd([
            "modelscope", "download",
            "--model", "gongjy/minimind-3v",
            "--local_dir", str(cache_dir)
        ])
        if not ok:
            print(fail("SFT 权重下载失败"))
            return False
        src = cache_dir / "pytorch_model.bin"
        if src.exists():
            import shutil
            shutil.copy2(src, weight_path)
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)
            print(ok("SFT 权重下载完成"))

    return verify_vlm(project_dir)


def verify_vlm(project_dir: Path) -> bool:
    """验证 VLM 安装。"""
    print(info("验证 VLM 安装..."))
    vision_path = project_dir / "minimind-v" / "model" / "siglip2-base-p32-256-ve"
    weight_path = project_dir / "minimind-v" / "out" / "sft_vlm.pth"

    has_vision = (vision_path / "model.safetensors").exists() or \
                 (vision_path / "pytorch_model.bin").exists()
    has_weight = weight_path.exists()

    if has_vision and has_weight:
        print(ok("VLM 模型文件存在"))
        return True
    else:
        if not has_vision:
            print(warn("SigLIP2 视觉编码器缺失"))
        if not has_weight:
            print(warn("SFT 权重文件缺失"))
        return False


def setup_config(project_dir: Path) -> bool:
    """生成 config.json（如果不存在）。"""
    config_path = project_dir / "config.json"
    example_path = project_dir / "config.json.example"

    if config_path.exists():
        print(ok("config.json 已存在"))
        return True

    if example_path.exists():
        import shutil
        shutil.copy2(example_path, config_path)
        print(ok("已从 config.json.example 创建 config.json"))
        print(warn("请编辑 config.json 填入 API key"))
        return True

    # 创建最小配置
    cfg = {
        "ai": {
            "providers": [{
                "api_key": "YOUR_API_KEY",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com/v1",
                "multimodal": False
            }],
            "concurrency": 5,
            "max_retries": 3,
            "retry_delay": 1
        },
        "vault": {"path": "./knowledge-base", "categories": {"其他": []}},
        "import": {"archive_dir": "_archive", "failed_dir": "_failed", "dedup": True,
                   "dedup_index": ".notemind_index.json", "split_threshold_sections": 5,
                   "split_threshold_chars": 50000},
        "performance": {"chunk_size": 5, "report_enabled": True},
        "logging": {"level": "INFO", "file": "logs/import.log", "log_dir": "logs"}
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
    print(ok("已创建 config.json（请编辑填入 API key）"))
    return True


def main():
    parser = argparse.ArgumentParser(description="NoteMind 一键安装脚本")
    parser.add_argument("--no-vlm", action="store_true", help="跳过 VLM 模型安装")
    parser.add_argument("--offline", type=str, default=None, help="离线模型包路径 (tar.gz)")
    parser.add_argument("--yes", action="store_true", help="非交互式，接受所有默认选项")
    parser.add_argument("--venv", type=str, default=None, help="虚拟环境路径")
    args = parser.parse_args()

    project_dir = Path(__file__).resolve().parent
    print("=" * 60)
    print("  NoteMind 一键安装")
    print(f"  平台: {platform.system()} {platform.machine()}")
    print(f"  项目目录: {project_dir}")
    print("=" * 60)

    # 1. 检查 Python
    print(f"\n{info('[1/5] 检查 Python')}")
    if not check_python():
        sys.exit(1)

    # 2. 创建虚拟环境
    print(f"\n{info('[2/5] 创建虚拟环境')}")
    venv_dir = Path(args.venv) if args.venv else project_dir / "venv"
    ok, python_exe = create_venv(venv_dir)
    if not ok:
        sys.exit(1)

    # 3. 安装依赖
    print(f"\n{info('[3/5] 安装 NoteMind 依赖')}")
    extras = ["all"]
    if not install_deps(python_exe, extras, project_dir):
        sys.exit(1)

    # 4. 配置
    print(f"\n{info('[4/5] 配置文件')}")
    setup_config(project_dir)

    # 5. VLM 模型
    print(f"\n{info('[5/5] VLM 模型')}")
    if args.no_vlm:
        print(warn("跳过 VLM 模型安装"))
    else:
        # 优先离线安装
        if args.offline:
            offline_path = args.offline
            print(info(f"使用离线模型包: {offline_path}"))
            if install_vlm_offline(python_exe, offline_path, project_dir):
                print(ok("VLM 离线安装成功"))
            else:
                print(fail("离线安装失败，尝试在线下载..."))
                if not install_vlm_online(python_exe, project_dir):
                    print(fail("VLM 在线安装也失败，跳过"))
        else:
            # 检查本地是否已有模型文件
            if verify_vlm(project_dir):
                print(ok("VLM 模型已存在，跳过安装"))
            else:
                print(info("本地无 VLM 模型，从网络下载..."))
                if not install_vlm_online(python_exe, project_dir):
                    print(fail("VLM 在线安装失败"))

    # 完成
    print(f"\n{'=' * 60}")
    print(ok("NoteMind 安装完成！"))
    print(f"\n激活虚拟环境:")
    if platform.system() == "Windows":
        print(f"  {venv_dir}\\Scripts\\activate")
    else:
        print(f"  source {venv_dir}/bin/activate")
    print(f"\n使用:")
    print(f"  notemind --source ./inbox --vault ./knowledge-base")
    print(f"  python import.py --source ./inbox")
    print(f"\n记得编辑 config.json 填入 API key!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
