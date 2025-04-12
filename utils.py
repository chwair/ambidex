import os
import json
from pathlib import Path

def make_safe_filename(name):
    safe_name = name.lower().replace(" ", "_")
    for char in [':', '/', '\\', '*', '?', '"', '<', '>', '|', '.']:
        safe_name = safe_name.replace(char, "_")
    safe_name = ''.join(c for c in safe_name if c.isalnum() or c in ['_', '-'])
    return safe_name

def load_config(config_file):
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return {"backup_dir": "", "games": {}}
    return {"backup_dir": "", "games": {}}

def save_config(config_file, config):
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=4)

def generate_game_name_suggestions(paths):
    suggestions = set()
    
    for path in paths:
        if os.path.isdir(path):
            folder_name = os.path.basename(path)
            suggestions.add(folder_name.replace('_', ' ').title())
            
            try:
                for subfolder in os.listdir(path):
                    subfolder_path = os.path.join(path, subfolder)
                    if os.path.isdir(subfolder_path):
                        suggestions.add(subfolder.replace('_', ' ').title())
            except (PermissionError, FileNotFoundError):
                pass
        else:
            parent_folder = os.path.basename(os.path.dirname(path))
            if parent_folder:
                suggestions.add(parent_folder.replace('_', ' ').title())
            
            file_name = os.path.splitext(os.path.basename(path))[0]
            if file_name and len(file_name) > 3:  # Avoid very short names
                suggestions.add(file_name.replace('_', ' ').title())
    
    cleaned_suggestions = []
    for suggestion in suggestions:
        if suggestion.lower() not in ['saves', 'saved games', 'savedata', 'save games', 'savegames', 'save files']:
            if not suggestion.lower().endswith(('.sav', '.dat', '.bin', '.json', '.xml')):
                cleaned_suggestions.append(suggestion)
    
    return cleaned_suggestions

def open_directory(path):
    import sys
    import subprocess
    
    try:
        if sys.platform == 'win32':
            subprocess.run(['explorer', path])
        elif sys.platform == 'darwin':
            subprocess.run(['open', path])
        else:
            subprocess.run(['xdg-open', path])
        return True
    except Exception as e:
        print(f"Failed to open directory: {e}")
        return False
