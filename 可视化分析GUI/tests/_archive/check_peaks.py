import sys
sys.path.insert(0, r'D:\北大\光谱工具')

from plot_absorption import load_absorption_spectra, find_absorption_peaks

data = load_absorption_spectra(r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826\20260826RB.csv', skip_metadata=True)[0]
temp_data = {'wl': data['wl'], 'absorption': data['absorption']}
peaks = find_absorption_peaks(temp_data)

print('Type:', type(peaks))
print('Keys:', list(peaks.keys()))
print()
print('Values:')
for k, v in peaks.items():
    print(f'  {k}: type={type(v)}, value={v if not hasattr(v, "shape") else f"array with shape {v.shape}"}')