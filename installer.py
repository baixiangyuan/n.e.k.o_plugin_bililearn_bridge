"""BiliLearn 安装包的获取与解包（仓库自带 + 自动下载）。

「开箱即用」由本模块保证：猫娘要操控 BiliLearn，但用户不该被要求
手填 exe 路径。取得 exe 的顺序是

1. **仓库自带**：插件包内的 ``assets/`` 目录随版本附带一份安装包，
   离线可用、无需联网。
2. **本地缓存**：之前自动下载过的包缓存在插件数据目录，不重复下载。
3. **自动下载**：以上都没有时，从 GitHub release 拉取最新版
   （``xiaoyaya191/bilibili_learning_bot``），带 SHA256 校验。
4. **本地已装**：以上都失败则回退到常见安装位置扫描（见 ``__init__``）。

解包目标默认为插件数据目录下的 ``runtime/``（即 ``data_path()/runtime``），
绝不写系统目录，卸载/清理时随插件数据一起消失。

零第三方依赖：``urllib.request`` 下载、``zipfile`` 解包、``hashlib`` 校验。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

# GitHub 上的发行仓库：安装包发布在 release 资产里。
GITHUB_OWNER = "xiaoyaya191"
GITHUB_REPO = "bilibili_learning_bot"
# 安装包名前缀（版本号在后）：BiliLearn-Web-3.1.6-Windows-x64.zip
INSTALLER_PREFIX = "BiliLearn-Web-"
INSTALLER_SUFFIX = "-Windows-x64.zip"
# 仓库自带安装包所在目录（相对插件包根）。
ASSETS_DIRNAME = "assets"
# 解包后的运行时根目录名（位于插件数据目录下）。
RUNTIME_DIRNAME = "runtime"
# 仓库自带的版本号（与 assets/ 下实际文件名保持一致）。
BUNDLED_VERSION = "3.1.6"

_RELEASE_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
_USER_AGENT = "n.e.k.o-plugin-bililearn-bridge"
# 单块大小：1024 KiB，够快且内存占用可控。
_CHUNK = 1024 * 1024


def bundled_asset_dir(plugin_dir: Path) -> Path:
    """仓库自带安装包目录（插件包内的 ``assets/``）。"""
    return Path(plugin_dir) / ASSETS_DIRNAME


def runtime_root(state_dir: Path | None) -> Path:
    """解包后的 BiliLearn 运行时根目录（插件数据目录下，可安全清理）。"""
    base = Path(state_dir) if state_dir else Path.home() / ".neko" / "bililearn_bridge"
    return base / RUNTIME_DIRNAME


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def find_runtime_exe(state_dir: Path | None) -> Path | None:
    """已解包的运行时里是否已有 exe（不触发解包，纯本地查找）。"""
    return _find_exe_in(runtime_root(state_dir))


# 分卷清单文件名（GitHub 单文件 100MB 上限下的自带安装包形态）。
MANIFEST_NAME = "installer-manifest.json"
# 重组结果的暂存后缀，避免半成品被当成可用安装包。
_REASSEMBLING_SUFFIX = ".reassembling"


def _read_manifest(plugin_dir: Path) -> dict[str, Any] | None:
    """读取 assets/installer-manifest.json；缺失或损坏返回 None。"""
    path = bundled_asset_dir(plugin_dir) / MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    parts = data.get("parts")
    if not isinstance(parts, list) or not parts:
        return None
    if not all(isinstance(name, str) and name for name in parts):
        return None
    for key in ("name", "size", "sha256", "part_bytes"):
        if key not in data:
            return None
    return data


def reassemble_bundled(plugin_dir: Path, state_dir: Path | None, *, logger: Any = None) -> Path | None:
    """把仓库自带的分卷安装包拼回完整 zip（带 SHA256 校验，结果缓存）。

    返回拼好的 zip 路径；没有分卷/校验失败返回 None。
    """
    manifest = _read_manifest(plugin_dir)
    if not manifest:
        return None
    name = str(manifest["name"])
    size = int(manifest["size"])
    expected = str(manifest["sha256"]).lower()

    cache = _cache_dir(state_dir)
    target = cache / name
    try:
        if target.is_file() and target.stat().st_size == size and _sha256_of(target).lower() == expected:
            if logger:
                logger.info("复用已重组缓存：%s", name)
            return target
    except OSError:
        pass

    partial = target.with_name(target.name + _REASSEMBLING_SUFFIX)
    digest = hashlib.sha256()
    written = 0
    try:
        cache.mkdir(parents=True, exist_ok=True)
        with partial.open("wb") as out:
            for part in manifest["parts"]:
                part_path = bundled_asset_dir(plugin_dir) / str(part)
                with part_path.open("rb") as handle:
                    while True:
                        chunk = handle.read(_CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        if logger:
            logger.error("重组自带安装包失败：%s", exc)
        return None
    if written != size or digest.hexdigest().lower() != expected:
        partial.unlink(missing_ok=True)
        if logger:
            logger.error("重组结果校验未通过（大小/哈希不符），已丢弃")
        return None
    partial.replace(target)
    if logger:
        logger.info("已重组自带安装包：%s（%.1f MB）", name, size / 1048576)
    return target


def find_bundled_installer(plugin_dir: Path) -> Path | None:
    """在仓库自带的 ``assets/`` 里找安装包（取名字典序最大者＝最新版）。"""
    folder = bundled_asset_dir(plugin_dir)
    try:
        if not folder.is_dir():
            return None
    except OSError:
        return None
    try:
        candidates = [
            entry
            for entry in folder.iterdir()
            if entry.is_file()
            and entry.name.startswith(INSTALLER_PREFIX)
            and entry.name.endswith(INSTALLER_SUFFIX)
        ]
    except OSError:
        return None
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item.name)[-1]


def _version_from_name(name: str) -> str:
    stem = name
    if stem.startswith(INSTALLER_PREFIX):
        stem = stem[len(INSTALLER_PREFIX):]
    if stem.endswith(INSTALLER_SUFFIX):
        stem = stem[: -len(INSTALLER_SUFFIX)]
    return stem


def find_cached_installer(state_dir: Path | None) -> Path | None:
    """查找已下载并缓存的安装包（不触发下载）。"""
    cache = _cache_dir(state_dir)
    try:
        if not cache.is_dir():
            return None
    except OSError:
        return None
    try:
        candidates = [
            entry
            for entry in cache.iterdir()
            if entry.is_file()
            and entry.name.startswith(INSTALLER_PREFIX)
            and entry.name.endswith(INSTALLER_SUFFIX)
        ]
    except OSError:
        return None
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item.name)[-1]


def _cache_dir(state_dir: Path | None) -> Path:
    base = Path(state_dir) if state_dir else Path.home() / ".neko" / "bililearn_bridge"
    return base / "installer-cache"


def _asset_api_url() -> str:
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def _http_get(url: str, timeout: float = 30.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - 固定 GitHub 域名
        return response.read()


def _release_metadata(timeout: float) -> dict[str, Any]:
    """读取 latest release 元数据；失败时抛出 OSError 由上层降级处理。"""
    raw = _http_get(_asset_api_url(), timeout=timeout)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise OSError("unexpected release metadata")
    return data


def _pick_installer_asset(metadata: dict[str, Any]) -> tuple[str, str, int] | None:
    """从 release 资产里挑 Windows x64 安装包，返回 (url, name, size)。"""
    assets = metadata.get("assets")
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        size = int(asset.get("size") or 0)
        if name.startswith(INSTALLER_PREFIX) and name.endswith(INSTALLER_SUFFIX) and url:
            return url, name, size
    return None


def _pick_checksum_asset(metadata: dict[str, Any]) -> str | None:
    assets = metadata.get("assets")
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if name.endswith("SHA256SUMS.txt") and url:
            return url
    return None


def _download(url: str, target: Path, timeout: float) -> Path:
    """流式下载到 target（先写 .part，完成后原子改名，避免半成品被当作可用）。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - 固定 GitHub 域名
        with partial.open("wb") as handle:
            while True:
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
    partial.replace(target)
    return target


