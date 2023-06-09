import random

import numpy as np
import skimage.color as sc

import torch

def get_patch(*args, patch_size=96, scale=2, multi=False, input_large=False):
    """
    一对lr和hr，随机取一对patch
    :param args:
    :param patch_size:
    :param scale:
    :param multi:
    :param input_large:
    :return:
    """
    """
    ih, iw = args[0].shape[:2]
    args[0]:lr
    取lr的高和宽
    """
    ih, iw = args[0].shape[:2]
    """
    oabreast
    multi = False(只有一个scale)
    input_large = False（只有VDSR，input_large = True）
    """
    if not input_large:
        p = scale if multi else 1
        tp = p * patch_size
        ip = tp // scale
        """
        实际效果
        tp = patch_size
        ip = patch_scale // scale
        """
    else:
        tp = patch_size
        ip = patch_size

    # 在start和stop-1间，选取一个随机数
    """
    random.randrange(start, end, step = 1):在start和stop-1间，选取一个随机数
    取lr的patch的，h和w的随机起始点
    """
    ix = random.randrange(0, iw - ip + 1)
    iy = random.randrange(0, ih - ip + 1)

    if not input_large:
        """
        hr patch的对应随机起始点
        """
        tx, ty = scale * ix, scale * iy
    else:
        tx, ty = ix, iy

    """
    args[0][iy:iy + ip, ix:ix + ip, :],
    *[a[ty:ty + tp, tx:tx + tp, :] for a in args[1:]]
    
    在Oabreast的_load_file函数没有改变之前，直接取三维图像的一帧，得到二维图像，没有第三维
    而，上面的语句涉及到第三维，所以，编译器报错
    下面的语句，只对前两维处理，第三维如果存在，效果为全取，如果不存在，没有对应处理
    也就是适应三维和二维
    
    args[1:]：lr之外的其他图像
    *[]:列表解包
    """
    ret = [
        args[0][iy:iy + ip, ix:ix + ip],
        *[a[ty:ty + tp, tx:tx + tp] for a in args[1:]]
    ]

    return ret

def set_channel(*args, n_channels=3):
    def _set_channel(img):
        if img.ndim == 2:
            """
            如果img为二维矩阵，即灰度图，增加一个维度，使其成为三维矩阵
            """
            img = np.expand_dims(img, axis=2)

        c = img.shape[2]
        if n_channels == 1 and c == 3:
            img = np.expand_dims(sc.rgb2ycbcr(img)[:, :, 0], 2)
        elif n_channels == 3 and c == 1:
            img = np.concatenate([img] * n_channels, 2)

        return img

    return [_set_channel(a) for a in args]

def np2Tensor(*args, rgb_range=255):
    def _np2Tensor(img):
        np_transpose = np.ascontiguousarray(img.transpose((2, 0, 1)))
        tensor = torch.from_numpy(np_transpose).float()
        tensor.mul_(rgb_range / 255)

        return tensor

    return [_np2Tensor(a) for a in args]

def augment(*args, hflip=True, rot=True):
    """
    flip：翻转
    vertical：垂直的
    horizonal：水平的
    rotate：旋转
    :param args:
    :param hflip:
    :param rot:
    :return:
    """
    hflip = hflip and random.random() < 0.5
    vflip = rot and random.random() < 0.5
    rot90 = rot and random.random() < 0.5

    def _augment(img):
        """
        ::-1    从结尾到开头，逆序取元素
        水平：改变列
        垂直：改变行
        旋转：转置矩阵
        :param img:
        :return:
        """
        if hflip: img = img[:, ::-1, :]
        if vflip: img = img[::-1, :, :]
        if rot90: img = img.transpose(1, 0, 2)
        
        return img

    return [_augment(a) for a in args]

