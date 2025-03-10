import sys
import os
import json
import datetime
import shutil
import time
import platform
import urllib.parse
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, 
    QPushButton, QFileDialog, QInputDialog, QLineEdit, QScrollArea,
    QGridLayout, QLabel, QMessageBox, QListWidget, QListWidgetItem,
    QListView, QTreeView, QAbstractItemView, QDialog, QRadioButton,
    QButtonGroup, QHBoxLayout, QFormLayout, QLayout, QSizePolicy,
    QMenu
)
from PySide6.QtGui import QPixmap, QIcon, QCursor, QAction, QDrag, QPainter, QColor, QStyleHints
from PySide6.QtCore import Qt, QSize, Signal, QObject, QThread, QMetaObject, Slot, QRunnable, QThreadPool, QPoint, QRect, QMimeData
import requests
import threading

class WorkerSignals(QObject):
    """
    Defines the signals available for worker threads
    """
    auth_complete = Signal(dict)
    auth_failed = Signal(str)
    search_complete = Signal(list)
    search_failed = Signal(str)
    image_downloaded = Signal(str, str, str)  # Game name, image path, official game name
    finished = Signal()


class IGDBAuthWorker(QRunnable):
    """Worker for IGDB authentication using QThreadPool instead of QThread"""
    def __init__(self, client_id, client_secret):
        super().__init__()
        self.client_id = client_id
        self.client_secret = client_secret
        self.signals = WorkerSignals()
    
    def run(self):
        try:
            # Twitch API endpoint for OAuth token
            url = "https://id.twitch.tv/oauth2/token"
            
            payload = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials"
            }
            
            response = requests.post(url, data=payload)
            response.raise_for_status()  # Raise exception for HTTP errors
            
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


class IGDBGameSearchWorker(QRunnable):
    """Worker for IGDB game search using QThreadPool"""
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
            
            # IGDB API endpoint
            url = "https://api.igdb.com/v4/games"
            
            # Construct the APICALYPSE query with small covers
            query = f'search "{self.game_name}"; fields name,cover.url,cover.image_id; limit 10;'
            
            headers = {
                'Client-ID': self.auth_data["client_id"],
                'Authorization': f'Bearer {self.auth_data["access_token"]}',
                'Accept': 'application/json'
            }
            
            response = requests.post(url, headers=headers, data=query)
            response.raise_for_status()
            
            # Get the games with covers
            games = response.json()
            
            # Download small icons for immediate use
            for game in games:
                if "cover" in game:
                    cover = game["cover"]
                    if "image_id" in cover:
                        # Download micro thumbnail
                        thumb_url = f"https://images.igdb.com/igdb/image/upload/t_micro/{cover['image_id']}.jpg"
                        thumb_response = requests.get(thumb_url)
                        if thumb_response.ok:
                            game["thumb_data"] = thumb_response.content
            
            self.signals.search_complete.emit(games)
            
        except Exception as e:
            self.signals.search_failed.emit(f"Game search failed: {str(e)}")
        finally:
            self.signals.finished.emit()


class IGDBImageDownloadWorker(QRunnable):
    """Worker for downloading game cover images using QThreadPool"""
    def __init__(self, auth_data, game_data, destination_folder):
        super().__init__()
        self.auth_data = auth_data
        self.game_data = game_data
        self.destination_folder = destination_folder
        self.signals = WorkerSignals()
    
    def run(self):
        try:
            if not self.game_data:
                self.signals.search_failed.emit("No game data available")
                return
            
            if "cover" not in self.game_data or not self.game_data["cover"]:
                self.signals.search_failed.emit("No cover image available")
                return
                
            # Get cover details from the cover data already in the game object
            cover_data = self.game_data["cover"]
            if "image_id" not in cover_data:
                self.signals.search_failed.emit("Cover image ID not found")
                return
                
            # IGDB uses image IDs that need to be formatted into URLs
            # Using the tall image size for game capsules (t_720p)
            image_id = cover_data["image_id"]
            image_url = f"https://images.igdb.com/igdb/image/upload/t_cover_big/{image_id}.jpg"
            
            # Download the image
            response = requests.get(image_url)
            response.raise_for_status()
            
            # Create the destination folder if it doesn't exist
            os.makedirs(self.destination_folder, exist_ok=True)
            
            # Create a safe filename based on the game name
            safe_name = self.game_data["name"].lower().replace(" ", "_").replace(":", "").replace("/", "_")
            file_path = os.path.join(self.destination_folder, f"{safe_name}.jpg")
            
            with open(file_path, 'wb') as f:
                f.write(response.content)
            
            # Return the game's official name from the API for metadata consistency
            self.signals.image_downloaded.emit(self.game_data["name"], file_path, self.game_data["name"])
            
        except Exception as e:
            self.signals.search_failed.emit(f"Image download failed: {str(e)}")
        finally:
            self.signals.finished.emit()


class APITestWorker(QRunnable):
    """Worker for testing API connections using QThreadPool"""
    def __init__(self, auth_data):
        super().__init__()
        self.auth_data = auth_data
        self.signals = WorkerSignals()
    
    def run(self):
        try:
            # Test a basic API call to confirm the authentication works
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


