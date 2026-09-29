"""官方素材包（Resource CN）自动下载与解压。

下载在后台进行，不阻塞聊天命令；命令在素材就绪前使用简化渲染。

安全约定（与 README「官方素材包」一节对应）：
- 只接受 https 下载地址，http 明文地址直接拒绝；
- 下载完成后校验 SHA-256（配置固定值，或源站 <地址>.sha256 旁挂文件），不匹配即丢弃该源；
- 解压前校验包内成员路径，拒绝绝对路径、盘符、``..`` 与解压后落在目标目录之外的条目（Zip-Slip）。
"""

import hashlib
from pathlib import Path
from typing import Awaitable, Callable, List, Optional

import httpx

# 官方发布源。第一项是柚子社官方发布页的稳定直链，作为主源；
# 第二项为带 sign 的分享直链（sign 会过期），仅作备用，不作为唯一来源。
DEFAULT_ASSET_URLS = [
    'https://cloud.yuzuchan.moe/f/34s7/Resource%20CN1.55.7z',
    'https://share.yuzuchan.moe/d/downloads/Resource%20CN1.55.7z?sign=4wMRn_9n6YZiEVV2vELKCEOj9zsgxScnmgtjsEL3C6g=:0',
]

ARCHIVE_NAME = 'maimaidx_resources.7z'
NEED_GB = 2.0
SEVENZ_MAGIC = b'7z\xbc\xaf\x27\x1c'
# 素材包约 445MB；明显偏小说明拿到的是错误页/占位文件
MIN_ARCHIVE_BYTES = 1024 * 1024


class AssetFetchError(RuntimeError):
    """素材下载/解压失败。"""


def check_url(url: str) -> str:
    """校验下载地址：仅允许 https。"""
    text = (url or '').strip()
    if not text.lower().startswith('https://'):
        raise AssetFetchError(f'素材下载地址必须为 https:// 开头，已拒绝：{text[:80] or "(空)"}')
    return text


def check_final_url(url: str) -> None:
    """跟随重定向后再次确认仍是 https（防止源站把请求降级到明文）。"""
    if str(url).lower().startswith('https://'):
        return
    raise AssetFetchError(f'下载被重定向到非 https 地址，已中止：{str(url)[:80]}')


