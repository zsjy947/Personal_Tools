"""图像混淆与解混淆工具。

支持 5 种双向处理模式：
    1. 方块混淆
    2. 行像素混淆
    3. 像素混淆
    4. 兼容 PicEncrypt: 行模式
    5. 兼容 PicEncrypt: 行+列模式
"""

import argparse
import hashlib
import sys
from pathlib import Path
from time import perf_counter

import numpy as np
from numba import jit
from PIL import Image


# -------- 伪随机排列生成 --------

def amess(arrlength: int, ast: str) -> np.ndarray:
    """基于 MD5 哈希生成伪随机排列序列。"""
    arr = np.linspace(0, arrlength - 1, arrlength, dtype=int)
    for i in range(arrlength - 1, 0, -1):
        content = (ast + str(i)).encode()
        md5hash = hashlib.md5(content)
        md5 = (md5hash.hexdigest())[:7].upper()
        rand = int(md5, 16) % (i + 1)
        temp = arr[rand]
        arr[rand] = arr[i]
        arr[i] = temp
    return arr


# -------- Numba JIT 加速的像素级图像变换 --------

@jit(nopython=True)
def get_img_1(img_li, sx, sy, xl, yl):
    """方块混淆的底层像素变换。"""
    hit, wid, z = img_li.shape

    ssx = wid / 32
    ssy = hit / 32

    new_img = np.zeros((hit, wid, 4))
    for i in range(wid):
        for j in range(hit):
            m, n = i, j
            m = (xl[(int(n / ssy)) % sx] * ssx + m) % wid
            m = xl[int(m / ssx)] * ssx + m % ssx
            n = (yl[(int(m / ssx)) % sy] * ssy + n) % hit
            n = yl[int(n / ssy)] * ssy + n % ssy
            m, n = int(m), int(n)

            new_img[(m + n * wid) // wid][(m + n * wid) % wid] = img_li[(i + j * wid) // wid][(i + j * wid) % wid]

    return new_img


@jit(nopython=True)
def get_img_2(img_li, xl):
    """行像素混淆的底层像素变换。"""
    hit, wid, z = img_li.shape
    new_img = np.zeros((hit, wid, 4))
    for i in range(wid):
        for j in range(hit):
            m, n = i, j
            m = (xl[n % wid] + m) % wid
            m = xl[m]

            new_img[(m + n * wid) // wid][(m + n * wid) % wid] = img_li[(i + j * wid) // wid][(i + j * wid) % wid]

    return new_img


@jit(nopython=True)
def get_img_3(img_li, xl, yl):
    """像素混淆的底层像素变换。"""
    hit, wid, z = img_li.shape
    new_img = np.zeros((hit, wid, 4))
    for i in range(wid):
        for j in range(hit):
            m, n = i, j
            m = (xl[n % wid] + m) % wid
            m = xl[m]
            n = (yl[m % hit] + n) % hit
            n = yl[n]

            new_img[(m + n * wid) // wid][(m + n * wid) % wid] = img_li[(i + j * wid) // wid][(i + j * wid) % wid]

    return new_img


@jit(nopython=True)
def get_img_4(img_li, arrayaddress):
    """PicEncrypt 行模式的底层像素变换。"""
    hit, wid, z = img_li.shape
    new_img = np.zeros((hit, wid, 4))
    for i in range(wid):
        for j in range(hit):
            m = arrayaddress[i]
            new_img[(m + j * wid) // wid][(m + j * wid) % wid] = img_li[(i + j * wid) // wid][(i + j * wid) % wid]
    return new_img


def get_img_5(img_li, key):
    """PicEncrypt 行+列模式的底层像素变换。"""
    hit, wid, z = img_li.shape
    new_img_1 = np.zeros((hit, wid, 4))
    new_img_2 = np.zeros((hit, wid, 4))

    x = key
    for i in range(wid):
        arrayaddress_hit = produce_logistic(x, hit)
        x = arrayaddress_hit[hit - 1][0]
        arrayaddress_hit.sort(key=lambda p: p[0])
        arrayaddress_hit = np.array([arr[1] for arr in arrayaddress_hit])
        for j in range(hit):
            n = arrayaddress_hit[j]
            new_img_1[(i + n * wid) // wid][(i + n * wid) % wid] = img_li[(i + j * wid) // wid][(i + j * wid) % wid]

    x = key
    for j in range(hit):
        arrayaddress_wid = produce_logistic(x, wid)
        x = arrayaddress_wid[wid - 1][0]
        arrayaddress_wid.sort(key=lambda p: p[0])
        arrayaddress_wid = np.array([arr[1] for arr in arrayaddress_wid])
        for i in range(wid):
            m = arrayaddress_wid[i]
            new_img_2[(m + j * wid) // wid][(m + j * wid) % wid] = new_img_1[(i + j * wid) // wid][(i + j * wid) % wid]

    return new_img_2


# -------- PicEncrypt 算法 --------

def produce_logistic(key: float, wid: int) -> list:
    """Logistic 映射生成混沌序列。"""
    x = key
    seq = [[x, 0]]
    for i in range(1, wid):
        x = 3.9999999 * x * (1 - x)
        seq.append([x, i])
    return seq


# -------- 5 种解密模式 --------

def decrypt_b2(img_li, key):
    """1. 方块混淆解密。"""
    sx, sy = 32, 32
    xl = amess(sx, key)
    yl = amess(sy, key)
    return get_img_1(img_li, sx, sy, xl, yl)


def decrypt_c2(img_li, key):
    """2. 行像素混淆解密。"""
    hit, wid, z = img_li.shape
    xl = amess(wid, key)
    return get_img_2(img_li, xl)


def decrypt_c(img_li, key):
    """3. 像素混淆解密。"""
    hit, wid, z = img_li.shape
    xl = amess(wid, key)
    yl = amess(hit, key)
    return get_img_3(img_li, xl, yl)


def decrypt_pe1(img_li, key):
    """4. 兼容 PicEncrypt: 行模式。"""
    hit, wid, z = img_li.shape
    arrayaddress = produce_logistic(key, wid)
    arrayaddress.sort(key=lambda p: p[0])
    arrayaddress = np.array([arr[1] for arr in arrayaddress])
    return get_img_4(img_li, arrayaddress)


def decrypt_pe2(img_li, key):
    """5. 兼容 PicEncrypt: 行+列模式。"""
    return get_img_5(img_li, key)


def decrypt_array(mode: str, img_li: np.ndarray, key: str | float) -> np.ndarray:
    """使用现有算法将像素数组解混淆。"""
    if mode == "1":
        return decrypt_b2(img_li, key)
    if mode == "2":
        return decrypt_c2(img_li, key)
    if mode == "3":
        return decrypt_c(img_li, key)
    if mode == "4":
        return decrypt_pe1(img_li, key)
    if mode == "5":
        return decrypt_pe2(img_li, key)
    raise ValueError(f"无效的处理模式: {mode}")


def encrypt_array(mode: str, img_li: np.ndarray, key: str | float) -> np.ndarray:
    """应用解混淆像素排列的逆映射，生成可还原的混淆图片。"""
    height, width, _ = img_li.shape
    pixel_ids = np.arange(height * width, dtype=np.float64).reshape(height, width)
    index_image = np.repeat(pixel_ids[:, :, np.newaxis], 4, axis=2)
    decrypted_ids = decrypt_array(mode, index_image, key)
    source_indices = decrypted_ids[:, :, 0].astype(np.int64).ravel()

    encrypted = np.empty_like(img_li)
    encrypted.reshape(-1, 4)[source_indices] = img_li.reshape(-1, 4)
    return encrypted


# -------- 主函数 --------

def process_image(
    operation: str,
    mode: str,
    input_path: str | Path,
    key: str,
    output_path: str | Path,
) -> None:
    """混淆或解混淆图片。

    Args:
        operation: `encrypt` 为混淆，`decrypt` 为解混淆
        mode: 解密模式 '1'~'5'
        input_path: 输入图片路径
        key: 密钥（模式 1-3 为字符串，模式 4-5 为 0-1 浮点数）
        output_path: 输出图片路径
    """
    if operation not in {"encrypt", "decrypt"}:
        raise ValueError(f"无效的操作: {operation}")
    if mode not in {"1", "2", "3", "4", "5"}:
        raise ValueError(f"无效的处理模式: {mode}")

    input_path = Path(input_path)
    output_path = Path(output_path)
    if not input_path.is_file():
        raise FileNotFoundError(f"输入图片不存在: {input_path}")
    if not output_path.parent.is_dir():
        raise FileNotFoundError(f"输出目录不存在: {output_path.parent}")

    numeric_key = None
    if mode in {"4", "5"}:
        try:
            numeric_key = float(key)
        except ValueError as exc:
            raise ValueError("模式 4 和 5 的密钥必须是 0 到 1 之间的数字") from exc
        if not 0 < numeric_key < 1:
            raise ValueError("模式 4 和 5 的密钥必须大于 0 且小于 1")

    with Image.open(input_path) as img:
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        img_li = np.array(img)

    algorithm_key = numeric_key if numeric_key is not None else key
    if operation == "encrypt":
        new_img = encrypt_array(mode, img_li, algorithm_key)
    else:
        new_img = decrypt_array(mode, img_li, algorithm_key)

    img = Image.fromarray(np.uint8(new_img), mode="RGBA")
    if output_path.suffix.lower() in {".jpg", ".jpeg"}:
        img = img.convert("RGB")
    img.save(output_path)
    print(f"文件已保存: {output_path}")


def decrypt_image(
    mode: str,
    input_path: str | Path,
    key: str,
    output_path: str | Path,
) -> None:
    """兼容调用入口：解混淆图片。"""
    process_image("decrypt", mode, input_path, key, output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="使用指定模式混淆或解混淆图片。")
    parser.add_argument("input", type=Path, help="输入图片路径")
    parser.add_argument("output", type=Path, help="输出图片路径，需包含扩展名")
    parser.add_argument(
        "--operation",
        choices=("encrypt", "decrypt"),
        default="decrypt",
        help="处理方向：encrypt 混淆，decrypt 解混淆（默认）",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("1", "2", "3", "4", "5"),
        help="解密模式：1 方块，2 行像素，3 像素，4 PicEncrypt 行，5 PicEncrypt 行+列",
    )
    parser.add_argument(
        "--key",
        required=True,
        help="密钥；模式 1-3 使用字符串，模式 4-5 使用 0 到 1 之间的数字",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    start_time = perf_counter()
    try:
        process_image(args.operation, args.mode, args.input, args.key, args.output)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    print(f"耗时: {perf_counter() - start_time:.6f} 秒")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
