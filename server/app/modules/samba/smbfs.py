"""Samba 连接层：纯 Python 的 smbprotocol/smbclient，配置来自 server/.env。

    SAMBA_HOST=192.168.1.10        # 服务器地址
    SAMBA_SHARE=share              # 共享名
    SAMBA_ROOT=tasks               # 共享内子目录（可空=共享根）
    SAMBA_USER=xxx / SAMBA_PASSWORD=xxx

依赖（requirements-samba.txt）为惰性导入：未安装时模块可正常加载、状态接口给出提示。
路径拼接全部在本层完成，路由层只见相对名，天然防目录穿越。
"""
import os

from fastapi import HTTPException

_session_ok = False


def _smb_available() -> bool:
    try:
        import smbclient  # noqa: F401

        return True
    except ImportError:
        return False


def _smb():
    import smbclient

    return smbclient


def conf() -> dict:
    return {
        "host": os.environ.get("SAMBA_HOST", "").strip(),
        "share": os.environ.get("SAMBA_SHARE", "").strip(),
        "root": os.environ.get("SAMBA_ROOT", "").strip("/\\"),
        "user": os.environ.get("SAMBA_USER", "").strip(),
        "password": os.environ.get("SAMBA_PASSWORD", ""),
    }


def configured() -> bool:
    c = conf()
    return all([c["host"], c["share"], c["user"], c["password"]])


def _p(task: str = "", file: str | None = None) -> str:
    c = conf()
    parts = [f"\\\\{c['host']}\\{c['share']}"]
    if c["root"]:
        parts.append(c["root"])
    if task:
        parts.append(task)
    if file:
        parts.append(file)
    return "\\".join(parts)


def _ensure():
    global _session_ok
    if not configured():
        raise HTTPException(400, "Samba 未配置（在 server/.env 填写 SAMBA_* 后重启服务）")
    if not _smb_available():
        raise HTTPException(400, "未安装 smbprotocol（pip install -r requirements-samba.txt）")
    if not _session_ok:
        c = conf()
        _smb().register_session(c["host"], username=c["user"], password=c["password"])
        _session_ok = True


def _run(fn, *args):
    _ensure()
    try:
        return fn(*args)
    except HTTPException:
        raise
    except Exception as e:  # 连接类错误：重置会话，下次重连
        global _session_ok
        _session_ok = False
        try:
            _smb().reset_connection_cache()
        except Exception:
            pass
        raise HTTPException(502, f"Samba 操作失败：{e}")


# ---- 文件原语（测试打桩点）----

def listdir(task: str = "") -> list[str]:
    return _run(_smb().listdir, _p(task))


def stat(task: str = "", file: str | None = None):
    return _run(_smb().stat, _p(task, file))


def exists(task: str, file: str | None = None) -> bool:
    return _run(_smb().path.exists, _p(task, file))


def read(task: str, file: str) -> bytes:
    def _rd():
        with _smb().open_file(_p(task, file), "rb") as f:
            return f.read()
    return _run(_rd)


def write(task: str, file: str, data: bytes):
    def _wr():
        with _smb().open_file(_p(task, file), "wb") as f:
            f.write(data)
    return _run(_wr)


def mkdir(task: str):
    return _run(_smb().mkdir, _p(task))


def remove(task: str, file: str):
    return _run(_smb().remove, _p(task, file))


def is_dir(st) -> bool:
    # FILE_ATTRIBUTE_DIRECTORY = 0x10；直接判位，不依赖 smbprotocol 内部枚举路径
    return bool(getattr(st, "st_file_attributes", 0) & 0x10)


def probe() -> tuple[bool, str]:
    """连接探测（status 接口用）。"""
    if not configured():
        return False, "未配置"
    if not _smb_available():
        return False, "未安装 smbprotocol"
    try:
        _ensure()  # 先注册会话再访问，否则无凭据导致 SPNEGO 失败
        _smb().listdir(_p())
        return True, "连接正常"
    except HTTPException as e:
        return False, str(e.detail)[:200]
    except Exception as e:
        return False, str(e)[:200]
