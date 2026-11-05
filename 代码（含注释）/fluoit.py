import numpy as np
import pandas as pd
import scipy.integrate
import scipy.interpolate
import scipy.signal
import utils
import math
# from multiprocessing import Pool # 鬼！scipy的多线程支持和屎一样
import json
from pathlib import Path

import torch # 星怒出列！

#region 作图
import scienceplots
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
plt.style.use(['science', 'no-latex', 'bright'])
#endregion


#region 美化
from rich import print
from rich.console import Console
from rich.table import Table
from rich.progress import Progress
from rich.traceback import install
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text
from pyfiglet import Figlet
import argparse
from rich_argparse import RichHelpFormatter
#endregion

# 用于漂亮的控制台输出
install()

# numpy对json的支持不好，转为list处理之
class NumpyTypeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.generic):
            return obj.item()
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return json.JSONEncoder.default(self, obj)

class FluoItSolver:
    """
    主求解器
    """
    #看名字都知道是啥
    info = {} #储存各种杂七杂八的信息，懒得一个个写变量，相信自己记忆力用字典了
    time = None
    decay = None
    irf = None
    k_distribution = None
    k = None
    peak_result = None
    disp = False

    # 初始化，没啥说的
    def __init__(self, disp=False,disp_hello=False) -> None:
        self.info = {}
        self.time = None
        self.decay = None
        self.irf = None
        self.k_distribution = None
        self.k = None
        self.peak_result = None
        self.disp = disp
        if disp_hello:
            self.hello()
    
    # 各类数据的命名规范：
    # 不含pos的一律为时间（*不过目前好像没怎么用过）或一眼丁真的其他数据
    # 含pos的为位置（channel）
    def from_file(self,file_name):
        """
        从规整的文件里读取荧光数据（或许只有命令行状态用得到）

        格式要求：按顺序time、decay、irf三列，每列标题可以随便取
        Args:
            name: 文件的完整名字，带扩展名
        """
        # if os.path.exists(file_name):
        
        df = pd.read_csv(file_name) 
        self.time=df[df.columns[0]].to_numpy()    
        self.decay=df[df.columns[1]].to_numpy()
        self.irf=df[df.columns[2]].to_numpy()

    # 从传入的numpy读取数据，批处理的时候用
    def from_numpy(self,time,decay,irf):
        self.time=time
        self.decay=decay
        self.irf=irf
    
    def preprocess(self, background_length=30):
        """
        伟大的——预处理！
        Args:
            background_length: 选多长的数据视为背景
        """

        if self.disp:
            print("[bold]Preprocess [yellow]Started[/yellow][/bold]")
        irf=self.irf
        time=self.time
        decay=self.decay

        # 提取一点irf和decay相关的数据，具体内容自己看变量名
        irf_max_pos = irf.argmax()
        irf_max = irf.max()
        decay_max_pos = decay.argmax()
        decay_max = decay.max()
        data_len = len(decay)
        decay[decay <= 0] = 0.1
        irf_half = irf_max / 2
        irf_half_l_pos = np.argmax(irf >= irf_half)
        irf_half_r_pos = len(irf) - 1 - np.argmax((irf >= irf_half)[::-1])
        # print(irf[irf >= irf_half])
        irf_FWHM = time[irf_half_r_pos] - time[irf_half_l_pos]
        irf_background = irf[0 : background_length - 1].mean()
        decay_background = decay[0 : background_length - 1].mean()
        # irf_background=10
        # decay_background=0
        decay_rise_level = decay_max / 1000 + decay_background
        irf_rise_level = irf_max / 1000 + irf_background
        decay_rise_pos = -1
        for i in range(5, data_len):
            if (
                decay[i] > decay_rise_level
                and decay[i - 2 : decay_max_pos].min() > decay_background
            ):
                decay_rise_pos = i
                break
        irf_rise_pos = -1
        for i in range(5, len(irf)):
            if (
                irf[i] > irf_rise_level
                and irf[i - 2 : irf_max_pos].min() > irf_background
            ):
                irf_rise_pos = i
                break

        # 仅仅是一个简单的tail-fitting
        # 粗略的寻找一下irf和decay之间的微妙时间差（10 channels量级）
        qshift_fit_slice = slice(max(decay_rise_pos, irf_rise_pos), decay_max_pos + 2)
        qshift_data = np.arange(-30, 30, 0.2)
        qshift_data = np.column_stack((qshift_data, np.zeros(len(qshift_data))))
        guess_decay = np.zeros(data_len)
        guess_decay[: data_len - decay_max_pos] = decay[decay_max_pos:]
        guess_decay -= decay_background
        guess_decay[guess_decay < 0] = 0
        conv = scipy.signal.fftconvolve(irf / irf.sum(), guess_decay, mode="full")[
            : len(guess_decay)
        ]
        guess_decay = (
            guess_decay * ((decay_max - decay_background) / conv.max())
        ).astype(int)
        pchiped_irf = scipy.interpolate.PchipInterpolator(
            np.arange(0, len(irf)), irf, extrapolate=True
        )
        chi_sqr_best = 1e9
        qshift_suggested = 0
        if self.disp:
            progress = Progress()
            progress.start()
            task_qshift = progress.add_task(
                "[red]Tail-fitting...", total=len(qshift_data[:, 0])
            )
        for qshift in qshift_data[:, 0]:
            irf_shifted = pchiped_irf(np.arange(-qshift, len(irf) - qshift - 0.01))
            irf_shifted = irf_shifted / irf_shifted.sum()
            conv = scipy.signal.convolve(irf_shifted, guess_decay, mode="full")[
                : len(guess_decay)
            ]
            conv = (
                conv * ((decay_max - decay_background) / conv.max()) + decay_background
            )
            chi_sqr = (
                ((decay[qshift_fit_slice] - conv[qshift_fit_slice]) ** 2)
                / decay[qshift_fit_slice]
            ).sum()
            if chi_sqr < chi_sqr_best:
                chi_sqr_best = chi_sqr
                qshift_suggested = qshift
            qshift_data[qshift_data[:, 0] == qshift, 1] = chi_sqr
            if self.disp:
                progress.update(task_qshift, advance=1)
        if self.disp:
            progress.stop()
        # print(qshift_suggested,chi_sqr_best)
        irf_shifted = pchiped_irf(
            np.arange(-qshift_suggested, len(irf) - qshift_suggested - 0.01)
        )
        irf_shifted_max_pos = irf_shifted.argmax()
        irf_shifted_max = irf_shifted.max()
        irf_shifted = irf_shifted / irf_shifted.sum()

        # 寻找最精确的数据区间来做拟合，因为自由度太多，虽然很帅但不是很耐造（你也不希望reduced chi_sqr>2吧.jpg）
        # noise_level = max(decay_max / 500, 10 * decay_background, 10)
        noise_level = max(decay_max / 500,10)
        fit_start = irf_shifted_max_pos
        fit_range_tmp = np.where(decay[decay_max_pos:] < noise_level)[0]
        fit_end = (
            fit_range_tmp[0] + decay_max_pos - 1
            if len(fit_range_tmp) > 0
            else round(0.95 * data_len)
        )

        # 把（可能）有用的存进字典，相信你的记忆力不需要变量名提示doge
        self.info["data_len"] = data_len
        self.info["irf_background"] = irf_background
        self.info["irf_max_pos"] = irf_max_pos
        self.info["irf_max"] = irf_max
        self.info["irf_FWHM"] = irf_FWHM
        self.info["irf_rise_pos"] = irf_rise_pos
        self.info["decay_background"] = decay_background
        self.info["decay_max_pos"] = decay_max_pos
        self.info["decay_max"] = decay_max
        self.info["decay_rise_pos"] = decay_rise_pos
        self.info["qshift_suggested"] = qshift_suggested
        self.info["fit_start"] = fit_start
        self.info["fit_end"] = fit_end
        self.decay = decay
        self.time = time
        self.irf = irf
        if self.disp:
            print("[bold]Preprocess [green]Finished[/green][/bold]:tada:")
            table = Table(title="Data Summary", show_header=False)
            table.add_column("Var", style="cyan")
            table.add_column("Value", style="bright_green")
            for var, value in self.info.items():
                table.add_row(
                    var, str(value) if isinstance(value, int) else f"{value:.4g}"
                )
            print(Panel.fit(table))

    def MEM(self, method="MEM", gpu=True,res_tol = 1e-2):
        """
        干正事了，负责rough guess和后续准确的拟合
        Args:
            method: 使用的方法，可为MEM（最大熵）或SESM（平滑指数序列），SESM很快，挺稳，但背后技术有点玄学
            gpu: 是否使用伟大的pyTorch自动微分加速拟合
            res_tol: 决定什么时候停止拟合，1e-2挺好的
        """
        preexp_tol = 1e-10
        lambda_coeff = 1e-3
        
        torch.set_default_dtype(torch.float64)

        # 取点数据出来
        fit_start = self.info["fit_start"]
        fit_end = self.info["fit_end"]
        # print(fit_start,fit_end)
        qshift_suggested = self.info["qshift_suggested"]
        time1 = self.time[:fit_end]
        irf1 = self.irf[:fit_end]

        # 我们在这里从0.01到100按对数坐标取201个点作为k，没错，是1/tau的k，以后都是如此
        n_rates = 201
        short_rate = 0.01
        long_rate = 100
        def_rates = np.logspace(math.log10(short_rate), math.log10(long_rate), n_rates)

        # 我们tau都知道了，那可以先偷偷卷出201条单指数衰减了，后面的问题仅仅是这201条曲线的线性组合，不用多次卷积
        t_i = np.tile(time1, [n_rates, 1]).T
        k_j = np.tile(def_rates, [fit_end, 1])
        a_ij = np.exp(-k_j * t_i)
        A = np.apply_along_axis(
            scipy.signal.fftconvolve, 0, a_ij, irf1 / irf1.sum(), mode="full"
        )

        # 提前考虑到可能IRF和decay之间有位移，我们先把卷出来的曲线插个值方便平移
        pchip_A = scipy.interpolate.PchipInterpolator(
            np.arange(0, len(A[:, 0])), A, 0, extrapolate=True
        )
        # utils.plot(time1,[A[:,0],A[:,100]])

        decay1 = self.decay[fit_start:fit_end]
        time1 = self.time[fit_start:fit_end]
        # print(fit_start-fit_end)

        # 第一次粗优化，并非考虑拉格朗日乘子
        if self.disp:
            print("[bold]Rough Guess [yellow]Started[/yellow][/bold]")
            
        num_values_to_zero = len(def_rates[def_rates > 10])
        A_shifted = pchip_A(
            np.arange(fit_start - qshift_suggested, fit_end - qshift_suggested - 0.01)
        )
        start_point = np.append(
            np.ones(n_rates) / n_rates,
            [
                [
                    self.info["decay_background"],
                    self.info["irf_background"],
                    qshift_suggested,
                ]
            ],
        )
        x_pars = start_point
        lower_bounds = np.append(np.zeros(n_rates), [[0, 0, qshift_suggested - 4]])
        upper_bounds = np.append(np.ones(n_rates), [[50, 50, qshift_suggested + 4]])
        fixed_pars = np.zeros(n_rates + 3)
        fixed_pars[-3:] = 1
        decay_max = self.info["decay_max"]
        # print(A_shifted.shape,decay1.shape) # 做人要的就是谨慎
        start_points = np.zeros((5, n_rates + 3))
        start_points[:, -1] = qshift_suggested
        start_points[0, :-3] = 1 / n_rates
        start_points[1, :-3] = np.random.random(n_rates)
        start_points[2, :-3] = 0
        start_points[3, :-3] = 0.5
        start_points[4, :-3] = 1
        start_points[:, np.r_[0:3, (-num_values_to_zero - 3) : -3]] = 0.0
        mask1 = fixed_pars == 0
        A_shifted1 = torch.from_numpy(A_shifted)
        decay_background = self.info["decay_background"]
        decay11 = torch.from_numpy(decay1)

        # 下面仅仅是定义了几个待优化的函数，就是reduced chi_sqr，但后来发现SESM用于粗优化又快又好，不是不行
        # 闭包伟大，无需多言
        def guess_MEM(pars):
            # x_pars[mask1]=pars
            y_fitted = torch.matmul(A_shifted1, pars) * decay_max + decay_background
            return torch.sum((y_fitted - decay11) ** 2 / decay11) / (
                fit_end - fit_start
            )  # 仅仅返回一个很简单的 reduced chi_sqr

        def guess_MEM2(pars):
            x_pars[mask1] = pars
            y_fitted = np.dot(A_shifted, x_pars[0:-3]) * decay_max + x_pars[-3]
            return ((y_fitted - decay1) ** 2 / decay1).sum() / (
                fit_end - fit_start
            )  # 仅仅返回一个很简单的 reduced chi_sqr

        def guess_ESM(pars):
            # x_pars[mask1]=pars
            smoothness = (torch.diff(pars, 2) ** 2).sum()
            # S_tmp=-(pars*torch.log(pars/pars.sum())).sum()
            y_fitted = torch.matmul(A_shifted1, pars) * decay_max + decay_background
            chi_sqr = torch.sum((y_fitted - decay11) ** 2 / decay11) / (
                fit_end - fit_start
            )
            return chi_sqr + smoothness * 1e-1

        def guess_ESM2(pars):
            # x_pars[mask1]=pars
            smoothness = (np.diff(pars, 2) ** 2).sum()
            # S_tmp=-(pars*torch.log(pars/pars.sum())).sum()
            y_fitted = np.dot(A_shifted, pars) * decay_max + decay_background
            chi_sqr = np.sum((y_fitted - decay1) ** 2 / decay1) / (fit_end - fit_start)
            return chi_sqr + smoothness * 1e-1

        # 350多行，第一个正经拟合终于要开始了
        if gpu == True:
            if method == "MEM":
                res1 = utils.multistart(
                    guess_MEM,
                    start_points[:, mask1],
                    lb=lower_bounds[mask1],
                    ub=upper_bounds[mask1],
                    disp=self.disp
                )
                x_estimate = scipy.signal.savgol_filter(res1.x.numpy(), 50, 3)
            else:
                res1 = utils.multistart(
                    guess_ESM,
                    start_points[:, mask1],
                    lb=lower_bounds[mask1],
                    ub=upper_bounds[mask1],
                    disp=self.disp
                )
                # print(res1.fun.item())
                x_estimate = scipy.signal.savgol_filter(res1.x.numpy(), 50, 3)
        else:
            if method == "MEM":
                res1 = utils.multistart_cpu(
                    guess_MEM2,
                    start_points[:, mask1],
                    lb=lower_bounds[mask1],
                    ub=upper_bounds[mask1],
                    disp=self.disp
                )
            else:
                res1 = utils.multistart_cpu(
                    guess_ESM2,
                    start_points[:, mask1],
                    lb=lower_bounds[mask1],
                    ub=upper_bounds[mask1],
                    disp=self.disp
                )
            x_estimate = scipy.signal.savgol_filter(res1.x, 50, 3)
        
        # 打印出结果陶醉一下吧，其实结果还可以（？）
        if self.disp:
            print("[bold]Rough Guess [green]Finished[/green][/bold]:tada:")
            table = Table(title="Rough Guess Summary",show_header=False)
            table.add_column(style="cyan")
            table.add_column(style="bright_green")
            table.add_row("method", "simple ESM" if method == "MEM" else "SESM")
            table.add_row("backend", "pytorch + scipy" if gpu == True else "scipy")
            table.add_row("qshift", f"{qshift_suggested:.4g}")
            print(Panel.fit(table))
        # utils.logxplot(def_rates,[res1.x])

        # 真是个漫长的旅程，不是吗，终于要开始MEM了
        # 正式拟合和刚才粗拟合类似，不同的是它轮流进行IRF位移和A_i拟合（一起优化容易爆炸），当相邻两轮的结果差距小于给定范围则拟合成功
        fit_res_diff = 1000
        fit_res_old = 10000
        print("[bold]Main Optimization [yellow]Started[/yellow][/bold]")
        runs=0
        while fit_res_diff >= res_tol:
            runs+=1
            if self.disp:
                print(f"[bold]Run [yellow]{runs}[/yellow] Started[/bold]")
                print(f"Optimizing qshift...")
            x_estimate[x_estimate < 1e-4] = preexp_tol

            # start_points=np.append(x_estimate,[self.info("qshift_suggested")])

            def qshift(pars):
                shift_par = pars[0]
                # np.arange(fit_start-1,fit_end-1)
                # print(len(np.arange(fit_start - shift_par, fit_end - shift_par-0.01)))
                A_shifted_tmp = pchip_A(
                    np.arange(fit_start - shift_par, fit_end - shift_par - 0.01)
                )  # magic number，吃屎了，真别相信浮点数吧
                y_fitted = (
                    np.dot(A_shifted_tmp, x_estimate) * decay_max + decay_background
                )
                # print(A_shifted_tmp.shape)
                return ((y_fitted - decay1) ** 2 / decay1).sum() / (fit_end - fit_start)

            start_points[1, -1] -= 0.1
            start_points[2, -1] += 0.1
            res1 = utils.multistart_cpu(
                qshift,
                start_points=start_points[0:3, -1],
                lb=lower_bounds[-1],
                ub=upper_bounds[-1],
                disp=self.disp
            )
            # print(res1)
            qshift_suggested = res1.x[0]
            if self.disp:
                print(f"New qshift = {qshift_suggested:.4g}")
                print(f"Optimizing k distribution...")

            # print(qshift_suggested)
            start_points[:, -1] = qshift_suggested
            start_points[0, :-3] = x_estimate
            A_shifted = pchip_A(
                np.arange(
                    fit_start - qshift_suggested, fit_end - qshift_suggested - 0.01
                )
            )
            # print(A_shifted.shape)
            A_shifted1 = torch.from_numpy(A_shifted)

            def main_MEM(pars):
                # 非常怪问题，GPU优化MEM必爆炸，可能log是autograd不能碰的滑梯（？）
                # 后期补充：并非如此，虽然仍然为log的锅——trust-constr算法中途会越界，出现负数的对数，所以弗能用
                S_tmp = -(pars * torch.log((pars + 1e-10) / (pars.sum() + 1e-10))).sum()
                y_fitted = torch.matmul(A_shifted1, pars) * decay_max + decay_background
                chi_sqr = torch.sum((y_fitted - decay11) ** 2 / decay11) / (
                    fit_end - fit_start
                )
                return chi_sqr - S_tmp * lambda_coeff

            def main_ESM(pars):
                # x_pars[mask1]=pars
                smoothness = (torch.diff(pars, 2) ** 2).sum()
                # S_tmp=-(pars*torch.log(pars/pars.sum())).sum()
                y_fitted = torch.matmul(A_shifted1, pars) * decay_max + decay_background
                chi_sqr = torch.sum((y_fitted - decay11) ** 2 / decay11) / (
                    fit_end - fit_start
                )
                return chi_sqr + smoothness * 1e-1

            def main_MEM2(pars):
                # x_pars[mask1]=pars
                S_tmp = -(pars * np.log((pars + 1e-10) / (pars.sum() + 0.1))).sum()
                # if(len(pars[pars<0])>0):
                #     print(pars[pars<0])
                # print(S_tmp)
                # print(pars)
                y_fitted = np.dot(A_shifted, pars) * decay_max + decay_background
                chi_sqr = np.sum((y_fitted - decay1) ** 2 / decay1) / (
                    fit_end - fit_start
                )
                return chi_sqr - lambda_coeff * S_tmp

            def main_ESM2(pars):
                # x_pars[mask1]=pars
                smoothness = (np.diff(pars, 2) ** 2).sum()
                # S_tmp=-(pars*torch.log(pars/pars.sum())).sum()
                y_fitted = np.dot(A_shifted, pars) * decay_max + decay_background
                chi_sqr = np.sum((y_fitted - decay1) ** 2 / decay1) / (
                    fit_end - fit_start
                )
                return chi_sqr + smoothness * 1e-1

            if method == "MEM":
                if gpu == True:
                    res1 = utils.multistart(
                        main_MEM,
                        start_points[0, mask1],
                        lb=lower_bounds[mask1],
                        ub=upper_bounds[mask1],
                        method="SLSQP",
                        disp=self.disp,
                        single=True
                    )
                    x_estimate = res1.x.numpy()
                    fit_res_diff = fit_res_old - res1.fun.item()
                    fit_res_old = res1.fun.item()
                else:
                    res1 = utils.multistart_cpu(
                        main_MEM2,
                        start_points[0, mask1],
                        lb=lower_bounds[mask1],
                        ub=upper_bounds[mask1],
                        disp=self.disp,
                        single=True
                    )
                    x_estimate = res1.x
                    fit_res_diff = fit_res_old - res1.fun
                    fit_res_old = res1.fun
            else:
                if gpu == True:
                    res1 = utils.multistart(
                        main_ESM,
                        start_points[0, mask1],
                        lb=lower_bounds[mask1],
                        ub=upper_bounds[mask1],
                        disp=self.disp,
                        single=True
                    )
                    x_estimate = res1.x.numpy()
                    fit_res_diff = fit_res_old - res1.fun.item()
                    fit_res_old = res1.fun.item()
                else:
                    res1 = utils.multistart_cpu(
                        main_ESM2,
                        start_points[0, mask1],
                        lb=lower_bounds[mask1],
                        ub=upper_bounds[mask1],
                        disp=self.disp,
                        single=True
                    )
                    x_estimate = res1.x
                    fit_res_diff = fit_res_old - res1.fun
                    fit_res_old = res1.fun
            if self.disp:
                print(f"Cost Function = {fit_res_old:.4g}")
                print(f"[bold]Run [yellow]{runs}[/yellow] Finished[/bold]\n")

        # 提取结果，并储存之
        y_fitted = np.dot(A_shifted, res1.x) * decay_max + decay_background
        self.info["y_fitted"]=y_fitted
        pchiped_irf = scipy.interpolate.PchipInterpolator(
            np.arange(0, len(self.irf)), self.irf, extrapolate=True
        )
        self.info["irf_shifted"]=pchiped_irf(np.arange(-qshift_suggested, len(self.irf) - qshift_suggested - 0.01))
        chi_sqr = np.sum((y_fitted - decay1) ** 2 / decay1) / (fit_end - fit_start)
        self.info["chi_sqr"] = chi_sqr
        self.info["qshift_suggested"]=qshift_suggested
        self.info["residuals"] = (y_fitted - decay1) / np.sqrt(decay1)
        self.k_distribution = x_estimate
        self.k = def_rates

        if self.disp:
            print(f"[bold green]Termination Condition Reached[/bold green]:tada:")
            print("[bold]Main Optimization [green]Finished[/green][/bold]:tada:")
            table = Table(title="Main Optimization Summary",show_header=False)
            table.add_column(style="cyan")
            table.add_column(style="bright_green")
            table.add_row("method", "MEM" if method == "MEM" else "SESM")
            table.add_row("backend", "pytorch + scipy" if gpu == True else "scipy")
            table.add_row("qshift", f"{self.info['qshift_suggested']:.4g}")
            table.add_row("reduced chi square", f"{self.info['chi_sqr']:.4g}")
            print(Panel.fit(table))
        # utils.logxplot(def_rates, [res1.x])

        # print(fixed_pars)

    def postprocess(self):
        """
        用来对寿命分布进行多重高斯拟合，找到峰数量、面积、FWHM等优质数据
        """
        # 写到这里可能人已经起飞，先把寿命分布提取出来，注意是k！
        if self.disp:
            print(f"[bold]Now it's time for Postprocessing[/bold]")
        k_distribution = self.k_distribution
        k = self.k

        # 结果的峰还是挺明显的，用scipy自己的库找就行
        peaks: np.ndarray = scipy.signal.find_peaks(
            k_distribution, height=0.005, distance=5
        )[0]
        peaks = np.array([[k[peak], k_distribution[peak]] for peak in peaks])
        
        # 按照高度排个序
        sorted_indices = np.argsort(peaks[:, 1])[::-1]
        peaks = peaks[sorted_indices]
        if self.disp:
            print(f"{len(peaks[:,0])} peaks are found, doing Gaussian Fit...")
        
        # 峰太多就把小峰扔了
        if len(peaks) > 5:
            peaks = peaks[:5, :]
        # print(peaks)

        # 准备一下高斯找峰的初始值
        guess = np.array([[peak[1], peak[0], peak[0]] for peak in peaks]).flatten()
        lb = np.array([[0, peak[0] / 2, 0] for peak in peaks]).flatten()
        ub = np.array(
            [[k_distribution.max() * 2, peak[0] * 1.5, k.max()] for peak in peaks]
        ).flatten()
        # print(lb,guess,ub)
        # bounds=np.column_stack((lb,ub))
        # print(bounds)

        # 找找我的
        res1 = utils.multiple_gaussian(k, k_distribution, guess, (lb, ub))
        # print(res1)
        res1 = res1.reshape(len(peaks), 3)
        sorted_indices = np.argsort(res1[:, 1])[::-1]
        res1=res1[sorted_indices]

        # 算一下相关数据，存了
        self.info["peak_fit"]=res1
        # print(res1)
        peak_area = res1[:, 0] * res1[:, 2] * math.sqrt(math.pi)
        # res1[:,0]/=sum(peak_area)
        peak_area = peak_area / sum(peak_area)
        peak_FWHM = 2 * (math.sqrt(math.log(2))) * res1[:, 2]
        peak_weight=peak_area/peak_area.sum()
        self.peak_result = [
            [peak[1], peak_area[n], peak_FWHM[n], peak_weight[n]] for n, peak in enumerate(res1)
        ]
        print(self.peak_result)
        # print(peak_weight)
        if self.disp:
            print("[bold]Gaussian Fit [green]Finished[/green][/bold]")
            table = Table(title="Peak Summary", show_header=True)
            table.add_column("ID", style="cyan")
            table.add_column("k", style="bright_green")
            table.add_column("Area", style="bright_green")
            table.add_column("FWHM", style="bright_green")
            table.add_column("Weight", style="bright_green")
            for n, peak in enumerate(self.peak_result):
                table.add_row(
                    str(n+1),f"{peak[0]:.3g}",f"{peak[1]:.3g}",f"{peak[2]:.3g}",f"{(peak[3]/peak_weight.sum()):.3g}"
                )
            print(Panel.fit(table))
        # utils.logxplot(k, [k_distribution, utils.gaussian(k, *(res1.flatten()))])
        # print(self.peak_result)

    def serialize(self):
        """
        将结果序列化为json
        """
        data = {
            'time': self.time,
            'irf': self.irf,
            'decay': self.decay,
            'k': self.k,
            'k_distribution': self.k_distribution,
            'peak_result': self.peak_result,
            'info': self.info,
        }
        json_data = json.dumps(data, cls=NumpyTypeEncoder)
        return json_data
    
    @staticmethod
    def hello():
        """
        面子工程
        """
        f = Figlet(font='isometric3')
        console = Console()
        logo = Text(f.renderText('FluoIt'))
        logo.highlight_words(["/","_"],"bright_green")
        logo.highlight_words(["\\",":"],"bright_cyan")
        console.print(logo,highlight=False)
        console.print("[bold bright_green]FluoIt[/bold bright_green] 1.0.0",highlight=False)
        console.print("Developed by [italic]Edward Kerman[/italic].",highlight=False)
        console.print("Licensed under MIT License.",highlight=False)

