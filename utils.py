import os
import json
import requests
import re
import subprocess
import sys
import ctypes
from ctypes import wintypes
import platform
import winreg


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
    try:
        path = os.path.normpath(path)
        
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.run(['open', path], check=True)
        else:
            subprocess.run(['xdg-open', path], check=True)
        return True
    except Exception as e:
        print(f"Failed to open directory: {e}")
        return False

def fetch_pcgamingwiki_save_locations(game_name):
    """
    Fetch save game locations from PCGamingWiki API using sections
    Returns a dictionary of store types and their save paths
    """
    save_locations = {}
    
    try:
        # Step 1: Use opensearch to get the exact wiki page title
        search_url = f"https://www.pcgamingwiki.com/w/api.php?action=opensearch&format=json&search={game_name.replace(' ', '%20')}&formatversion=2"
        
        response = requests.get(search_url)
        response.raise_for_status()
        search_data = response.json()
        
        if not search_data[1] or len(search_data[1]) == 0:
            return {}
            
        wiki_page_title = search_data[1][0]
        wiki_page_url = search_data[3][0]
        wiki_page_name = wiki_page_url.split('/')[-1]
        
        # Step 2: Get the sections to find the save location section index
        sections_url = f"https://www.pcgamingwiki.com/w/api.php?action=parse&format=json&page={wiki_page_name}&prop=sections&formatversion=2"
        
        response = requests.get(sections_url)
        response.raise_for_status()
        sections_data = response.json()
        
        if 'error' in sections_data:
            return {}
        
        if 'parse' not in sections_data:
            return {}
        
        # Find the "Save game data location" section
        save_section_index = None
        
        for section in sections_data['parse']['sections']:
            if section['line'] == 'Save game data location':
                save_section_index = section['index']
                break
        
        if not save_section_index:
            return {}
        
        # Step 3: Get the content of the save location section
        content_url = f"https://www.pcgamingwiki.com/w/api.php?action=parse&format=json&page={wiki_page_name}&section={save_section_index}&formatversion=2"
        
        response = requests.get(content_url)
        response.raise_for_status()
        content_data = response.json()
        
        if 'error' in content_data:
            return {}
        
        if 'parse' not in content_data:
            return {}
        
        # extract paths from the HTML content
        html_content = content_data['parse']['text']
        
        # pattern to match rows in the table
        row_pattern = r'<th\s+scope="row"\s+class="table-gamedata-body-system">(.*?)</th>\s*?<td\s+class="table-gamedata-body-location"><span[^>]*>(.*?)</span></td>'
        store_rows = re.findall(row_pattern, html_content, re.DOTALL)
        
        split_rows = []

        for row in store_rows:
            store_type = row[0].strip()
            path_html = row[1]

            # split the path_html by <br> tags
            path_html_parts = re.split(r'<br\s*/?>', path_html)
            if len(path_html_parts) > 1:
                for index, part in enumerate(path_html_parts):
                    # clean up the path - remove HTML tags
                    path = re.sub(r'<[^>]*>', '', part)
                    path = path.strip()
                    split_rows.append((f"{store_type} [{str(index + 1)}]", path))
            else:
                # clean up the path - remove HTML tags
                path = re.sub(r'<[^>]*>', '', path_html)
                path = path.strip()
                split_rows.append((store_type, path))

        print(split_rows)

        for row in split_rows:
            store_type = row[0].strip()
            path = row[1]
            
            # normalize backslashes for Windows paths
            path = re.sub(r'\\+', '\\\\', path)
            
            # replace common environment variables
            try:
                if '%USERPROFILE%' in path:
                    if '%USERPROFILE%\\Documents' in path:
                        # use wintypes to find actual documents folder
                        CSIDL_PERSONAL = 5
                        SHGFP_TYPE_CURRENT = 0 
                        
                        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
                        ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)
                        documents = buf.value
                        
                        path = path.replace('%USERPROFILE%\\Documents', documents)
                    else:
                        user_profile = os.path.expandvars('%USERPROFILE%')
                        path = path.replace('%USERPROFILE%', user_profile)
                if '%APPDATA%' in path:
                    appdata = os.path.expandvars('%APPDATA%')
                    path = path.replace('%APPDATA%', appdata)
                if '%LOCALAPPDATA%' in path:
                    localappdata = os.path.expandvars('%LOCALAPPDATA%')
                    path = path.replace('%LOCALAPPDATA%', localappdata)
                if '%PUBLIC%' in path:
                    public = os.path.expandvars('%PUBLIC%')
                    path = path.replace('%PUBLIC%', public)
                if '%PROGRAMDATA%' in path:
                    programdata = os.path.expandvars('%PROGRAMDATA%')
                    path = path.replace('%PROGRAMDATA%', programdata)
            except Exception as e:
                print(f"Error expanding environment variables: {e}")
            save_locations[store_type] = path
            print(f"Store Type: {store_type}, Path: {path}")
            print(save_locations)
        
        return save_locations
        
    except requests.exceptions.RequestException as e:
        print(f"Network request failed: {e}")
        return {}
    except Exception as e:
        print(f"Unexpected error fetching PCGamingWiki data: {e}")
        return {}

