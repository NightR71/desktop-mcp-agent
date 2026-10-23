import os
import json

def get_settings_path():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(base_dir, "UIsettings.json")

def read_settings():
    defaults = {
        'ball_diameter': 150,
        'opacity': 0.8,
        'color': 'black',
        'font_size': 12,
        'ball_x': None,
        'ball_y': None,
        'hotkey': 'Ctrl+.',
        'stop_hotkey': 'Ctrl+Shift+.',
        'hover_enabled': True,
        'hover_delay': 1000
    }
    path = get_settings_path()
    try:
        with open(path, 'r') as f:
            data = json.load(f)
            defaults.update({k: data.get(k, defaults[k]) for k in defaults})
    except Exception:
        pass
    return defaults

def write_settings(settings):
    path = get_settings_path()
    try:
        with open(path, 'w') as f:
            json.dump(settings, f)
    except Exception:
        pass