def sha256_file(path: Path) -> str:
    """流式计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def enough_space(target: Path, need_gb: float = NEED_GB) -> bool:
    """目标磁盘剩余空间是否充足（下载 + 解压约需 2GB）。"""
    try:
        import shutil

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


def check_member_paths(names: List[str], workdir: Path) -> None:
    """解压前校验包内成员路径，防止 zip-slip 写到目标目录之外。

    新版本 py7zr 自身也会拦截非法成员名，这里做独立校验以便：
    尽早失败并给出明确报错，且在旧版 py7zr 下同样安全。
    """
    base = Path(workdir).resolve()
    for raw in names:
        name = str(raw).replace('\\', '/')
        if not name or name.startswith('/') or Path(name).is_absolute():
            raise AssetFetchError(f'素材包内含非法路径，已中止解压：{name[:120]}')
        parts = [p for p in name.split('/') if p not in ('', '.')]
        if parts and ':' in parts[0]:  # Windows 盘符（C:...）
            raise AssetFetchError(f'素材包内含非法路径，已中止解压：{name[:120]}')
        if '..' in parts:
            raise AssetFetchError(f'素材包内含上级目录跳转，已中止解压：{name[:120]}')
        target = (base / Path(*parts)).resolve() if parts else base
        if target != base and base not in target.parents:
            raise AssetFetchError(f'素材包内条目将写到目标目录之外，已中止解压：{name[:120]}')


async def fetch_sidecar_sha256(url: str, log=None) -> Optional[str]:
    """尝试读取 <下载地址>.sha256 作为期望哈希；不存在或格式不符时返回 None。

    旁挂文件只能发现损坏/截断或源站侧的意外改动，不能抵御恶意源站；
    需要强校验请在配置 resources.download_sha256 固定哈希。
    """
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            res = await client.get(check_url(url) + '.sha256')
        if res.status_code != 200:
            return None
        check_final_url(str(res.url))
        fields = res.text.split()
        token = fields[0].strip().lower() if fields else ''
        if len(token) == 64 and all(c in '0123456789abcdef' for c in token):
            return token
        if log:
            log.warning('素材包旁挂校验文件格式不符，已忽略：%s', res.text[:60])
    except Exception as e:  # noqa: BLE001 - 旁挂文件缺失属正常情况
        if log:
            log.info('未获取到素材包旁挂 SHA-256（%s），跳过旁挂校验', e)
    return None


async def download_archive(
    urls: List[str],
    dest: Path,
    progress_cb: Optional[Callable[[int, int], Awaitable[None]]] = None,
    log=None,
    expected_sha256: str = '',
) -> Path:
    """按顺序尝试多个下载源，流式下载到 dest（.part 临时文件）。

    仅接受 https 源；下载完成后做大小、7z 魔数与 SHA-256 校验，任一不过即丢弃该源换下一个。
    """
    errors: List[str] = []
    expected = (expected_sha256 or '').strip().lower()
    tmp = dest.with_suffix('.part')
    for url in urls:
        if not url or not url.strip():
            continue
        try:
            url = check_url(url)
        except AssetFetchError as e:
            errors.append(str(e))
            if log:
                log.warning('素材下载源被拒绝: %s', e)
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            last_report = 0.0
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream('GET', url) as resp:
                    check_final_url(str(resp.url))
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
            if tmp.stat().st_size < MIN_ARCHIVE_BYTES:
                raise AssetFetchError(
                    f'素材包体积异常（仅 {tmp.stat().st_size} 字节），可能下载到了错误页')
            with open(tmp, 'rb') as f:
                if f.read(len(SEVENZ_MAGIC)) != SEVENZ_MAGIC:
                    raise AssetFetchError('下载内容不是 7z 压缩包（文件头校验失败）')
            digest = sha256_file(tmp)
            want = expected or await fetch_sidecar_sha256(url, log=log)
            if want and digest != want:
                raise AssetFetchError(f'SHA-256 校验失败（期望 {want}，实际 {digest}）')
            if log:
                if want:
                    log.info('素材包校验通过（SHA-256 %s）', digest)
                else:
                    log.info('素材包 SHA-256：%s（源站未提供校验值，仅记录；'
                             '可在 resources.download_sha256 固定该值）', digest)
            tmp.replace(dest)
            return dest
        except Exception as e:  # noqa: BLE001 - 换下一个源
            errors.append(f'{url[:60]}...: {e}')
            if log:
                log.warning('素材下载源失败，尝试下一个源: %s', e)
    try:  # 全部源失败时清掉半截文件，避免留下几百 MB 垃圾
        tmp.unlink()
    except OSError:
        pass
    raise AssetFetchError('所有下载源均失败：' + '；'.join(errors))


def extract_archive(archive: Path, workdir: Path) -> Path:
    """解压 .7z 并返回定位到的 static 目录。"""
    try:
        import py7zr
    except ImportError as e:
        raise AssetFetchError('缺少 py7zr，无法解压素材包') from e
    if not archive.is_file():
        raise AssetFetchError(f'素材包不存在：{archive}')
    with open(archive, 'rb') as f:
        if f.read(len(SEVENZ_MAGIC)) != SEVENZ_MAGIC:
            raise AssetFetchError('素材包不是有效的 7z 文件（文件可能损坏或未下载完整）')
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        with py7zr.SevenZipFile(str(archive), 'r') as z:
            check_member_paths(z.getnames(), workdir)
            z.extractall(str(workdir))
    except AssetFetchError:
        raise
    except Exception as e:
        raise AssetFetchError(f'素材包解压失败: {e}') from e
    static = find_static_dir(workdir)
    if not static:
        raise AssetFetchError('压缩包中未找到 static/mai/pic 目录，文件可能不完整')
    return static
