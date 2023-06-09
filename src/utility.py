import os
import math
import time
import datetime
from multiprocessing import Process
from multiprocessing import Queue

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import numpy as np
import imageio

import torch
import torch.optim as optim
import torch.optim.lr_scheduler as lrs
from torch.utils.tensorboard import SummaryWriter

from skimage.metrics import peak_signal_noise_ratio

class timer():
    def __init__(self):
        self.acc = 0
        self.tic()

    def tic(self):
        # time.time():返回时间戳
        self.t0 = time.time()

    def toc(self, restart=False):
        diff = time.time() - self.t0
        if restart: self.t0 = time.time()
        return diff

    def hold(self):
        self.acc += self.toc()

    def release(self):
        ret = self.acc
        self.acc = 0

        return ret

    def reset(self):
        self.acc = 0

class checkpoint():
    # 函数组1
    def __init__(self, args):
        self.args = args
        self.ok = True
        # log：模型参数文件psnr_log.pt，每个epoch都要记录
        self.log = torch.Tensor()
        now = datetime.datetime.now().strftime('%Y-%m-%d-%H:%M:%S')

        # 加载checkpoint
        # load：加载load中的数据，继续上一次训练
        # dir：某次实验的文件根目录
        # log：psnr_log.pt
        if not args.load:
            # 新的实验，建立对应实验根目录
            if not args.save:
                args.save = now
                if args.save_suffix:
                    # 我的修改，时间now添加后缀save_suffix
                    args.save = args.save + "_" + args.save_suffix
            self.dir = os.path.join('..', 'experiment', args.save)
        else:
            # 加载已存在实验数据，加载对应实验根目录
            self.dir = os.path.join('..', 'experiment', args.load)
            if os.path.exists(self.dir):
                self.log = torch.load(self.get_path('psnr_log.pt'))
                print('Continue from epoch {}...'.format(len(self.log)))
            else:
                args.load = ''

        # reset：重置实验，删除实验根目录
        if args.reset:
            os.system('rm -rf ' + self.dir)
            args.load = ''

        # 建立dir，如果dir没有建立
        os.makedirs(self.dir, exist_ok=True)
        # 建立实验model文件夹
        os.makedirs(self.get_path('model'), exist_ok=True)
        # 建立数据集sr重建结果输出文件夹
        for d in args.data_test:
            os.makedirs(self.get_path('results-{}'.format(d)), exist_ok=True)
        # 建立tensorboard文件夹与对应writer
        os.makedirs(self.get_path('tblog'), exist_ok=True)
        self.writer = SummaryWriter(log_dir=self.get_path('tblog'))

        # log_file，加载log.txt：model结构
        # w：打开文件，具有写权限
        # X：创建文件，具有写权限
        open_type = 'a' if os.path.exists(self.get_path('log.txt'))else 'x'
        self.log_file = open(self.get_path('log.txt'), open_type)
        # 加载config.txt：args参数
        with open(self.get_path('config.txt'), open_type) as f:
            f.write(now + '\n\n')
            for arg in vars(args):
                f.write('{}: {}\n'.format(arg, getattr(args, arg)))
            f.write('\n')

        # 线程数（background函数中将使用线程）
        self.n_processes = 8

    def get_path(self, *subdir):
        '''
        将subdir元组中的参数，与项目根目录dir拼接，并返回
        :param subdir:
        :return:
        '''
        return os.path.join(self.dir, *subdir)

    # 函数组2
    def save(self, trainer, epoch, is_best=False):
        """
        保存各个模块的pt文件，log日志
        没有涉及图像的保存
        :param trainer:
        :param epoch:
        :param is_best:
        :return:
        """
        # 保存best、latest、epoch_i模型权重文件
        trainer.model.save(self.get_path('model'), epoch, is_best=is_best)
        # 保存loss模块权重文件loss.pt，和每个epoch的平均loss记录文件loss_log.pt
        trainer.loss.save(self.dir)

        # 绘制并保存loss图像
        trainer.loss.plot_loss(self.dir, epoch)
        # 绘制并保存psnr图像
        self.plot_psnr(epoch)

        trainer.optimizer.save(self.dir)
        torch.save(self.log, self.get_path('psnr_log.pt'))

    def plot_psnr(self, epoch):
        axis = np.linspace(1, epoch, epoch)
        # 仅对测试数据集，绘制psnr图像
        for idx_data, d in enumerate(self.args.data_test):
            label = 'SR on {}'.format(d)
            fig = plt.figure()
            plt.title(label)
            for idx_scale, scale in enumerate(self.args.scale):
                plt.plot(
                    axis,
                    self.log[:, idx_data, idx_scale].numpy(),
                    label='Scale {}'.format(scale)
                )
            plt.legend()
            plt.xlabel('Epochs')
            plt.ylabel('PSNR')
            plt.grid(True)
            plt.savefig(self.get_path('test_{}.png'.format(d)))
            plt.close(fig)

    # 函数组3
    def add_log(self, log):
        # 拼接log（psnr）：将传入的log与ckp中log拼接
        # log(psnr)最终由skp.save函数保存
        self.log = torch.cat([self.log, log])

    # 函数组4
    def write_log(self, log, refresh=False):
        # 往log.txt中写入日志
        print(log)
        self.log_file.write(log + '\n')
        if refresh:
            self.log_file.close()
            self.log_file = open(self.get_path('log.txt'), 'a')

    def done(self):
        self.log_file.close()

    # 函数组5
    def begin_background(self):
        """
        创建线程安全的数据结构Queue（）：queue

        创建多线程
        线程从queue中提取图像数据（文件名与像素张量），存储为图像文件
        :return:
        """
        self.queue = Queue()

        def bg_target(queue):
            while True:
                if not queue.empty():
                    filename, tensor = queue.get()
                    if filename is None: break
                    imageio.imwrite(filename, tensor.numpy())

        self.process = [
            Process(target=bg_target, args=(self.queue,)) \
            for _ in range(self.n_processes)
        ]
        
        for p in self.process: p.start()

    def end_background(self):
        """
        关闭所有线程
        1、往quque中添加n_processes个（None, None）， 使n_processes个线程停止目标函数
        2、等待queue空，即所有process停止目标函数
        3、join函数，阻塞主线程，使其等待子线程结束后，继续
        :return:
        """
        for _ in range(self.n_processes): self.queue.put((None, None))
        while not self.queue.empty(): time.sleep(1)
        for p in self.process: p.join()

    # 数组6
    def save_results(self, dataset, filename, save_list, scale):
        """
        将图片信息放入queue中
        线程从queue中取出信息，完成图片文件保存
        :param dataset:
        :param filename:
        :param save_list:
        :param scale:
        :return:
        """
        if self.args.save_results:
            filename = self.get_path(
                'results-{}'.format(dataset.dataset.name),
                '{}_x{}_'.format(filename, scale)
            )

            postfix = ('SR', 'LR', 'HR')
            for v, p in zip(save_list, postfix):
                normalized = v[0].mul(255 / self.args.rgb_range)
                tensor_cpu = normalized.byte().permute(1, 2, 0).cpu()
                self.queue.put(('{}{}.png'.format(filename, p), tensor_cpu))

    def save_results_dat(self, dataset, sr_dat, scale):
        if self.args.save_results:
            filename = self.get_path(
                'results-{}'.format(dataset.dataset.name),
                '{}_x{}_SR.DAT'.format(self.args.data_test, scale)
            )
            sr_dat.tofile(filename)