class FluoItPlotter:
    """
    把结果画成图的类
    """
    info = {}
    time = None
    decay = None
    y_fitted = None
    irf = None
    k_distribution = None
    k = None
    peak_result = None
    peak_fit=None
    irf_shifted=None
    residuals=None
    save_dir=None
    name=None

    def __init__(self,save_dir=None,name="fit_result") :
        self.info = {}
        self.time = None
        self.decay = None
        self.irf = None
        self.k_distribution = None
        self.k = None
        self.peak_result = None
        self.peak_fit=None
        self.y_fitted=None
        self.irf_shifted=None
        self.residuals=None
        self.save_dir=save_dir
        self.name=name
    
    def from_file(self,file_name):
        """
        读数据、存数据
        """
        with open(file_name, 'r') as file:
            loaded_data = json.load(file)
        self.name=Path(file_name).stem
        self.info=loaded_data["info"]
        self.time=np.array(loaded_data["time"])
        self.irf=np.array(loaded_data["irf"])
        self.decay=np.array(loaded_data["decay"])
        self.y_fitted=np.array(loaded_data["info"]["y_fitted"])
        self.irf_shifted=np.array(loaded_data["info"]["irf_shifted"])
        self.fit_time=self.time[self.info["fit_start"]:self.info["fit_end"]]
        self.residuals=np.array(self.info["residuals"])
        self.peak_fit=np.array(loaded_data["info"]["peak_fit"])
        self.peak_result=np.array(loaded_data["peak_result"])
        self.k_distribution=np.array(loaded_data["k_distribution"])
        self.k=np.array(loaded_data["k"])
   
    def plot_decay(self):
        """
        画时间-荧光强度图，下面附赠一个残差图
        """
        fig = plt.figure(figsize=(5, 4))
        gs = GridSpec(2, 1, height_ratios=[7, 3])
        # fig.suptitle("decay view")
        # 创建第一个子图
        ax1 = fig.add_subplot(gs[0])
        # ax1.scatter(df['time'], df['fluor_counts'], label='Fluor Counts', color='blue', alpha=0.6)
        ax1.scatter(self.time, self.decay, label='Experiment', alpha=0.6, marker='o',s=1,edgecolors='none',color="#66ccee")
        time_shifted=self.info["qshift_suggested"]*(self.time[2]-self.time[1])
        ax1.plot(self.time, self.irf_shifted, label=f'IRF (shifted ${time_shifted:.2f}$ ns)', linewidth=0.5,color="#ccbb44")
        ax1.plot(self.fit_time, self.y_fitted, label='Fit', linewidth=1.5,color="#ee6677")
        ax1.set_yscale('log')  # Y轴对数坐标
        ax1.legend()  # 显示图例
        ax1.set_ylabel('Counts (log scale)')  # Y轴标签
        ax1.set_ylim(bottom=1)
        ax1.get_yaxis().set_label_coords(-0.1,0.5)

        # 创建第二个子图
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax2.plot(self.fit_time, self.residuals, label='Residuals', linewidth=0.3,color="#ee6677")
        ax2.set_xlabel('Time')  # X轴标签
        ax2.set_ylabel('Residuals')  # Y轴标签
        ax2.get_yaxis().set_label_coords(-0.1,0.5)
        ax2.text(0.95, 0.9, r'$\chi_{\rm R}^2 = '+f'{self.info["chi_sqr"]:.4g}$',  ha='right', va='top', transform=plt.gca().transAxes,bbox=dict(boxstyle='square,pad=0.3', edgecolor='none', facecolor='white'))


        # 显示图表
        # plt.show()
        if self.save_dir is not None:
            folder = Path(self.save_dir)
            folder = folder.resolve().parent if folder.is_file() else folder.resolve()
            plt.savefig(folder/(self.name+"_decay.png"), bbox_inches='tight',dpi=600)

    def plot_peaks(self):
        """
        画寿命分布图
        """
        fig, ax = plt.subplots(figsize=(5, 2))
        ax.set_xlabel(r'$\tau$')  # X轴标签
        # fig.set_ylabel('Residuals')  # Y轴标签
        ax.set_ylabel('Peak Height')
        ax.get_yaxis().set_label_coords(-0.1,0.5)
        ax.set_xscale("log")
        ax.set_ylim(top=self.k_distribution.max()*1.4)

        # 怂，这个时候k换成tau了
        ax.plot(1/self.k,self.k_distribution,linestyle='-',linewidth=0.5,color="black")
        alpha=self.peak_result[:,3]/(self.peak_result[:,3].sum())
        for n,peak in enumerate(self.peak_fit):
            gauss_peak=peak[0]*np.exp(-((self.k-peak[1])/peak[2])**2)
            # ax.plot(self.k, gauss_peak, line)
            ax.fill_between(1/self.k, 0, gauss_peak, alpha=0.5,label=f"$"+r"\tau"+f" = {1/peak[1]:.3g}, "+r"\alpha"+f" = {alpha[n]:.3g}$")
        ax.legend()  # 显示图例
        # 显示图表
        # plt.show()
        if self.save_dir is not None:
            folder = Path(self.save_dir)
            folder = folder.resolve().parent if folder.is_file() else folder.resolve()
            plt.savefig(folder/(self.name+"_peaks.png"), bbox_inches='tight',dpi=600)
    
    def show_fig(self):
        plt.show()

    def save_fig(self):
        plt.savefig("figs/decc1.png", bbox_inches='tight',dpi=600)

