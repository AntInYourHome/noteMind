#!/usr/bin/env python3
"""
NoteMind VLM 模型安装器 — 支持在线下载和离线解压两种模式。

用法:
  # 在线模式（有网络）:
  python scripts/setup_vlm.py

  # 离线模式（已有模型包）:
  python scripts/setup_vlm.py --offline /path/to/minimind-v-models.tar.gz
"""

import os
import sys
import shutil
import subprocess
import argparse


def run_cmd(cmd: str) -> bool:
    """运行 shell 命令，返回是否成功。"""
    print(f"  > {cmd}")
    result = subprocess.run(cmd, shell=True)
    return result.returncode == 0


def check_modelscope() -> bool:
    """检查 ModelScope 是否已安装。"""
    try:
        subprocess.run(["modelscope", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def install_offline(archive_path: str, project_dir: str) -> bool:
    """离线解压模型包。"""
    minimind_dir = os.path.join(project_dir, "minimind-v")

    print(f"\n[1] 解压模型包: {archive_path}")
    if not os.path.exists(archive_path):
        print(f"  文件不存在: {archive_path}")
        return False

    os.makedirs(minimind_dir, exist_ok=True)

    # 解压到 minimind-v 目录
    cmd = f'tar xzf "{archive_path}" -C "{minimind_dir}"'
    if not run_cmd(cmd):
        print("  解压失败")
        return False

    # 验证
    vision_path = os.path.join(minimind_dir, "model", "siglip2-base-p32-256-ve")
    weight_path = os.path.join(minimind_dir, "out", "sft_vlm.pth")

    if not os.path.exists(os.path.join(vision_path, "model.safetensors")):
        print("  警告: SigLIP2 模型文件不完整")
        return False
    if not os.path.exists(weight_path):
        print("  警告: SFT 权重文件不存在")
        return False

    size_mb = os.path.getsize(archive_path) / (1024 * 1024)
    print(f"  已解压 ({size_mb:.0f}MB)")
    return True


def install_online(project_dir: str) -> bool:
    """在线下载模型。"""
    minimind_dir = os.path.join(project_dir, "minimind-v")

    # 1. 安装 ModelScope
    if not check_modelscope():
        print("\n[1] 安装 ModelScope...")
        if not run_cmd("pip install modelscope -q"):
            print("  安装失败，请手动执行: pip install modelscope")
            return False

    # 2. 创建目录
    os.makedirs(minimind_dir, exist_ok=True)
    os.makedirs(os.path.join(minimind_dir, "model"), exist_ok=True)
    os.makedirs(os.path.join(minimind_dir, "out"), exist_ok=True)

    # 3. 下载 SigLIP2 视觉编码器
    vision_path = os.path.join(minimind_dir, "model", "siglip2-base-p32-256-ve")
    if os.path.exists(os.path.join(vision_path, "model.safetensors")):
        print(f"\n[√] SigLIP2 已存在: {vision_path}")
    else:
        print(f"\n[2] 下载 SigLIP2 视觉编码器 (~180MB)...")
        if not run_cmd(
            f"modelscope download --model gongjy/siglip2-base-p32-256-ve "
            f"--local_dir {vision_path}"
        ):
            print("  下载失败")
            return False

    # 4. 下载 MiniMind-V SFT 权重
    weight_path = os.path.join(minimind_dir, "out", "sft_vlm.pth")
    if os.path.exists(weight_path):
        print(f"\n[√] SFT 权重已存在: {weight_path}")
    else:
        print(f"\n[3] 下载 MiniMind-V SFT 权重 (~125MB)...")
        cache_dir = os.path.join(minimind_dir, "modelscope_cache_weights")
        if not run_cmd(
            f"modelscope download --model gongjy/minimind-3v "
            f"--local_dir {cache_dir}"
        ):
            print("  下载失败")
            return False
        src = os.path.join(cache_dir, "pytorch_model.bin")
        if os.path.exists(src):
            shutil.copy2(src, weight_path)
            print(f"  已复制到: {weight_path}")
            shutil.rmtree(cache_dir, ignore_errors=True)

    return True


def verify_installation(project_dir: str) -> bool:
    """验证模型安装。"""
    sys.path.insert(0, project_dir)
    try:
        from scripts.vlm_local import is_available
        if is_available():
            return True
    except Exception:
        pass
    return False


def main():
    parser = argparse.ArgumentParser(description="NoteMind VLM 模型安装器")
    parser.add_argument("--offline", type=str, default=None,
                        help="离线模型包路径 (tar.gz)")
    args = parser.parse_args()

    # 确定项目根目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    os.chdir(project_dir)

    print("=" * 50)
    print("NoteMind VLM 模型安装")
    print("=" * 50)

    # 安装
    if args.offline:
        success = install_offline(args.offline, project_dir)
    else:
        success = install_online(project_dir)

    if not success:
        print("\n安装失败!")
        sys.exit(1)

    # 验证
    print("\n[4] 验证安装...")
    if verify_installation(project_dir):
        print("  VLM 模型可用!")
        print("\n" + "=" * 50)
        print("安装完成！VLM 图片描述功能已就绪。")
        print("默认自动启用（NOTEMIND_LOCAL_VLM=auto）。")
        print("如需禁用: export NOTEMIND_LOCAL_VLM=0")
    else:
        print("  警告: 模型文件存在但不可用，请检查路径")

    print("=" * 50)


if __name__ == "__main__":
    main()