def extract_between_tags(text, start_tag, end_tag):
    """Helper function to extract content between tags"""
    result = []
    start_len = len(start_tag)
    end_len = len(end_tag)
    
    current_pos = 0
    while True:
        start_pos = text.find(start_tag, current_pos)
        if start_pos == -1:
            break
            
        start_pos += start_len
        end_pos = text.find(end_tag, start_pos)
        
        if end_pos == -1:
            break
            
        content = text[start_pos:end_pos]
        result.append(content)
        current_pos = end_pos + end_len
        
    return result

def get_igdb_api_source(config):
    api_source = config.get("igdb_api_source", "ambidex")
    
    if api_source == "legacy" and config.get("igdb_auth"):
        from workers import LegacyIGDBGameSearchWorker, LegacyIGDBImageDownloadWorker
        return {
            "search_worker": LegacyIGDBGameSearchWorker,
            "image_worker": LegacyIGDBImageDownloadWorker,
            "needs_auth": True
        }
    else:
        # Always default to Ambidex API if legacy auth is missing
        from workers import IGDBGameSearchWorker, IGDBImageDownloadWorker
        return {
            "search_worker": IGDBGameSearchWorker,
            "image_worker": IGDBImageDownloadWorker,
            "needs_auth": False
        }

def get_windows_accent_color():
    """
    Tries to get the Windows accent color.
    Returns a hex color string (e.g., "#RRGGBB") or a default blue if not found/not on Windows.
    """
    if platform.system() == "Windows":
        try:
            # The DWM AccentColor is an ABGR value (alpha, blue, green, red)
            # e.g., 0xAABBGGRR
            key_path = r"Software\\Microsoft\\Windows\\DWM"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
            accent_color_dword, _ = winreg.QueryValueEx(key, "AccentColor")
            winreg.CloseKey(key)
            
            # Extract R, G, B components
            # alpha = (accent_color_dword >> 24) & 0xFF
            blue  = (accent_color_dword >> 16) & 0xFF
            green = (accent_color_dword >> 8) & 0xFF
            red   = accent_color_dword & 0xFF
            return f"#{red:02x}{green:02x}{blue:02x}"
        except Exception:
            # Fallback if registry access fails or key/value not found
            pass
    return "#0078D4" # Default blue for non-Windows or if detection fails

def is_windows_11_or_later():
    """
    Checks if the current OS is Windows 11 or later based on the build number.
    """
    if platform.system() == "Windows":
        try:
            # platform.version() gives something like '10.0.22621' for Win11
            # Windows 11 official release build is 22000
            version_parts = platform.version().split('.')
            if len(version_parts) >= 3:
                build_number = int(version_parts[2])
                return build_number >= 22000
        except (ValueError, IndexError):
            # Could not parse version string
            pass
    return False
