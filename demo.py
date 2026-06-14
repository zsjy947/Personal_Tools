"""图像解混淆/解密工具。

支持 5 种解混淆模式：
    1. 方块混淆
    2. 行像素混淆
    3. 像素混淆
    4. 兼容 PicEncrypt: 行模式
    5. 兼容 PicEncrypt: 行+列模式
"""

import hashlib
import time

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
    wid, hit, z = img_li.shape
    xl = amess(wid, key)
    return get_img_2(img_li, xl)


def decrypt_c(img_li, key):
    """3. 像素混淆解密。"""
    wid, hit, z = img_li.shape
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


# -------- 主函数 --------

def main(mode: str, path: str, key: str, out: str) -> None:
    """解混淆主函数。

    Args:
        mode: 解密模式 '1'~'5'
        path: 输入图片路径
        key: 密钥（模式 1-3 为字符串，模式 4-5 为 0-1 浮点数）
        out: 输出图片路径
    """
    img = Image.open(path)

    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    img_li = np.array(img)

    if mode == '1':
        new_img = decrypt_b2(img_li, key)
    elif mode == '2':
        new_img = decrypt_c2(img_li, key)
    elif mode == '3':
        new_img = decrypt_c(img_li, key)
    elif mode == '4':
        key = float(key)
        new_img = decrypt_pe1(img_li, key)
    elif mode == '5':
        key = float(key)
        new_img = decrypt_pe2(img_li, key)
    else:
        raise ValueError(f"无效的解密模式: {mode}")

    img = Image.fromarray(np.uint8(new_img))
    img.save(out)
    print(f'文件 {out} 已存入。')


if __name__ == '__main__':
    image = input('Path：')
    pword = input('Password(0-1)：')
    save_path = input('Save to(不含后缀)：') + '.png'
    mode = input(
        '1. 方块混淆\n'
        '2. 行像素混淆\n'
        '3. 像素混淆\n'
        '4. 兼容PicEncrypt: 行模式\n'
        '5. 兼容PicEncrypt: 行+列模式\n'
        '输入解混淆模式：'
    )

    start_time = time.time()
    main(mode, image, pword, save_path)
    input(
        '\nDecryption Finished...\n'
        'Time: {:.6f} second(s)\n'
        'Press any key...'.format(time.time() - start_time)
    )
