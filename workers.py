import os
import requests
import time
from PySide6.QtCore import QObject, QRunnable, Signal


class WorkerSignals(QObject):
    auth_complete = Signal(dict)
    auth_failed = Signal(str)
    search_complete = Signal(list)
    search_failed = Signal(str)
    image_downloaded = Signal(str, str, str)  # game name, image path, official game name
    finished = Signal()


class LegacyIGDBAuthWorker(QRunnable):
    def __init__(self, client_id, client_secret):
        super().__init__()
        self.client_id = client_id
        self.client_secret = client_secret
        self.signals = WorkerSignals()
    
    def run(self):
        try:
            url = "https://id.twitch.tv/oauth2/token"
            
            payload = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials"
            }
            
            response = requests.post(url, data=payload)
            response.raise_for_status()
            
            data = response.json()
            if "access_token" in data:
                auth_data = {
                    "client_id": self.client_id,
                    "access_token": data["access_token"],
                    "expires_at": time.time() + data["expires_in"]
                }
                self.signals.auth_complete.emit(auth_data)
            else:
                self.signals.auth_failed.emit("Authentication failed: No access token received")
                
        except Exception as e:
            self.signals.auth_failed.emit(f"Authentication failed: {str(e)}")
        finally:
            self.signals.finished.emit()


class LegacyIGDBGameSearchWorker(QRunnable):
    def __init__(self, auth_data, game_name):
        super().__init__()
        self.auth_data = auth_data
        self.game_name = game_name
        self.signals = WorkerSignals()
    
    def run(self):
        try:
            if not self.auth_data or not self.auth_data.get("client_id") or not self.auth_data.get("access_token"):
                self.signals.search_failed.emit("Authentication data missing")
                return
            
            url = "https://api.igdb.com/v4/games"
            
            query = f'search "{self.game_name}"; fields name,cover.url,cover.image_id; limit 10;'
            
            headers = {
                'Client-ID': self.auth_data["client_id"],
                'Authorization': f'Bearer {self.auth_data["access_token"]}',
                'Accept': 'application/json'
            }
            
            response = requests.post(url, headers=headers, data=query)
            response.raise_for_status()
            
            games = response.json()
            
            for game in games:
                if "cover" in game:
                    cover = game["cover"]
                    if "image_id" in cover:
                        thumb_url = f"https://images.igdb.com/igdb/image/upload/t_micro/{cover['image_id']}.jpg"
                        thumb_response = requests.get(thumb_url)
                        if thumb_response.ok:
                            game["thumb_data"] = thumb_response.content
            
            self.signals.search_complete.emit(games)
            
        except Exception as e:
            self.signals.search_failed.emit(f"Game search failed: {str(e)}")
        finally:
            self.signals.finished.emit()


class LegacyIGDBImageDownloadWorker(QRunnable):
    def __init__(self, auth_data, game_data, destination_folder):
        super().__init__()
        self.auth_data = auth_data
        self.game_data = game_data
        self.destination_folder = destination_folder
        self.signals = WorkerSignals()
    
    def make_safe_filename(self, name):
        safe_name = name.lower().replace(" ", "_")
        for char in [':', '/', '\\', '*', '?', '"', '<', '>', '|', '.']:
            safe_name = safe_name.replace(char, "_")
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c in ['_', '-'])
        return safe_name
    
    def run(self):
        try:
            if not self.game_data:
                self.signals.search_failed.emit("No game data available")
                return
            
            if "cover" not in self.game_data or not self.game_data["cover"]:
                self.signals.search_failed.emit("No cover image available")
                return
                
            cover_data = self.game_data["cover"]
            if "image_id" not in cover_data:
                self.signals.search_failed.emit("Cover image ID not found")
                return
                
            image_id = cover_data["image_id"]
            image_url = f"https://images.igdb.com/igdb/image/upload/t_cover_big/{image_id}.jpg"
            
            try:
                max_retries = 3
                retry_count = 0
                while retry_count < max_retries:
                    try:
                        response = requests.get(image_url, timeout=15)  
                        response.raise_for_status()
                        break
                    except requests.exceptions.RequestException as e:
                        retry_count += 1
                        if retry_count >= max_retries:
                            raise
                        time.sleep(1)
            except requests.exceptions.RequestException as e:
                self.signals.search_failed.emit(f"Failed to download image: {str(e)}")
                return
            
            try:
                os.makedirs(self.destination_folder, exist_ok=True)
            except OSError as e:
                self.signals.search_failed.emit(f"Failed to create image directory: {str(e)}")
                return
            
            try:
                safe_name = self.make_safe_filename(self.game_data["name"])
                file_path = os.path.join(self.destination_folder, f"{safe_name}.jpg")
                
                if len(response.content) < 100:  
                    self.signals.search_failed.emit("Downloaded image is too small or empty")
                    return
                
                temp_path = file_path + ".tmp"
                with open(temp_path, 'wb') as f:
                    f.write(response.content)
                
                if os.path.exists(file_path):
                    os.unlink(file_path)
                os.rename(temp_path, file_path)
                
                if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                    self.signals.search_failed.emit("Failed to save image file")
                    return
                
                try:
                    from PySide6.QtGui import QImageReader
                    reader = QImageReader(file_path)
                    if not reader.canRead():
                        os.unlink(file_path)  
                        self.signals.search_failed.emit("Downloaded file is not a valid image")
                        return
                except Exception:
                    pass
                
                self.signals.image_downloaded.emit(self.game_data["name"], file_path, self.game_data["name"])
            except IOError as e:
                self.signals.search_failed.emit(f"Failed to save image: {str(e)}")
                return
            except Exception as e:
                self.signals.search_failed.emit(f"Error processing image: {str(e)}")
                return
            
        except Exception as e:
            self.signals.search_failed.emit(f"Image download failed: {str(e)}")
        finally:
            self.signals.finished.emit()