if __name__ == "__main__":
    
    # 这下面全是面子工程，有点臭长就不介绍了
    RichHelpFormatter.group_name_formatter = str.upper
    RichHelpFormatter.styles["argparse.args"] = "bright_green"
    RichHelpFormatter.styles["argparse.groups"] = "cyan"
    parser = argparse.ArgumentParser(formatter_class=RichHelpFormatter)
    solver = FluoItSolver(disp=False)
    subparsers = parser.add_subparsers(dest='command')
    # group = parser.add_mutually_exclusive_group(required=False)
    fit_parser = subparsers.add_parser('fit', help='Fit decay data using MEM or SESM',formatter_class=RichHelpFormatter)
    fit_parser.add_argument('-i','--input', help="The location of decay file",required=True)
    fit_parser.add_argument('-o','--output', help="Output json location", default="fit_result.json")
    # group.add_argument('-p','--plot', help="the location of decay file")
    fit_parser.add_argument('-m','--method', choices=('MEM', 'SESM'), default='MEM',help="The method FluoIt uses, can be MEM ([bold dark_cyan]M[/bold dark_cyan]ax [bold dark_cyan]E[/bold dark_cyan]ntropy [bold dark_cyan]M[/bold dark_cyan]ethod) or SESM ([bold dark_cyan]S[/bold dark_cyan]moothed [bold dark_cyan]E[/bold dark_cyan]xponential [bold dark_cyan]S[/bold dark_cyan]eries [bold dark_cyan]M[/bold dark_cyan]ethod)")
    fit_parser.add_argument('-nt','--notorch', action='store_true', help="Add it to disable pytorch autograd")
    fit_parser.add_argument('--tol', type=float, help="Tolerance (Termination Condition) for the Main Optimization")
    parser.add_argument('-q', '--quiet', action='store_true', help="Do not print FluoIt log messages")
    parser.add_argument('-v', '--version', action='store_true', help="Print the version of FluoIt")
    plot_parser = subparsers.add_parser('plot', help='Plot the results by FluoIt',formatter_class=RichHelpFormatter)
    plot_parser.add_argument('-i','--input', help="The location of fit result", default="fit_result.json")
    plot_parser.add_argument('-o','--output', help="Output folder location", default="plots/")
    plot_parser.add_argument('--show', action='store_true', help="Show plots")
    args=parser.parse_args()
    if args.version==True:
        # 踏平坎坷成大道！黑神话·悟空MJN——7分！
        solver.hello()
    elif args.command=="fit":
        
        try:
            solver.disp=not args.quiet
            solver.from_file(args.input)
            solver.preprocess()
            solver.MEM(args.method, not args.notorch,res_tol=args.tol if args.tol is not None else (1e-2 if args.notorch else 1e-3))
            solver.postprocess()
            json_str=solver.serialize()
            try:
                with open(args.output, 'w') as file:
                    file.write(json_str)
                print(f"[bold][green]Results saved[/green][/bold] to {args.output}:tada:")
            except Exception as e:
                print(f"[bold red][Error][/bold red]: {e}")
                answer=Prompt.ask(f"[bold cyan]Save as default filename[/bold cyan]?", choices=["y", "n"])
                if answer:
                    with open('fit_result.json', 'w') as file:
                        file.write(json_str)
        except Exception as e:
            print(f"[bold red][Error][/bold red]: {e}")
        
            
    elif args.command=="plot":
        # print("not implemented yet!")
        try:
            plotter=FluoItPlotter(args.output)
            plotter.from_file(args.input)
            plotter.plot_decay()
            plotter.plot_peaks()
            if args.show==True:
                plotter.show_fig()
        except Exception as e:
            print(f"[bold red][Error][/bold red]: {e}")
    else:
        solver.hello()
        parser.print_help()
    # json_str=solver.serialize()
    # print(info)
