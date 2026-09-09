import sys
sys.path.insert(0, r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\画图')

from plot_absorption import load_absorption_spectra, find_absorption_peaks

# 测试所有文件
files = [
    r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826\20260826RB.csv',
    r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826\20260826Ce6.csv',
    r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826\20260826RBL8i.csv',
]

for f in files:
    print(f"测试: {f.split(chr(92))[-1]}")
    data = load_absorption_spectra(f, skip_metadata=True)[0]
    temp_data = {'wl': data['wl'], 'absorption': data['absorption']}
    peaks = find_absorption_peaks(temp_data)
    print(f"  num_peaks: {peaks.get('num_peaks')}")
    print(f"  peak_wavelengths: {peaks.get('peak_wavelengths')}")
    print(f"  是否有peak_wavelengths: {'peak_wavelengths' in peaks}")
    print(f"  是否有peak_intensities: {'peak_intensities' in peaks}")
    print()