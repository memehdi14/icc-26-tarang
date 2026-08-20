import re

target = r"C:\MMDPublic\Hackathons\TeamOcelleon\projects\tarang-dsp\integration_validation\plot_clinical_ecg_cardiogram.py"
with open(target, "r", encoding="utf-8") as f:
    content = f.read()

new_loader = '''def load_raw_ecg_data(csv_path, fs=250.0):
    """Parses raw ADC sample points from CSV (supporting @E2, @E, [ECG], and legacy formats)."""
    import base64
    val_list = []
    
    with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or row[0].startswith('#'):
                continue
            if len(row) < 3 or row[0] == 'unix_timestamp':
                continue
            
            raw = row[2].strip() if len(row) > 2 else ''
            
            if raw.startswith('@E2,'):
                try:
                    _, enc = raw.split(',', 1)
                    p = base64.b64decode(enc)
                    count = p[8]
                    for i in range(count):
                        off = 9 + i * 13
                        raw_u16 = int.from_bytes(p[off:off+2], 'little', signed=False)
                        val_list.append(raw_u16)
                except Exception:
                    pass
                continue

            if raw.startswith('@E,'):
                parts = raw.split(',')
                if len(parts) > 3:
                    try:
                        val_list.append(int(parts[3]))
                    except ValueError:
                        pass
                continue
            
            m = re.search(r'\\[ECG\\]\\s+raw=([-\\d]+)', raw)
            if m:
                val_list.append(int(m.group(1)))
                continue
            
            m2 = re.search(r'raw=([-\\d]+)', raw)
            if m2:
                val_list.append(int(m2.group(1)))
                continue
            
            if len(row) > 4 and row[2] == 'ECG_RAW' and row[4].lstrip('-').isdigit():
                val_list.append(int(row[4]))
                
    if not val_list or len(val_list) < 50:
        return None, None
        
    raw_adc = np.array(val_list, dtype=float)
    t_sec = np.arange(len(raw_adc)) / fs
    return t_sec, raw_adc'''

pattern = r'def load_raw_ecg_data\(csv_path, fs=250\.0\):.*?(?=def preprocess_ecg)'
updated = re.sub(pattern, new_loader + "\n\n\n", content, flags=re.DOTALL)

with open(target, "w", encoding="utf-8") as f:
    f.write(updated)
print("Successfully patched plot_clinical_ecg_cardiogram.py")