class IGDBSetupDialog(QDialog):
    # Signal for successful API setup
    setup_complete = Signal(dict)
    
    def __init__(self, parent=None, current_settings=None):
        super().__init__(parent)
        self.setWindowTitle("IGDB API Setup")
        self.resize(500, 300)
        
        self.settings = current_settings or {}
        self.auth_data = None
        
        # Initialize ThreadPool for background tasks
        self.threadpool = QThreadPool.globalInstance()
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        
        # Client ID input
        self.client_id_input = QLineEdit()
        if self.settings.get("client_id"):
            self.client_id_input.setText(self.settings["client_id"])
        form.addRow("Client ID:", self.client_id_input)
        
        # Client Secret input
        self.client_secret_input = QLineEdit()
        if self.settings.get("client_secret"):
            self.client_secret_input.setText(self.settings["client_secret"])
        form.addRow("Client Secret:", self.client_secret_input)
        
        layout.addLayout(form)
        
        # Status label
        self.status_label = QLabel()
        self.status_label.setText("Register for free at https://dev.twitch.tv/console and create an application to get a Client ID and Secret.")
        layout.addWidget(self.status_label)
        
        # Instructions
        instructions = QLabel(
            "1. Go to https://dev.twitch.tv/console\n"
            "2. Register and create a new application\n"
            "3. Set the OAuth Redirect URL to http://localhost\n"
            "4. Set the Category to 'Application Integration'\n"
            "5. Set the Client Type to Confidential\n"
            "6. Copy the Client ID and Client Secret here"
        )
        layout.addWidget(instructions)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        
        self.test_button = QPushButton("Test Connection")
        self.test_button.clicked.connect(self.test_connection)
        buttons_layout.addWidget(self.test_button)
        
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.accept)
        self.save_button.setEnabled(False)
        buttons_layout.addWidget(self.save_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)
        
        layout.addLayout(buttons_layout)
    
    def test_connection(self):
        client_id = self.client_id_input.text().strip()
        client_secret = self.client_secret_input.text().strip()
        
        if not client_id or not client_secret:
            QMessageBox.warning(self, "Missing Information", "Please enter both Client ID and Client Secret")
            return
        
        self.status_label.setText("Testing connection...")
        self.test_button.setEnabled(False)
        
        # Create worker for authentication
        worker = IGDBAuthWorker(client_id, client_secret)
        worker.signals.auth_complete.connect(self.on_auth_complete)
        worker.signals.auth_failed.connect(self.on_auth_failed)
        worker.signals.finished.connect(lambda: self.test_button.setEnabled(True))
        
        # Start worker in thread pool
        self.threadpool.start(worker)
    
    def on_auth_complete(self, auth_data):
        self.auth_data = auth_data
        self.status_label.setText("Authentication successful. Testing API connection...")
        
        # Test making a simple API call to verify the token works
        worker = APITestWorker(auth_data)
        worker.signals.auth_complete.connect(lambda success: self.on_api_test_complete())
        worker.signals.auth_failed.connect(self.on_api_test_failed)
        
        # Start worker in thread pool
        self.threadpool.start(worker)
    
    def on_auth_failed(self, error_message):
        self.status_label.setText(f"Error: {error_message}")
        QMessageBox.critical(self, "Authentication Failed", error_message)
    
    def on_api_test_complete(self):
        self.status_label.setText("Connection successful! The API is accessible.")
        self.save_button.setEnabled(True)
        QMessageBox.information(self, "Success", "IGDB API connection successful!")
    
    def on_api_test_failed(self, error_message):
        self.status_label.setText(f"API Error: {error_message}")
        QMessageBox.critical(self, "API Connection Failed", error_message)


