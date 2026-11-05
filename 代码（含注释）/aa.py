import numpy as np
from scipy.optimize import fsolve
import matplotlib.pyplot as plt
import pandas as pd

# --- 1. 定义系统参数 ---
# 反应焓变 (J/mol)
delta_H1 = -40000.0
delta_H2 = -60000.0
delta_H3 = delta_H2 - delta_H1 # 组合反应的焓变

# 气体常数 (J/mol·K)
R = 8.314

# 参考温度和在该温度下的平衡常数
T_ref = 298.15  # 25 °C
K1_ref = 50.0   # 假设值
K2_ref = 100.0  # 假设值

# 初始浓度 (mol/L)
A0 = 1.0
B0 = 2.0
C0 = 0.0
D0 = 0.0

# --- 2. 定义核心计算函数 ---

def calculate_equilibrium(temp, A0, B0, K1_ref, K2_ref, T_ref, delta_H1, delta_H2):
    """
    在给定温度下，计算平衡浓度。
    """
    # a) 使用范特霍夫方程计算当前温度下的K1和K2
    K1 = K1_ref * np.exp((-delta_H1 / R) * (1/temp - 1/T_ref))
    K2 = K2_ref * np.exp((-delta_H2 / R) * (1/temp - 1/T_ref))

    # b) 定义需求解的非线性方程组
    # x: 反应I消耗的A的量
    # y: 反应II消耗的A的量
    def equations(vars):
        x, y = vars
        # 防止浓度为负或零导致计算错误
        A_eq = A0 - x - y
        B_eq = B0 - x - 2*y
        C_eq = x
        D_eq = y

        # 添加物理约束，防止求解器跑到无效区域
        if A_eq <= 0 or B_eq <= 0 or C_eq < 0 or D_eq < 0:
            return [1e6, 1e6] # 返回一个很大的误差

        eq1 = K1 * A_eq * B_eq - C_eq
        eq2 = K2 * A_eq * (B_eq**2) - D_eq
        return [eq1, eq2]

    # c) 使用fsolve数值求解器求解
    # 初始猜测值，x和y不能太大
    initial_guess = [A0 * 0.1, A0 * 0.1]
    solution = fsolve(equations, initial_guess)
    x, y = solution

    # d) 计算平衡浓度
    A_final = A0 - x - y
    B_final = B0 - x - 2*y
    C_final = x
    D_final = y

    return A_final, B_final, C_final, D_final, K1, K2

# --- 3. 运行模拟 ---
# 设置温度范围
temperatures = np.linspace(300, 500, 101) # 从约27°C到227°C
results = []

for T in temperatures:
    A, B, C, D, K1, K2 = calculate_equilibrium(T, A0, B0, K1_ref, K2_ref, T_ref, delta_H1, delta_H2)
    
    # 避免除以零
    selectivity = D / C if C > 1e-9 else 0
    k_ratio = K2 / K1 if K1 > 1e-9 else 0
    
    results.append({
        "Temperature (K)": T,
        "[A]": A,
        "[B]": B,
        "[C]": C,
        "[D]": D,
        "Selectivity [D]/[C]": selectivity,
        "K_Ratio (K2/K1)": k_ratio
    })

# 将结果转换为Pandas DataFrame以便于查看
df_results = pd.DataFrame(results)

# --- 4. 展示结果 ---
print("模拟结果预览:")
print(df_results.head())
print("\n...")
print(df_results.tail())


# --- 5. 可视化结果 ---
fig, axs = plt.subplots(3, 1, figsize=(10, 15), sharex=True)
fig.suptitle(f'Equilibrium Simulation (ΔH_III = {delta_H3/1000} kJ/mol)', fontsize=16)

# 图1: 关键指标：选择性 vs K比值
ax1 = axs[0]
ax1.plot(df_results["Temperature (K)"], df_results["Selectivity [D]/[C]"], 'r-', lw=2, label='Actual Selectivity [D]/[C]')
ax1.set_ylabel('Ratio Value')
ax1.set_title('Actual Selectivity vs. Simplified Model Prediction')
ax1.legend(loc='upper left')
ax1.grid(True)
# 创建第二个y轴
ax1_twin = ax1.twinx()
ax1_twin.plot(df_results["Temperature (K)"], df_results["K_Ratio (K2/K1)"], 'b--', lw=2, label='Simplified Model (K_II/K_I)')
ax1_twin.set_ylabel('K_II / K_I')
ax1_twin.legend(loc='upper right')

# 图2: B的平衡浓度变化
ax2 = axs[1]
ax2.plot(df_results["Temperature (K)"], df_results["[B]"], 'g-', lw=2, label='[B] concentration')
ax2.set_title('Concentration of Reactant B vs. Temperature')
ax2.set_ylabel('Concentration [B] (mol/L)')
ax2.legend()
ax2.grid(True)

# 图3: 各物质平衡浓度
ax3 = axs[2]
ax3.plot(df_results["Temperature (K)"], df_results["[A]"], label='[A]')
ax3.plot(df_results["Temperature (K)"], df_results["[B]"], label='[B]')
ax3.plot(df_results["Temperature (K)"], df_results["[C]"], label='[C]')
ax3.plot(df_results["Temperature (K)"], df_results["[D]"], label='[D]')
ax3.set_title('Equilibrium Concentrations of All Species')
ax3.set_xlabel('Temperature (K)')
ax3.set_ylabel('Concentration (mol/L)')
ax3.legend()
ax3.grid(True)


plt.tight_layout(rect=[0, 0, 1, 0.96])
plt.show()