class LegacyAPITestWorker(QRunnable):
    def __init__(self, auth_data):
        super().__init__()
        self.auth_data = auth_data
        self.signals = WorkerSignals()
    
    def run(self):
        try:
            url = "https://api.igdb.com/v4/platforms"
            query = "fields name; limit 1;"
            
            headers = {
                'Client-ID': self.auth_data["client_id"],
                'Authorization': f'Bearer {self.auth_data["access_token"]}',
                'Accept': 'application/json'
            }
            
            response = requests.post(url, headers=headers, data=query)
            response.raise_for_status()
            
            data = response.json()
            
            if isinstance(data, list) and len(data) > 0:
                self.signals.auth_complete.emit(True)
            else:
                self.signals.auth_failed.emit("API returned unexpected data format")
        
        except Exception as e:
            self.signals.auth_failed.emit(f"API connection failed: {str(e)}")
        finally:
            self.signals.finished.emit()


class IGDBGameSearchWorker(QRunnable):
    def __init__(self, game_name):
        super().__init__()
        self.game_name = game_name
        self.signals = WorkerSignals()
    
    def run(self):
        try:
            url = "https://ambidex-igdb.netlify.app/api/igdb"
            
            params = {'search': self.game_name}
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            
            games = response.json()
            
            if isinstance(games, dict) and 'error' in games:
                self.signals.search_failed.emit(f"API error: {games['error']}")
                return
            
            for game in games:
                if "cover" in game and "image_id" in game["cover"]:
                    thumb_url = f"https://images.igdb.com/igdb/image/upload/t_micro/{game['cover']['image_id']}.jpg"
                    try:
                        thumb_response = requests.get(thumb_url, timeout=10)
                        if thumb_response.ok:
                            game["thumb_data"] = thumb_response.content
                    except Exception:
                        pass
            
            self.signals.search_complete.emit(games)
            
        except requests.exceptions.RequestException as e:
            self.signals.search_failed.emit(f"Game search failed: {str(e)}")
        except ValueError as e:
            self.signals.search_failed.emit(f"Invalid response from server: {str(e)}")
        except Exception as e:
            self.signals.search_failed.emit(f"Game search failed: {str(e)}")
        finally:
            self.signals.finished.emit()


class IGDBImageDownloadWorker(QRunnable):
    def __init__(self, game_data, destination_folder):
        super().__init__()
        self.game_data = game_data
        self.destination_folder = destination_folder
        self.signals = WorkerSignals()
    
    def make_safe_filename(self, name):
        safe_name = name.lower().replace(" ", "_")
        for char in [':', '/', '\\', '*', '?', '"', '<', '>', '|', '.']:
            safe_name = safe_name.replace(char, "_")
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c in ['_', '-'])
        return safe_name
    
    def run(self):
        try:
            if not self.game_data:
                self.signals.search_failed.emit("No game data available")
                return
            
            if "cover" not in self.game_data or not self.game_data["cover"]:
                self.signals.search_failed.emit("No cover image available")
                return
                
            cover_data = self.game_data["cover"]
            if "image_id" not in cover_data:
                self.signals.search_failed.emit("Cover image ID not found")
                return
                
            image_id = cover_data["image_id"]
            image_url = f"https://images.igdb.com/igdb/image/upload/t_cover_big/{image_id}.jpg"
            
            try:
                max_retries = 3
                retry_count = 0
                while retry_count < max_retries:
                    try:
                        response = requests.get(image_url, timeout=15)  
                        response.raise_for_status()
                        break
                    except requests.exceptions.RequestException as e:
                        retry_count += 1
                        if retry_count >= max_retries:
                            raise
                        time.sleep(1)
            except requests.exceptions.RequestException as e:
                self.signals.search_failed.emit(f"Failed to download image: {str(e)}")
                return
            
            try:
                os.makedirs(self.destination_folder, exist_ok=True)
            except OSError as e:
                self.signals.search_failed.emit(f"Failed to create image directory: {str(e)}")
                return
            
            try:
                safe_name = self.make_safe_filename(self.game_data["name"])
                file_path = os.path.join(self.destination_folder, f"{safe_name}.jpg")
                
                if len(response.content) < 100:  
                    self.signals.search_failed.emit("Downloaded image is too small or empty")
                    return
                
                temp_path = file_path + ".tmp"
                with open(temp_path, 'wb') as f:
                    f.write(response.content)
                
                if os.path.exists(file_path):
                    os.unlink(file_path)
                os.rename(temp_path, file_path)
                
                if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                    self.signals.search_failed.emit("Failed to save image file")
                    return
                
                try:
                    from PySide6.QtGui import QImageReader
                    reader = QImageReader(file_path)
                    if not reader.canRead():
                        os.unlink(file_path)  
                        self.signals.search_failed.emit("Downloaded file is not a valid image")
                        return
                except Exception:
                    pass
                
                self.signals.image_downloaded.emit(self.game_data["name"], file_path, self.game_data["name"])
            except IOError as e:
                self.signals.search_failed.emit(f"Failed to save image: {str(e)}")
                return
            except Exception as e:
                self.signals.search_failed.emit(f"Error processing image: {str(e)}")
                return
            
        except Exception as e:
            self.signals.search_failed.emit(f"Image download failed: {str(e)}")
        finally:
            self.signals.finished.emit()
