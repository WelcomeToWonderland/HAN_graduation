import torch.utils.data as data
import os
import numpy as np
from data import common
import random

class OABreast(data.Dataset):
    # 函数组-1
    def __init__(self, args, name='', train=True, benchmark=False):
        print('Making dataset oabreast...')
        nxs = [616, 284, 494,
               616, 284, 494,
               616, 284, 494]
        nys = [484, 410, 614,
               484, 410, 614,
               484, 410, 614]
        """
        original
        train
        test
        """
        nzs = [719, 722, 752,
               319, 322, 352,
               400, 400, 400]
        if name.split('_')[1] == '07':
            idx = 0
        elif name.split('_')[1] == '35':
            idx = 1
        elif name.split('_')[1] == '47':
            idx = 2
        if name.endswith('train'):
            multiple = 1
        elif name.endswith('test'):
            multiple = 2
        else:
            multiple = 0
        self.nx = nxs[3 * multiple + idx]
        self.ny = nys[3 * multiple + idx]
        self.nz = nzs[3 * multiple + idx]

        self.args = args
        self.name = name
        self.train = train
        self.split = 'train' if train else 'test'
        self.do_eval = True
        # 在后续几个函数中有所涉及（commom.get_patch）
        self.input_large = (args.model == 'VDSR')
        self.benchmark = benchmark
        self.scale = args.scale
        self.idx_scale = 0


        self._set_filesystem(args.dir_data)

        list_hr, list_lr = self._scan()
        self.images_hr, self.images_lr = list_hr, list_lr

        """
        self.repeat
        在__len__函数中，有使用
        """
        if train:
            """
            test_every(_batch)
            n_patches 两次test之间，使用了n_patches张图像（patch），进行train
            """
            n_patches = args.batch_size * args.test_every
            args.test_every = 10

            """
            修改前
            n_images = len(args.data_train) * len(self.images_hr)
                        
            n_images理解为，所有数据集中图像数量之和（单个数据集，就是这个数据集中）
            
            疑惑
            数据集个数*本数据集中数据数量，但是不同数据集中的数据数量是不同的
            那这样的话，不同数据集对应dataset类求出的n_images是不同的，求出的repeat也是不同的
            """
            n_images = len(args.data_train) * np.shape(self.images_hr)[2]
            if n_images == 0:
                self.repeat = 0
            else:
                """
                self.repeat
                两次test之间，同一张图像需要重复多少次
                """
                self.repeat = max(n_patches // n_images, 1)

    def _set_filesystem(self, dir_data):
        '''
        去掉了input_large相关语句（benchmark中也去掉了）

        记录相关路径，但是没有根据路径创建文件
        :param dir_data:
        :return:
        '''
        self.apath = os.path.join(dir_data, self.name)
        scale_dir = f'X{self.scale[0]}'
        self.dir_lr = os.path.join(dir_data, self.name, 'LR',scale_dir)
        self.dir_hr = os.path.join(dir_data, self.name, 'HR')
        self.ext = '.DAT'

    def _scan(self):
        '''
        扫描文件夹
        读取dat文件，加载所有图片信息，放入list
        :return:
        '''
        list_hr = []
        # 读取不同scale的lr文件
        list_lr = [[] for _ in self.scale]

        for entry in os.scandir(self.dir_hr):
            filename = os.path.splitext(entry.name)[0]
            list_hr = np.fromfile(os.path.join(self.dir_hr, filename + self.ext), dtype=np.uint8)
            list_hr = list_hr.reshape(self.nx, self.ny, self.nz)
        for entry in os.scandir(self.dir_lr):
            filename = os.path.splitext(entry.name)[0]
            for si, s in enumerate(self.scale):
                list_lr[si] = np.fromfile(os.path.join(self.dir_lr, filename + self.ext), dtype=np.uint8)
                list_lr[si] = list_lr[si].reshape(int(self.nx / s), int(self.ny / s), self.nz)

        return list_hr, list_lr

    # 函数组-2
    def __getitem__(self, idx):
        '''
        函数修改，不再返回filename，改成返回idx
        :param idx:
        :return:
        '''
        lr, hr = self._load_file(idx)
        pair = self.get_patch(lr, hr)
        pair = common.set_channel(*pair, n_channels=self.args.n_colors)
        pair_t = common.np2Tensor(*pair, rgb_range=self.args.rgb_range)
        return pair_t[0], pair_t[1], idx

    def _load_file(self, idx):
        '''
        函数修改：不再是加载图片（已经加载在list中），而是将图片从list中取出
        同时在最后增加一个维度（x，y 到 x, y, 1），相当于单通道图片
        :param idx:
        :return:
        '''
        idx = self._get_index(idx)
        # hr = self.images_hr[:, :, idx]
        # lr = self.images_lr[self.idx_scale][:, :, idx]

        # 第一、二维度，长宽不变，增加第三维度，将二维图像转化为三维图像
        hr = self.images_hr[:, :, idx]
        hr = np.expand_dims(hr, 2)
        lr = self.images_lr[self.idx_scale][:, :, idx]
        lr = np.expand_dims(lr, 2)

        return lr, hr

    def _get_index(self, idx):
        if self.train:
            return idx % np.shape(self.images_hr)[2]
        else:
            return idx

    def get_patch(self, lr, hr):
        """
        train:patch和argument
        test:没有patch，只有形状校对，符合成scale倍数就行
        :param lr:
        :param hr:
        :return:
        """
        scale = self.scale[self.idx_scale]
        if self.train:
            lr, hr = common.get_patch(
                lr, hr,
                patch_size=self.args.patch_size,
                scale=scale,
                multi=(len(self.scale) > 1),
                input_large=self.input_large
            )
            #print(hr.shape)
            if not self.args.no_augment: lr, hr = common.augment(lr, hr)
        else:
            ih, iw = lr.shape[:2]
            hr = hr[0:ih * scale, 0:iw * scale]

        return lr, hr

    # 函数-3
    def __len__(se1f):

        """
        if se1f.train:
            return np.shape(se1f.images_hr)[2] * se1f.repeat
        else:
            return np.shape(se1f.images_hr)[2]

        不再使用args.every_test属性，对应sef.repeat属性
        :return:
        """
        return np.shape(se1f.images_hr)[2]

    # 函数-4
    def set_scale(self, idx_scale):
        if not self.input_large:
            """
            oabreast，只会执行这个分支
            """
            self.idx_scale = idx_scale
        else:
            self.idx_scale = random.randint(0, len(self.scale) - 1)

