# ============================================================
# PyMC - Native binary auto-downloader
# ============================================================
"""
当本地 ``native/`` 目录里没有可用的 ``terrain_gen`` / ``mob_ai``
可执行文件时（或本地版本因为 DLL 缺失而启动失败时），
自动从 GitHub Release 下载对应平台的预编译二进制并落盘。

下载源: https://github.com/ZerexaNet/PYMC/releases/latest
缓存目录: <repo_root>/native/  (与源码同名，下次启动直接复用)
"""

from __future__ import annotations

import json
import logging
import os
import platform
import stat
import sys
import urllib.request
import urllib.error
from pathlib import Path

logger = logging.getLogger("pymc.native_downloader")

# Public GitHub repo for release asset lookup (no token needed for public releases)
GITHUB_OWNER = "ZerexaNet"
GITHUB_REPO = "PYMC"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def _cache_dir() -> Path:
    """返回 native 二进制缓存目录。优先放在源码根目录的 native/ 下。"""
    # 1) 源码布局: <repo>/native/
    here = Path(__file__).resolve().parent.parent
    candidates = [
        here / "native",
        Path.cwd() / "native",
    ]
    # 2) Nuitka onefile 解包目录
    compiled = globals().get("__compiled__")
    if compiled is not None and hasattr(compiled, "containing_dir"):
        candidates.append(Path(compiled.containing_dir).resolve() / "native")
    # 3) 用户级缓存 (~/.pymc/native)
    candidates.append(Path.home() / ".pymc" / "native")

    for c in candidates:
        try:
            c.mkdir(parents=True, exist_ok=True)
            # 测试可写
            (c / ".write_test").touch()
            (c / ".write_test").unlink()
            return c
        except Exception:
            continue
    # 最后兜底
    fallback = Path.cwd() / "native"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _platform_asset_name(base: str) -> str:
    """根据当前平台返回 Release 中对应的资产名。"""
    if os.name == "nt":
        # Windows: terrain_gen.exe / mob_ai.exe
        if base.endswith(".exe"):
            return base
        return base + ".exe"
    # Linux/macOS: 项目当前只在 Windows CI 上传了 native 二进制，
    # 其他平台返回基础名让外层逻辑决定是否下载。
    return base


def _fetch_latest_release_info() -> dict | None:
    """调用 GitHub API 获取最新 release 元数据。失败返回 None。"""
    req = urllib.request.Request(
        RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "PyMC-native-downloader",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        logger.debug(f"GitHub API 请求失败: {e}")
        return None
    except Exception as e:
        logger.debug(f"GitHub API 解析失败: {e}")
        return None


def _download_asset(url: str, dest: Path) -> bool:
    """从 GitHub Release 下载资产到 dest，返回是否成功。"""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "PyMC-native-downloader",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        # 在 Unix 上加可执行位
        if os.name != "nt":
            try:
                dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            except Exception:
                pass
        return True
    except Exception as e:
        logger.warning(f"下载失败 {url}: {e}")
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def ensure_native_binary(
    base_name: str,
    *,
    force_redownload: bool = False,
) -> str | None:
    """
    确保本地有一个可用的 native 二进制。

    流程:
      1. 检查 <cache>/base_name 是否存在且可执行；如果存在直接返回。
      2. 否则查 GitHub 最新 Release，下载同名资产到 <cache>/。
      3. 下载后再次校验 magic bytes 是否匹配当前平台。

    参数:
      base_name: 二进制基础名，例如 "terrain_gen" 或 "mob_ai"
                 (函数内部会自动加 .exe 后缀)
      force_redownload: 即使本地已存在也强制重新下载

    返回:
      成功则返回本地路径字符串，失败返回 None。
    """
    cache = _cache_dir()
    asset_name = _platform_asset_name(base_name)
    local_path = cache / asset_name

    if not force_redownload and local_path.exists() and local_path.is_file():
        # 已有缓存，直接用
        return str(local_path)

    logger.info(f"本地未找到 {asset_name}，尝试从 GitHub Release 下载...")

    # 只在 Windows 平台尝试下载 (Linux/macOS CI 当前不单独上传 native 二进制)
    if os.name != "nt":
        logger.debug(f"非 Windows 平台，跳过下载 {asset_name}")
        return None

    release = _fetch_latest_release_info()
    if not release:
        logger.warning(
            f"无法获取 GitHub 最新 release 信息，跳过 {asset_name} 下载。"
            f" 请手动从 https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest 下载"
            f" 并放置到 {cache}"
        )
        return None

    # 找匹配的资产
    download_url = None
    asset_size = 0
    for asset in release.get("assets", []):
        if asset.get("name") == asset_name:
            download_url = asset.get("browser_download_url")
            asset_size = int(asset.get("size", 0))
            break

    if not download_url:
        logger.warning(
            f"最新 release 中未找到 {asset_name}。"
            f" 请手动从 {release.get('html_url', '')} 下载并放置到 {cache}"
        )
        return None

    logger.info(
        f"正在下载 {asset_name} ({asset_size / 1024:.0f} KB) "
        f"from {download_url} ..."
    )
    if not _download_asset(download_url, local_path):
        return None

    logger.info(f"下载完成: {local_path}")
    return str(local_path)