class GameSearchDialog(QDialog):
    def __init__(self, parent=None, auth_data=None, game_name=""):
        super().__init__(parent)
        self.setWindowTitle(f"Search for {game_name}")
        self.resize(600, 400)
        
        self.auth_data = auth_data
        self.game_name = game_name
        self.selected_game = None
        
        # Initialize ThreadPool for background tasks
        self.threadpool = QThreadPool.globalInstance()
        
        self.init_ui()
        self.search_game()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Status label
        self.status_label = QLabel(f"Searching for '{self.game_name}'...")
        layout.addWidget(self.status_label)
        
        # Game list
        self.game_list = QListWidget()
        self.game_list.itemClicked.connect(self.on_game_selected)
        layout.addWidget(self.game_list)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.select_button = QPushButton("Select Game")
        self.select_button.clicked.connect(self.accept)
        self.select_button.setEnabled(False)
        button_layout.addWidget(self.select_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
    
    def search_game(self):
        # Create worker for game search
        worker = IGDBGameSearchWorker(self.auth_data, self.game_name)
        worker.signals.search_complete.connect(self.on_search_complete)
        worker.signals.search_failed.connect(self.on_search_failed)
        
        # Start worker in thread pool
        self.threadpool.start(worker)
    
    def on_search_complete(self, games):
        if not games:
            self.status_label.setText(f"No results found for '{self.game_name}'")
            return
        
        self.status_label.setText(f"Found {len(games)} results for '{self.game_name}'")
        self.game_list.clear()
        
        for game in games:
            item = QListWidgetItem(game["name"])
            item.setData(Qt.UserRole, game)
            self.game_list.addItem(item)
    
    def on_search_failed(self, error_message):
        self.status_label.setText(f"Error: {error_message}")
    
    def on_game_selected(self, item):
        self.selected_game = item.data(Qt.UserRole)
        self.select_button.setEnabled(True)


class SaveSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Game Save Selection")
        self.setMinimumWidth(400)
        
        self.selected_paths = []
        
        layout = QVBoxLayout(self)
        
        # Selection options
        self.option_group = QButtonGroup(self)
        self.files_option = QRadioButton("Select save files")
        self.directory_option = QRadioButton("Define save directory")
        self.option_group.addButton(self.files_option)
        self.option_group.addButton(self.directory_option)
        
        # Default selection
        self.files_option.setChecked(True)
        
        options_layout = QVBoxLayout()
        options_layout.addWidget(self.files_option)
        options_layout.addWidget(self.directory_option)
        layout.addLayout(options_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        proceed_button = QPushButton("Proceed")
        cancel_button = QPushButton("Cancel")
        
        proceed_button.clicked.connect(self.handle_selection)
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(proceed_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
    
    def handle_selection(self):
        if self.files_option.isChecked():
            self.select_files()
        else:
            self.define_directory()
    
    def select_files(self):
        # Custom file dialog that can select files and directories simultaneously
        file_dialog = QFileDialog(self)
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        file_dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        
        # Get the file view and set it to allow directory selection
        file_view = file_dialog.findChild(QListView, "listView")
        if file_view:
            file_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        
        tree_view = file_dialog.findChild(QTreeView)
        if tree_view:
            tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        
        if not file_dialog.exec():
            return  # User cancelled the dialog
        
        self.selected_paths = file_dialog.selectedFiles()
        
        if self.selected_paths:
            self.accept()
        else:
            QMessageBox.warning(self, "No Selection", "Please select at least one file or folder.")
    
    def define_directory(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Select Game Save Directory"
        )
        
        if directory:
            self.selected_paths = [directory]
            self.accept()


class FlowLayout(QLayout):
    """
    Custom flow layout that automatically arranges widgets based on available width
    This allows for a responsive grid layout that adapts to window size changes
    """
    def __init__(self, parent=None, margin=0, spacing=-1):
        super(FlowLayout, self).__init__(parent)
        
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        
        self.item_list = []
    
    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)
    
    def addItem(self, item):
        self.item_list.append(item)
    
    def count(self):
        return len(self.item_list)
    
    def itemAt(self, index):
        if 0 <= index < len(self.item_list):
            return self.item_list[index]
        return None
    
    def takeAt(self, index):
        if 0 <= index < len(self.item_list):
            return self.item_list.pop(index)
        return None
    
    def expandingDirections(self):
        return Qt.Orientation(0)
    
    def hasHeightForWidth(self):
        return True
    
    def heightForWidth(self, width):
        height = self.do_layout(QRect(0, 0, width, 0), True)
        return height
    
    def setGeometry(self, rect):
        super(FlowLayout, self).setGeometry(rect)
        self.do_layout(rect, False)
    
    def sizeHint(self):
        return self.minimumSize()
    
    def minimumSize(self):
        size = QSize()
        
        for item in self.item_list:
            size = size.expandedTo(item.minimumSize())
            
        margin = self.contentsMargins()
        size += QSize(2 * margin.left(), 2 * margin.top())
        return size
    
    def do_layout(self, rect, test_only=False):
        x = rect.x()
        y = rect.y()
        line_height = 0
        spacing = self.spacing()
        
        for item in self.item_list:
            style = item.widget().style()
            layout_spacing_x = style.layoutSpacing(
                QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Horizontal
            ) or spacing
            layout_spacing_y = style.layoutSpacing(
                QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Vertical
            ) or spacing
            
            space_x = layout_spacing_x
            space_y = layout_spacing_y
            
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
                
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
                
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
            
        return y + line_height - rect.y()


class DraggableWidget(QWidget):
    """Custom widget that supports drag & drop for game reordering with visual feedback"""
    game_moved = Signal(str, str)  # Signal emitted when a game is moved (source_name, target_name)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.drag_indicator = None
        self.drop_indicator = QWidget(self)
        self.drop_indicator.setFixedWidth(2)  # Thinner line for cleaner look
        self.drop_indicator.setStyleSheet("background-color: #0078d4;")  # Solid color
        self.drop_indicator.hide()
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.accept()
            self.showDropIndicator(event.pos())
            event.acceptProposedAction()
            QApplication.changeOverrideCursor(Qt.DragMoveCursor)
        else:
            event.ignore()
    
    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.accept()
            self.showDropIndicator(event.pos())
        else:
            event.ignore()
    
    def dragLeaveEvent(self, event):
        self.drop_indicator.hide()
        QApplication.restoreOverrideCursor()
        event.accept()
    
    def dropEvent(self, event):
        self.drop_indicator.hide()
        QApplication.restoreOverrideCursor()
        if event.source():
            event.source().unsetCursor()
        source_name = event.mimeData().text()
        target_widget = self.childAt(event.position().toPoint())
        
        if target_widget and isinstance(target_widget, QWidget):
            # Walk up the widget hierarchy to find the game widget
            while target_widget and not target_widget.property("game_name"):
                target_widget = target_widget.parent()
            
            if target_widget:
                target_name = target_widget.property("game_name")
                if source_name and target_name and source_name != target_name:
                    self.game_moved.emit(source_name, target_name)
        
        event.accept()
    
    def showDropIndicator(self, pos):
        target_widget = self.childAt(pos)
        if target_widget and isinstance(target_widget, QWidget):
            # Walk up the widget hierarchy to find the game widget
            while target_widget and not target_widget.property("game_name"):
                target_widget = target_widget.parent()
            
            if target_widget:
                # Determine if we should show indicator before or after the target
                target_pos = target_widget.pos()
                target_center = target_pos.x() + target_widget.width() / 2
                
                if pos.x() < target_center:
                    # Show indicator before the target
                    self.drop_indicator.setGeometry(
                        target_pos.x() - 1,  # Offset slightly for better visibility
                        target_pos.y(),
                        2,
                        target_widget.height()
                    )
                else:
                    # Show indicator after the target
                    self.drop_indicator.setGeometry(
                        target_pos.x() + target_widget.width() - 1,
                        target_pos.y(),
                        2,
                        target_widget.height()
                    )
                
                self.drop_indicator.setStyleSheet("background-color: #0078d4;")  # Solid color
                self.drop_indicator.raise_()
                self.drop_indicator.show()
                return
        
        self.drop_indicator.hide()

    def start_drag(self, event, widget):
        """Start dragging a game widget"""
        if event.button() == Qt.LeftButton:
            # Create drag pixmap
            pixmap = widget.grab()
            
            # Create slightly transparent version for drag feedback
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            painter.fillRect(pixmap.rect(), QColor(0, 0, 0, 180))
            painter.end()
            
            # Create and setup drag object
            drag = QDrag(widget)
            mime_data = QMimeData()
            mime_data.setText(widget.property("game_name"))
            drag.setMimeData(mime_data)
            drag.setPixmap(pixmap)
            drag.setHotSpot(event.position().toPoint())
            
            # Execute drag operation
            drag.exec(Qt.MoveAction)


class GameSaveBackup(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ambidex")
        self.setMinimumSize(800, 600)
        
        # Set window icon
        icon_path = "icon.ico"
        self.setWindowIcon(QIcon(icon_path))
        
        # Set backup directory to script directory
        self.app_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Initialize config
        self.config_file = os.path.join(self.app_dir, "config.json")
        self.config = self.load_config()
        
        # Ensure backup directory exists
        if not self.config.get("backup_dir"):
            self.config["backup_dir"] = os.path.join(self.app_dir, "backups")
        
        # Create backup directory if it doesn't exist
        os.makedirs(self.config["backup_dir"], exist_ok=True)
        
        # Save the config with the default backup directory
        self.save_config()
        
        # Current game being added - to track the workflow steps
        self.current_game_addition = None
        
        # Check if this is first run
        if not os.path.exists(self.config_file):
            self.show_first_run_dialog()
        
        # Initialize ThreadPool for background tasks
        self.threadpool = QThreadPool.globalInstance()
        
        # Setup UI
        self.init_ui()
    
    def show_first_run_dialog(self):
        """Show first-run dialog to ask about IGDB usage"""
        reply = QMessageBox.question(
            self,
            "Welcome to Ambidex!",
            "Would you like to enable IGDB integration to automatically fetch game covers and metadata?\n\n"
            "This requires a free Twitch account and API key.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if reply == QMessageBox.Yes:
            self.show_api_setup()

    def init_ui(self):
        # Create tab widget
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        # Create tabs
        self.backup_tab = QWidget()
        self.restore_tab = QWidget()
        
        self.tabs.addTab(self.backup_tab, "Backup")
        self.tabs.addTab(self.restore_tab, "Restore")
        
        # Setup Backup Tab
        self.setup_backup_tab()
        
        # Setup Restore Tab
        self.setup_restore_tab()
        
        # Add main menu
        self.setup_menu()
    
    def setup_menu(self):
        menu_bar = self.menuBar()
        
        # Settings menu
        settings_menu = menu_bar.addMenu("Settings")
        
        # IGDB API setup action
        api_setup_action = settings_menu.addAction("IGDB API Setup")
        api_setup_action.triggered.connect(self.show_api_setup)
        
        # Set backup directory action
        backup_dir_action = settings_menu.addAction("Set Backup Directory")
        backup_dir_action.triggered.connect(self.set_backup_directory)
    
    def setup_backup_tab(self):
        layout = QVBoxLayout(self.backup_tab)
        
        # Top buttons layout
        top_buttons = QHBoxLayout()
        
        # Add game button
        self.add_game_button = QPushButton("+ Add Game Save Files")
        self.add_game_button.clicked.connect(self.add_game_save)
        top_buttons.addWidget(self.add_game_button)
        
        # Backup all button
        backup_all_button = QPushButton("Backup All Games")
        backup_all_button.clicked.connect(self.backup_all_games)
        top_buttons.addWidget(backup_all_button)
        
        layout.addLayout(top_buttons)
        
        # Scroll area for game grid
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)  # Remove the frame
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)  # Hide horizontal scrollbar
        
        self.game_grid_widget = DraggableWidget()  # Custom widget that supports drag & drop
        self.game_grid_widget.game_moved.connect(self.on_game_moved)
        
        # Use FlowLayout instead of QGridLayout for dynamic adjustment
        self.game_grid = FlowLayout(self.game_grid_widget)
        self.game_grid.setSpacing(10)  # Add some spacing between game widgets
        self.scroll_area.setWidget(self.game_grid_widget)
        layout.addWidget(self.scroll_area)
        
        # Load existing games
        self.load_games()
        
    def load_games(self):
        # Clear current grid
        while self.game_grid.count():
            item = self.game_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        
        # Add games to grid
        for game_name, game_data in self.config.get("games", {}).items():
            game_widget = self.create_game_widget(game_name, game_data)
            self.game_grid.addWidget(game_widget)
            
    def backup_game(self, game_name, show_message=True):
        game_data = self.config["games"].get(game_name)
        if not game_data:
            return
        
        # Create timestamp for this backup
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Sanitize the game folder name to ensure it's a valid directory name
        game_folder_name = game_name.replace(" ", "_").replace(":", "").replace("/", "_").replace("\\", "_")
        game_folder_name = ''.join(c for c in game_folder_name if c.isalnum() or c in ['_', '-'])
        
        # Ensure backup_dir is absolute and normalized
        backup_base = os.path.abspath(os.path.normpath(self.config["backup_dir"]))
        
        # First ensure the base backup directory exists
        try:
            os.makedirs(backup_base, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(
                self, 
                "Base Backup Directory Error", 
                f"Could not access or create base backup directory: {e}\n\n"
                f"Path: {backup_base}\n\n"
                "Please set a valid backup directory from Settings menu."
            )
            return
            
        # Create the full backup path
        backup_dir = os.path.join(backup_base, game_folder_name, timestamp)
        
        # Now create the game-specific backup directory with timestamp
        try:
            print(f"Creating directory: {backup_dir}")  # Debug output
            os.makedirs(backup_dir, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(
                self, 
                "Backup Directory Error", 
                f"Could not create backup directory: {e}\n\n"
                f"Path: {backup_dir}\n\n"
                "Please check file permissions or set a different backup directory."
            )
            return
        
        # Store the original directory structure for restoration
        parent_dir = game_data.get("parent_dir", "")
        if parent_dir:
            try:
                with open(os.path.join(backup_dir, "parent_dir.txt"), 'w') as f:
                    f.write(parent_dir)
            except Exception as e:
                print(f"Warning: Could not write parent_dir.txt: {e}")
        
        # Copy save files
        success = True  # Track if backup was successful
        
        for save_path in game_data["save_paths"]:
            try:
                # Ensure source path exists
                if not os.path.exists(save_path):
                    QMessageBox.warning(self, "Path Not Found", f"Save path does not exist: {save_path}")
                    success = False
                    continue
                
                # Create relative path for backup to maintain structure
                if parent_dir and save_path.startswith(parent_dir):
                    rel_path = os.path.relpath(save_path, parent_dir)
                    dest_path = os.path.join(backup_dir, rel_path)
                else:
                    dest_path = os.path.join(backup_dir, os.path.basename(save_path))
                
                # Create parent directories if needed
                if os.path.isfile(save_path):
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                
                if os.path.isdir(save_path):
                    # Make sure target directory doesn't exist before copying
                    if os.path.exists(dest_path):
                        shutil.rmtree(dest_path)
                    shutil.copytree(save_path, dest_path)
                else:
                    shutil.copy2(save_path, dest_path)
            except Exception as e:
                QMessageBox.warning(self, "Backup Error", f"Error backing up {save_path}: {e}")
                success = False
                continue
        
        if success:
            # Add backup to config
            backup_info = {
                "timestamp": timestamp,
                "datetime": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "directory": backup_dir
            }
            
            self.config["games"][game_name]["backups"].append(backup_info)
            self.save_config()
            
            if show_message:
                QMessageBox.information(self, "Backup Complete", f"Save files for {game_name} have been backed up successfully!")
            self.update_games_list()  # Update the restore tab
        else:
            # If backup failed, try to clean up the partial backup directory
            try:
                if os.path.exists(backup_dir):
                    shutil.rmtree(backup_dir)
            except Exception as e:
                print(f"Warning: Could not clean up partial backup: {e}")
    
    def backup_all_games(self):
        """Backup all games in the collection"""
        if not self.config["games"]:
            QMessageBox.information(self, "No Games", "No games to backup.")
            return
            
        reply = QMessageBox.question(
            self,
            "Backup All Games",
            f"Are you sure you want to backup all {len(self.config['games'])} games?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if reply == QMessageBox.Yes:
            for game_name in self.config["games"].keys():
                self.backup_game(game_name, False)
            QMessageBox.information(self, "Backup Complete", "All games have been backed up successfully!")

    def update_games_list(self):
        self.games_list.clear()
        
        for game_name in self.config.get("games", {}).keys():
            # Only show games with backups in the restore tab
            if self.config["games"][game_name].get("backups"):
                self.games_list.addItem(game_name)
    
    def show_game_backups(self, item):
        game_name = item.text()
        self.backups_list.clear()
        self.restore_button.setEnabled(False)
        
        game_data = self.config["games"].get(game_name)
        if not game_data:
            return
        
        backups = sorted(game_data.get("backups", []), key=lambda x: x["timestamp"], reverse=True)
        
        for i, backup in enumerate(backups):
            item = QListWidgetItem(f"{backup['datetime']}")
            item.setData(Qt.UserRole, backup)
            
            # Mark the latest backup
            if i == 0:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setText(f"{backup['datetime']} (Latest)")
            
            self.backups_list.addItem(item)
    
    def show_backup_details(self, item):
        self.selected_backup = item.data(Qt.UserRole)
        self.restore_button.setEnabled(True)
    
    def restore_backup(self):
        if not hasattr(self, "selected_backup"):
            return
        
        # Get the game name from the selected item in the games list
        game_name = self.games_list.currentItem().text()
        if not game_name:
            return
        
        game_data = self.config["games"].get(game_name)
        if not game_data:
            return
        
        # Confirm the restore action
        confirm = QMessageBox.question(
            self, 
            "Confirm Restore", 
            f"This will first backup your current saves and then restore the selected backup from {self.selected_backup['datetime']}.\n\nDo you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if confirm != QMessageBox.Yes:
            return
        
        # First backup the current saves
        self.backup_game(game_name)
        
        # Now restore from the selected backup
        backup_dir = self.selected_backup["directory"]
        parent_dir = game_data.get("parent_dir", "")
        
        # Check if parent_dir.txt exists in the backup
        parent_dir_file = os.path.join(backup_dir, "parent_dir.txt")
        if os.path.exists(parent_dir_file):
            with open(parent_dir_file, 'r') as f:
                backup_parent_dir = f.read().strip()
            # Use backup parent dir if it exists and original doesn't
            if backup_parent_dir and not parent_dir:
                parent_dir = backup_parent_dir
        
        for save_path in game_data["save_paths"]:
            try:
                # Determine source based on directory structure
                if parent_dir and save_path.startswith(parent_dir):
                    rel_path = os.path.relpath(save_path, parent_dir)
                    src = os.path.join(backup_dir, rel_path)
                else:
                    base_name = os.path.basename(save_path)
                    src = os.path.join(backup_dir, base_name)
                
                # If source doesn't exist in expected location, try direct backup dir
                if not os.path.exists(src):
                    if os.path.isdir(save_path):
                        # Try to find a directory with matching name
                        for item in os.listdir(backup_dir):
                            if item == os.path.basename(save_path) and os.path.isdir(os.path.join(backup_dir, item)):
                                src = os.path.join(backup_dir, item)
                                break
                    else:
                        # Try to find a file with matching name
                        for item in os.listdir(backup_dir):
                            if item == os.path.basename(save_path) and not os.path.isdir(os.path.join(backup_dir, item)):
                                src = os.path.join(backup_dir, item)
                                break
                
                # Restore the file/directory
                if os.path.exists(src):
                    if os.path.isdir(src):
                        if os.path.exists(save_path):
                            shutil.rmtree(save_path)
                        shutil.copytree(src, save_path)
                    else:
                        shutil.copy2(src, save_path)
                else:
                    QMessageBox.warning(self, "Restore Error", 
                                      f"Could not find {os.path.basename(save_path)} in the backup.")
            except Exception as e:
                QMessageBox.warning(self, "Restore Error", f"Error restoring {save_path}: {e}")
        
        QMessageBox.information(self, "Restore Complete", f"Save files for {game_name} have been restored successfully!")

    def setup_restore_tab(self):
        layout = QVBoxLayout(self.restore_tab)
        
        # Game selection list
        self.games_list = QListWidget()
        self.games_list.itemClicked.connect(self.show_game_backups)
        layout.addWidget(QLabel("Select a game:"))
        layout.addWidget(self.games_list)
        
        # Backup selection list
        self.backups_list = QListWidget()
        self.backups_list.itemClicked.connect(self.show_backup_details)
        layout.addWidget(QLabel("Available backups:"))
        layout.addWidget(self.backups_list)
        
        # Restore button
        self.restore_button = QPushButton("Restore Selected Backup")
        self.restore_button.clicked.connect(self.restore_backup)
        self.restore_button.setEnabled(False)
        layout.addWidget(self.restore_button)
        
        # Update games list
        self.update_games_list()

    def set_backup_directory(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Select Backup Directory", self.config["backup_dir"]
        )
        
        if directory:
            self.config["backup_dir"] = directory
            os.makedirs(directory, exist_ok=True)
            self.save_config()
            QMessageBox.information(self, "Backup Directory", f"Backup directory set to: {directory}")

    def create_game_widget(self, game_name, game_data):
        widget = QWidget()
        widget.setObjectName("gameWidget")
        widget.setMinimumWidth(140)
        widget.setMinimumHeight(200)
        widget.setMaximumWidth(180)
        widget.setStyleSheet("""
            #gameWidget {
                background-color: transparent;
                border: 1px solid transparent;
            }
            #gameWidget:hover {
                background-color: rgba(200, 200, 200, 0.1);
                border: 1px solid #0078d4;
                border-radius: 4px;
            }
        """)
        
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)  # Add some padding
        layout.setSpacing(4)  # Reduce spacing between elements
        
        # Create a container for the image and icon
        image_container = QWidget()
        # Don't set minimum/maximum height to allow natural sizing based on content
        image_layout = QVBoxLayout(image_container)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(0)  # Remove spacing between elements
        
        # Image label
        image_label = QLabel()
        image_label.setStyleSheet("border: none; background: transparent;")
        image_label.setAlignment(Qt.AlignCenter)
        
        # Set fixed dimensions for the image placeholder with correct aspect ratio
        image_width = 120
        image_height = int(image_width * (352/264))  # Maintain original aspect ratio
        
        if game_data.get("image") and os.path.exists(game_data["image"]):
            pixmap = QPixmap(game_data["image"])
            # Scale the image properly maintaining aspect ratio
            image_label.setPixmap(pixmap.scaled(image_width, image_height, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            # Set a fixed size to ensure consistent layout
            image_label.setFixedSize(image_width, image_height)
        else:
            image_label.setText(game_name)
            image_label.setStyleSheet("background-color: #333; color: white; border: 1px solid #555;")
            image_label.setFixedSize(image_width, image_height)
        
        image_layout.addWidget(image_label, 0, Qt.AlignCenter)
        layout.addWidget(image_container, 0, Qt.AlignCenter)
        
        name_label = QLabel(game_name)

        # Light mode and win10 exception
        if QApplication.styleHints().colorScheme() != Qt.ColorScheme.Dark or (platform.release() != "10" or int(platform.version().split('.')[2]) < 22000):
            name_label_col = "303030"
        else:
            name_label_col = "e0e0e0"
        name_label.setStyleSheet(f"border: none; color: #{name_label_col}; padding: 4px 0;")

        name_label.setAlignment(Qt.AlignCenter)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)
        
        # Backup button
        backup_button = QPushButton("Backup Saves")
        backup_button.clicked.connect(lambda: self.backup_game(game_name))
        layout.addWidget(backup_button)
        
        # Store game name and enable drag & drop
        widget.setProperty("game_name", game_name)
        widget.setAcceptDrops(True)
        widget.mousePressEvent = lambda e, w=widget: self.start_drag(e, w)
        
        # Enable context menu
        widget.setContextMenuPolicy(Qt.CustomContextMenu)
        widget.customContextMenuRequested.connect(lambda pos, w=widget: self.show_game_context_menu(pos, w))
        
        return widget

    def start_drag(self, event, widget):
        """Start dragging a game widget"""
        if event.button() == Qt.LeftButton:
            # Create drag pixmap
            pixmap = widget.grab()
            
            # Create slightly transparent version for drag feedback
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            painter.fillRect(pixmap.rect(), QColor(0, 0, 0, 180))
            painter.end()
            
            # Create and setup drag object
            drag = QDrag(widget)
            mime_data = QMimeData()
            mime_data.setText(widget.property("game_name"))
            drag.setMimeData(mime_data)
            drag.setPixmap(pixmap)
            drag.setHotSpot(event.position().toPoint())
            
            # Execute drag operation
            drag.exec(Qt.MoveAction)

    def on_game_moved(self, source_name, target_name):
        """Handle game reordering"""
        if source_name == target_name:
            return
            
        # Get the current order of games
        games = list(self.config["games"].keys())
        source_idx = games.index(source_name)
        target_idx = games.index(target_name)
        
        # Reorder the games
        games.insert(target_idx, games.pop(source_idx))
        
        # Create new ordered dictionary
        new_games = {}
        for game in games:
            new_games[game] = self.config["games"][game]
        
        self.config["games"] = new_games
        self.save_config()
        self.load_games()
        
    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading config: {e}")
                return {"backup_dir": "", "games": {}}
        return {"backup_dir": "", "games": {}}
    
    def save_config(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=4)

    def add_game_save(self):
        # Reset current game addition tracking
        self.current_game_addition = None
        
        # Show save selection dialog
        dialog = SaveSelectionDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        
        selected_paths = dialog.selected_paths
        
        if not selected_paths:
            return
            
        # Get game name from user
        game_name, ok = QInputDialog.getText(
            self, "Game Title", "Enter the game's title:"
        )
        
        if not ok or not game_name:
            return  # User cancelled the game name dialog
        
        # Determine common parent directory for all selected items
        if len(selected_paths) == 1:
            if os.path.isdir(selected_paths[0]):
                save_parent_dir = selected_paths[0]
            else:
                save_parent_dir = os.path.dirname(selected_paths[0])
        else:
            # Find common parent directory
            parent_dirs = [os.path.dirname(path) if not os.path.isdir(path) else path for path in selected_paths]
            common_parent = os.path.commonpath(parent_dirs)
            save_parent_dir = common_parent
        
        # Create temporary game entry to track the current process
        self.current_game_addition = {
            "name": game_name,
            "save_paths": selected_paths,
            "parent_dir": save_parent_dir
        }
        
        # Create game entry in config
        if game_name not in self.config["games"]:
            self.config["games"][game_name] = {
                "save_paths": [],
                "backups": [],
                "image": "",
                "thumb_data": None,  # Add storage for thumbnail data
                "parent_dir": save_parent_dir
            }
        
        # Add save paths from the selection
        for path in selected_paths:
            if path not in self.config["games"][game_name]["save_paths"]:
                self.config["games"][game_name]["save_paths"].append(path)
        
        # Save config
        self.save_config()
        
        # Try to get game metadata using IGDB API if configured
        if self.config.get("igdb_auth"):
            self.fetch_game_metadata(game_name, is_new_game=True)
        else:
            # Finalize game addition
            self.finalize_game_addition(None, None)
            
        # Update UI
        self.load_games()
        self.update_games_list()
    
    def fetch_game_metadata(self, game_name, is_new_game=False):
        # Check if IGDB API is configured properly
        if not self.config.get("igdb_auth"):
            if is_new_game and self.current_game_addition:
                self.finalize_game_addition(None, None)
            return
        
        # Show the game search dialog
        search_dialog = GameSearchDialog(self, self.config["igdb_auth"], game_name)
        
        if search_dialog.exec() == QDialog.Accepted and search_dialog.selected_game:
            # Store the selected game data temporarily for thumbnail
            self.current_game_data = search_dialog.selected_game
            # Download the game cover
            if is_new_game:
                self.download_game_cover(search_dialog.selected_game, is_new_game=True)
            else:
                self.download_game_cover(search_dialog.selected_game)
        else:
            # User cancelled the search dialog
            if is_new_game and self.current_game_addition:
                # Finalize with placeholder
                self.finalize_game_addition(None, None)
    
    def download_game_cover(self, game_data, is_new_game=False):
        # Create images directory if it doesn't exist
        images_dir = os.path.join(self.app_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        
        # Set up the IGDB API to download the cover
        worker = IGDBImageDownloadWorker(self.config["igdb_auth"], game_data, images_dir)
        
        if is_new_game:
            worker.signals.image_downloaded.connect(lambda name, path, official_name: 
                                        self.finalize_game_addition(path, official_name))
        else:
            worker.signals.image_downloaded.connect(self.on_image_downloaded)
        
        worker.signals.search_failed.connect(lambda msg: 
                                self.handle_image_download_failure(msg, is_new_game))
        
        # Start worker in thread pool
        self.threadpool.start(worker)
    
    def handle_image_download_failure(self, error_msg, is_new_game=False):
        if is_new_game and self.current_game_addition:
            # Finalize with placeholder even if download failed
            self.finalize_game_addition(None, None)
        else:
            QMessageBox.warning(self, "Image Download Failed", error_msg)
    
    def on_image_downloaded(self, game_name, image_path, official_name):
        # Update existing game with the image path and official name
        if game_name in self.config["games"]:
            self.config["games"][game_name]["image"] = image_path
            
            # Store the thumbnail data with base64 encoding
            if hasattr(self, "current_game_data") and self.current_game_data:
                if "thumb_data" in self.current_game_data:
                    import base64
                    thumb_data = self.current_game_data["thumb_data"]
                    self.config["games"][game_name]["thumb_data"] = base64.b64encode(thumb_data).decode('utf-8')
            
            # Update to official name if available and different
            if official_name and official_name != game_name:
                # Create new entry with official name
                self.config["games"][official_name] = self.config["games"][game_name].copy()
                # Delete old entry
                del self.config["games"][game_name]
            
            self.save_config()
            self.load_games()  # Refresh the UI to show the image
            
            # Notify user
            QMessageBox.information(self, "Image Downloaded", 
                                f"Cover image for '{official_name or game_name}' has been downloaded.")
    
    def finalize_game_addition(self, image_path, official_name):
        """Complete the game addition process after metadata and image are retrieved"""
        if not self.current_game_addition:
            return
        
        # Use official name from IGDB if available, otherwise use user's input
        game_name = official_name if official_name else self.current_game_addition["name"]
        
        # If the name has changed due to official name, update the config
        if official_name and official_name != self.current_game_addition["name"]:
            # Move the data to the new name
            if self.current_game_addition["name"] in self.config["games"]:
                self.config["games"][game_name] = self.config["games"][self.current_game_addition["name"]]
                del self.config["games"][self.current_game_addition["name"]]
        
        # Update the game entry with image path if provided
        if image_path and game_name in self.config["games"]:
            self.config["games"][game_name]["image"] = image_path
        
        # Save config
        self.save_config()
        
        # Update UI
        self.load_games()
        self.update_games_list()
        
        # Clear the current game addition
        self.current_game_addition = None
        
        # Notify user
        QMessageBox.information(self, "Game Added", 
                               f"Game '{game_name}' has been added successfully.")
    
    def show_api_setup(self, after_setup=None):
        # Show the IGDB API setup dialog
        setup_dialog = IGDBSetupDialog(self, {
            "client_id": self.config.get("igdb_client_id", ""),
            "client_secret": self.config.get("igdb_client_secret", "")
        })
        
        if setup_dialog.exec() == QDialog.Accepted and setup_dialog.auth_data:
            # Save the authentication data
            self.config["igdb_client_id"] = setup_dialog.client_id_input.text().strip()
            self.config["igdb_client_secret"] = setup_dialog.client_secret_input.text().strip()
            self.config["igdb_auth"] = setup_dialog.auth_data
            self.save_config()
            
            # Execute callback if provided
            if after_setup:
                after_setup()
            # Otherwise ask if user wants to update existing games
            elif self.config["games"]:
                reply = QMessageBox.question(
                    self,
                    "Update Existing Games",
                    "Would you like to update existing games with images from IGDB?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                
                if reply == QMessageBox.Yes:
                    self.update_all_game_metadata()
    
    def update_all_game_metadata(self):
        """Update metadata for all games in the collection"""
        for game_name in list(self.config["games"].keys()):
            self.fetch_game_metadata(game_name)
            
    def show_game_context_menu(self, pos, widget):
        game_name = widget.property("game_name")
        if not game_name or game_name not in self.config["games"]:
            return
        
        context_menu = QMenu(self)
        
        # Add menu actions
        rename_action = context_menu.addAction("Rename Game")
        edit_paths_action = context_menu.addAction("Edit Save Paths")
        fetch_metadata_action = context_menu.addAction("Fetch Metadata")
        open_backup_action = context_menu.addAction("Open Backup Directory")
        delete_action = context_menu.addAction("Delete Game")
        
        # Show context menu at cursor position
        action = context_menu.exec(widget.mapToGlobal(pos))
        
        # Handle menu actions
        if action == rename_action:
            self.rename_game(game_name)
        elif action == edit_paths_action:
            self.edit_game_paths(game_name)
        elif action == fetch_metadata_action:
            self.fetch_game_metadata(game_name)
        elif action == open_backup_action:
            self.open_backup_directory(game_name)
        elif action == delete_action:
            self.delete_game(game_name)
            
    def rename_game(self, game_name):
        # Prompt user for new name
        new_name, ok = QInputDialog.getText(
            self, "Rename Game", "Enter new game name:", 
            QLineEdit.Normal, game_name
        )
        
        if not ok or not new_name or new_name == game_name:
            return  # User cancelled or didn't change name
        
        # Check if new name already exists
        if new_name in self.config["games"]:
            QMessageBox.warning(self, "Name Exists", f"A game with the name '{new_name}' already exists.")
            return
        
        # Copy game data to new name and delete old entry
        self.config["games"][new_name] = self.config["games"][game_name].copy()
        del self.config["games"][game_name]
        
        # Save config and update UI
        self.save_config()
        self.load_games()
        self.update_games_list()
        QMessageBox.information(self, "Game Renamed", f"Game has been renamed to '{new_name}'.")
    
    def edit_game_paths(self, game_name):
        # Get current game data
        game_data = self.config["games"].get(game_name)
        if not game_data:
            return
        
        # Show save selection dialog
        dialog = SaveSelectionDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        
        selected_paths = dialog.selected_paths
        
        if not selected_paths:
            return
        
        # Determine common parent directory for all selected items
        if len(selected_paths) == 1:
            if os.path.isdir(selected_paths[0]):
                save_parent_dir = selected_paths[0]
            else:
                save_parent_dir = os.path.dirname(selected_paths[0])
        else:
            # Find common parent directory
            parent_dirs = [os.path.dirname(path) if not os.path.isdir(path) else path for path in selected_paths]
            common_parent = os.path.commonpath(parent_dirs)
            save_parent_dir = common_parent
        
        # Update game data with new paths
        self.config["games"][game_name]["save_paths"] = selected_paths
        self.config["games"][game_name]["parent_dir"] = save_parent_dir
        
        # Save config
        self.save_config()
        QMessageBox.information(self, "Paths Updated", f"Save paths for '{game_name}' have been updated.")
    
    def open_backup_directory(self, game_name):
        game_data = self.config["games"].get(game_name)
        if not game_data:
            return
        
        # Create the game's backup directory path
        game_folder_name = game_name.replace(" ", "_").replace(":", "").replace("/", "_")
        backup_dir = os.path.join(self.config["backup_dir"], game_folder_name)
        
        # Check if directory exists
        if not os.path.exists(backup_dir):
            # Create it if it doesn't exist
            try:
                os.makedirs(backup_dir, exist_ok=True)
                QMessageBox.information(self, "Directory Created", 
                                     f"Backup directory for '{game_name}' has been created.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to create backup directory: {e}")
                return
        
        # Open the directory in file explorer
        try:
            # Use the appropriate command for the OS
            if sys.platform == 'win32':
                # Windows
                subprocess.run(['explorer', backup_dir])
            elif sys.platform == 'darwin':
                # macOS
                subprocess.run(['open', backup_dir])
            else:
                # Linux
                subprocess.run(['xdg-open', backup_dir])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open directory: {e}")
    
    def delete_game(self, game_name):
        # Confirm deletion
        confirm = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete '{game_name}' from Ambidex?\n\nThis will not delete your backup files, but the game entry will be removed from the list.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if confirm != QMessageBox.Yes:
            return
        
        # Remove game from config
        if game_name in self.config["games"]:
            del self.config["games"][game_name]
            
            # Save config
            self.save_config()
            
            # Update UI
            self.load_games()
            self.update_games_list()
            QMessageBox.information(self, "Game Deleted", f"'{game_name}' has been removed.")
            

def main():
    app = QApplication(sys.argv)
    
    # Create and set application icon
    icon_path = "icon.ico"
    app.setWindowIcon(QIcon(icon_path))
    
    window = GameSaveBackup()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()