def quantize(img, rgb_range):
    """
    :param img:
    :param rgb_range:
    :return:
    """
    """
        pixel_range = 255 / rgb_range 这是整数，不会有误差吗
    """
    pixel_range = 255.0 / rgb_range
    """
    clamp（l, r）：将变量限制在l~r之间
    round：四舍五入的保留小数，默认保留小数位为0，相当于取整；输入数据与输出数据的类型相同
    """
    # return img.mul(pixel_range).clamp(0, 255).round().div(pixel_range)
    return img.mul(pixel_range).clamp(0, 255).div(pixel_range).round()

def calc_psnr(sr, hr, scale, rgb_range, dataset=None):
    # tensor.nelement() 获取tensor的元素数量
    if hr.nelement() == 1: return 0

    """
    shave
    修剪边缘像素
    """
    diff = (sr - hr) / rgb_range
    if dataset and dataset.dataset.benchmark:
        shave = scale
        """
        tensor.size（）获取tensor形状
        tensor.size(1) 获取第二个维度大小，也就是通道数量
        """
        if diff.size(1) > 1:
            gray_coeffs = [65.738, 129.057, 25.064]
            convert = diff.new_tensor(gray_coeffs).view(1, 3, 1, 1) / 256
            diff = diff.mul(convert).sum(dim=1)
    else:
        shave = scale + 6

    valid = diff[..., shave:-shave, shave:-shave]
    mse = valid.pow(2).mean()

    print(f"\npeak_signal_noise_ratio : {peak_signal_noise_ratio(hr.cpu().numpy(), sr.cpu().numpy(), data_range=rgb_range)}")
    print(f"calc_psnr : {-10 * math.log10(mse)}")

    return -10 * math.log10(mse)