def _verify_against_sums(target: Path, sums_url: str, timeout: float) -> bool:
    """有 SHA256SUMS.txt 就校验；没有则跳过（返回 True）。"""
    try:
        text = _http_get(sums_url, timeout=timeout).decode("utf-8", "replace")
    except (OSError, urllib.error.URLError):
        return True
    expected = ""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == target.name:
            expected = parts[0].lower()
            break
    if not expected:
        return True
    return _sha256_of(target).lower() == expected


def download_installer(state_dir: Path | None, timeout: float = 60.0) -> tuple[Path | None, str]:
    """从 GitHub latest release 下载安装包。

    返回 ``(路径, 说明)``；失败时路径为 ``None``，说明里带上原因，
    由调用方降级到「本地扫描」并如实告知用户。
    """
    cache = _cache_dir(state_dir)
    try:
        metadata = _release_metadata(timeout=timeout)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return None, f"读取 release 信息失败：{exc}"
    picked = _pick_installer_asset(metadata)
    if not picked:
        return None, "latest release 中没有找到 Windows x64 安装包"
    url, name, size = picked
    target = cache / name
    try:
        if target.is_file() and target.stat().st_size == size:
            return target, f"复用缓存：{name}"
        _download(url, target, timeout=timeout)
        if size and target.stat().st_size != size:
            target.unlink(missing_ok=True)
            return None, "下载文件大小与 release 不符，已丢弃"
    except (OSError, urllib.error.URLError) as exc:
        target.unlink(missing_ok=True)
        return None, f"下载失败：{exc}"
    sums_url = _pick_checksum_asset(metadata)
    if sums_url and not _verify_against_sums(target, sums_url, timeout=timeout):
        target.unlink(missing_ok=True)
        return None, "SHA256 校验未通过，已丢弃"
    version = _version_from_name(name)
    return target, f"已下载 {name}（{version}）"


