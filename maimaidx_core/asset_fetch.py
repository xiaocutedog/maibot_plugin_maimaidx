"""官方素材包（Resource CN）自动下载与解压。

下载在后台进行，不阻塞聊天命令；命令在素材就绪前使用简化渲染。
"""

import shutil
from pathlib import Path
from typing import Awaitable, Callable, List, Optional

import httpx

# 官方发布源（README 公布的直链；sign 可能过期，可在配置中覆盖下载地址）
DEFAULT_ASSET_URLS = [
    'https://share.yuzuchan.moe/d/downloads/Resource%20CN1.55.7z?sign=4wMRn_9n6YZiEVV2vELKCEOj9zsgxScnmgtjsEL3C6g=:0',
    'https://cloud.yuzuchan.moe/f/34s7/Resource%20CN1.55.7z',
]

ARCHIVE_NAME = 'maimaidx_resources.7z'
NEED_GB = 2.0


class AssetFetchError(RuntimeError):
    """素材下载/解压失败。"""


def enough_space(target: Path, need_gb: float = NEED_GB) -> bool:
    """目标磁盘剩余空间是否充足（下载 + 解压约需 2GB）。"""
    try:
        usage = shutil.disk_usage(str(target))
        return usage.free >= need_gb * 1024 ** 3
    except Exception:  # noqa: BLE001 - 无法判断时视为充足
        return True


def find_static_dir(base: Path) -> Optional[Path]:
    """在解压目录中定位包含 mai/pic 的 static 目录。"""
    if not base.is_dir():
        return None
    for p in base.rglob('static'):
        if p.is_dir() and (p / 'mai' / 'pic').is_dir():
            return p
    return None


async def download_archive(
    urls: List[str],
    dest: Path,
    progress_cb: Optional[Callable[[int, int], Awaitable[None]]] = None,
    log=None,
) -> Path:
    """按顺序尝试多个下载源，流式下载到 dest（.part 临时文件）。"""
    errors: List[str] = []
    for url in urls:
        if not url or not url.strip():
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix('.part')
            last_report = 0.0
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream('GET', url.strip()) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get('content-length', 0))
                    done = 0
                    with open(tmp, 'wb') as f:
                        async for chunk in resp.aiter_bytes(1024 * 256):
                            f.write(chunk)
                            done += len(chunk)
                            if progress_cb and total:
                                ratio = done / total
                                if ratio - last_report >= 0.1 or done == total:
                                    last_report = ratio
                                    await progress_cb(done, total)
            tmp.replace(dest)
            return dest
        except Exception as e:  # noqa: BLE001 - 换下一个源
            errors.append(f'{url[:60]}...: {e}')
            if log:
                log.warning('素材下载源失败，尝试下一个源: %s', e)
    raise AssetFetchError('所有下载源均失败：' + '；'.join(errors))


def extract_archive(archive: Path, workdir: Path) -> Path:
    """解压 .7z 并返回定位到的 static 目录。"""
    try:
        import py7zr
    except ImportError as e:
        raise AssetFetchError('缺少 py7zr，无法解压素材包') from e
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        with py7zr.SevenZipFile(str(archive), 'r') as z:
            z.extractall(str(workdir))
    except Exception as e:
        raise AssetFetchError(f'素材包解压失败: {e}') from e
    static = find_static_dir(workdir)
    if not static:
        raise AssetFetchError('压缩包中未找到 static/mai/pic 目录，文件可能不完整')
    return static