# def calc_psnr(sr, hr, scale, rgb_range, dataset=None):
#     return peak_signal_noise_ratio(hr, sr, data_range=rgb_range)

def make_optimizer(args, target):
    '''
        make optimizer and scheduler together
    '''
    # optimizer
    """
    trainable ：获取模型中可训练的参数
    lr learning rate
    """
    trainable = filter(lambda x: x.requires_grad, target.parameters())
    kwargs_optimizer = {'lr': args.lr, 'weight_decay': args.weight_decay}

    if args.optimizer == 'SGD':
        optimizer_class = optim.SGD
        kwargs_optimizer['momentum'] = args.momentum
    elif args.optimizer == 'ADAM':
        # 默认优化器
        optimizer_class = optim.Adam
        kwargs_optimizer['betas'] = args.betas
        kwargs_optimizer['eps'] = args.epsilon
    elif args.optimizer == 'RMSprop':
        optimizer_class = optim.RMSprop
        kwargs_optimizer['eps'] = args.epsilon

    # scheduler
    milestones = list(map(lambda x: int(x), args.decay.split('-')))
    kwargs_scheduler = {'milestones': milestones, 'gamma': args.gamma}
    scheduler_class = lrs.MultiStepLR

    """
    类名后面的括号中，填写继承的父类
    optimizer_class是一个占位符，或者说一个变量，存储一个class
    """
    class CustomOptimizer(optimizer_class):
        def __init__(self, *args, **kwargs):
            super(CustomOptimizer, self).__init__(*args, **kwargs)

        def _register_scheduler(self, scheduler_class, **kwargs):
            self.scheduler = scheduler_class(self, **kwargs)

        def save(self, save_dir):
            torch.save(self.state_dict(), self.get_dir(save_dir))

        def load(self, load_dir, epoch=1):
            self.load_state_dict(torch.load(self.get_dir(load_dir)))
            if epoch > 1:
                for _ in range(epoch): self.scheduler.step()

        def get_dir(self, dir_path):
            return os.path.join(dir_path, 'optimizer.pt')

        def schedule(self):
            self.scheduler.step()

        def get_lr(self):
            # return self.scheduler.get_lr()[0]
            return self.scheduler.get_last_lr()[0]

        def get_last_epoch(self):
            return self.scheduler.last_epoch
    
    optimizer = CustomOptimizer(trainable, **kwargs_optimizer)
    optimizer._register_scheduler(scheduler_class, **kwargs_scheduler)
    return optimizer