def _find_exe_in(tree: Path, max_depth: int = 4) -> Path | None:
    """在解包目录里浅层定位 exe（打包形态为 "BiliLearn Web/BiliLearn Web.exe"）。"""
    names = ("BiliLearn Web.exe", "BiliLearnWeb.exe")
    try:
        if not tree.is_dir():
            return None
    except OSError:
        return None
    for name in names:
        candidate = tree / "BiliLearn Web" / name
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            pass
    for name in names:
        try:
            if (tree / name).is_file():
                return tree / name
        except OSError:
            pass
    if max_depth <= 0:
        return None
    try:
        entries = list(os.scandir(tree))
    except OSError:
        return None
    for entry in entries:
        try:
            if not entry.is_dir() or entry.name.startswith((".", "_", "$")):
                continue
        except OSError:
            continue
        found = _find_exe_in(Path(entry.path), max_depth - 1)
        if found:
            return found
    return None


def ensure_runtime_exe(
    installer: Path,
    state_dir: Path | None,
    *,
    logger: Any = None,
) -> Path | None:
    """把安装包解包到运行时目录并返回 exe 路径。

    幂等：已解包且 exe 存在则直接复用；安装包变化（版本不同）会先清旧目录。
    解包用 ``zipfile``，不调用外部解压程序。
    """
    target = runtime_root(state_dir)
    version = _version_from_name(installer.name)
    marker = target / ".installed-version"
    try:
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == version:
            found = _find_exe_in(target)
            if found:
                return found
    except (OSError, UnicodeDecodeError):
        pass

    # 版本不同或标记缺失：清掉旧运行时后重新解包。
    try:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        if logger:
            logger.info("正在解包 BiliLearn %s 到 %s", version, target)
        with zipfile.ZipFile(installer) as archive:
            # 只允许解出相对路径，防御 zip-slip。
            for member in archive.namelist():
                name = member.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    raise zipfile.BadZipFile(f"unsafe entry: {member}")
            archive.extractall(target)
        marker.write_text(version, encoding="utf-8")
    except (OSError, zipfile.BadZipFile) as exc:
        if logger:
            logger.error("解包 BiliLearn 失败：%s", exc)
        return None
    return _find_exe_in(target)


def cleanup_runtime(state_dir: Path | None) -> None:
    """删除解包出来的运行时目录（插件卸载/清理时调用）。"""
    shutil.rmtree(runtime_root(state_dir), ignore_errors=True)


def bundled_version() -> str:
    """仓库自带安装包对应的 BiliLearn 版本号。"""
    return BUNDLED_VERSION
