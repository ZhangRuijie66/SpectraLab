from typing import List
import numpy as np
import matplotlib.pyplot as plt
import scipy.optimize
import torch
import gpuminimize
from rich.progress import Progress

def plot(x:np.ndarray,ys:List[np.ndarray]):
    """
    画图小工具，会暂停程序
    Args:
        x: 横坐标
        y: 纵坐标，数组格式，可以提供多组数据在同一图上画出，所有数据数组等长

    Returns:
        并非有
    """
    plt.figure(2)
    for yi in ys:
        plt.plot(x,yi)
    plt.show()
def logyplot(x:np.ndarray,ys:List[np.ndarray]):
    """
    画图小工具，会暂停程序
    Args:
        x: 横坐标
        y: 纵坐标，数组格式，可以提供多组数据在同一图上画出，所有数据数组等长

    Returns:
        并非有
    """
    plt.figure(2)
    for yi in ys:
        plt.semilogy(x,yi)
    plt.ylim(bottom=1)
    plt.show()
def logxplot(x:np.ndarray,ys:List[np.ndarray]):
    """
    画图小工具，会暂停程序
    Args:
        x: 横坐标
        y: 纵坐标，数组格式，可以提供多组数据在同一图上画出，所有数据数组等长

    Returns:
        并非有
    """
    plt.figure(2)
    for yi in ys:
        plt.semilogx(x,yi)
    # plt.ylim(0,1)
    plt.show()

def multistart(func, start_points,lb,ub, disp=False,method="trust-constr",single=False):

    # set up the np.random.RandomState generator
    def minimize1(start_point):
        return gpuminimize.minimize(func, torch.from_numpy(start_point),  method=method,bounds=dict(lb=torch.from_numpy(lb),ub=torch.from_numpy(ub)),max_iter=20000)

    # Generate starting points uniformly within ranges
    best_fun = 1e9
    # TODO: Should initialize best_res with a dummy
    # in case none of the results are Valid
    # best_fun = None
    best_res = None
    best_n = -1
    if start_points.ndim>1 or single==False:
        
        if disp:
            progress = Progress()
            progress.start()
            task_minimize = progress.add_task(
                "[red]Multi-Start Minimizing...", total=len(start_points[:,0]) if start_points.ndim>1 else len(start_points)
            )
        for n, x0 in enumerate(start_points):
            res = minimize1(x0)
            if disp:
                progress.update(task_minimize,advance=1)
            # print(res.fun.item())
            # plot(np.arange(0,len(res.x)),[res.x])
            if res.fun.item() < best_fun:
                best_fun = res.fun.item()
                best_res = res
                best_n = n
        if disp:
            progress.stop()
    else:
        res = minimize1(start_points)
        # print(res.fun.item())
        if res.fun.item() < best_fun:
            best_fun = res.fun.item()
            best_res = res
            # best_n = n

    return best_res
def multistart_cpu(func, start_points,lb,ub, disp=False,single = False):

    # set up the np.random.RandomState generator

    # Generate starting points uniformly within ranges
    best_fun = 1e9
    # TODO: Should initialize best_res with a dummy
    # in case none of the results are Valid
    # best_fun = None
    best_res = None
    best_n = -1
    if start_points.ndim>1 or single==False:
        if disp:
            progress = Progress()
            progress.start()
            task_minimize = progress.add_task(
                "[red]Multi-Start Minimizing...", total=len(start_points[:,0]) if start_points.ndim>1 else len(start_points)
            )
        for n, x0 in enumerate(start_points):
            res = scipy.optimize.minimize(func, x0, method="SLSQP",bounds=np.column_stack((lb,ub)),options=dict(maxiter=20000))
            # print(res.success,res.fun)
            if disp:
                progress.update(task_minimize,advance=1)
            if res.success == True and res.fun < best_fun:
                
                best_fun = res.fun
                best_res = res
                best_n = n
        if disp:
            progress.stop()
    else:
        res = scipy.optimize.minimize(func, start_points, method="SLSQP",bounds=np.column_stack((lb,ub)),options=dict(maxiter=20000))
        # print(res)
            # print(res.success,res.fun)
        if res.success == True and res.fun < best_fun:
            best_fun = res.fun
            best_res = res
    return best_res

def gaussian(x,*pars):
    res=np.zeros_like(x)
    for i in range(0, len(pars), 3):
        res+=pars[i]*np.exp(-((x-pars[i+1])/(pars[i+2]))**2)
    return res
def multiple_gaussian(k,real_k_distribution,guess,bounds):
    res,pocv=scipy.optimize.curve_fit(gaussian,k,real_k_distribution,p0=guess,bounds=bounds)
    # print(res)
    # logxplot(k,[real_k_distribution,gaussian(k,*res)])
    return res