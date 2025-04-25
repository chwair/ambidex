import sys
import os
import datetime
import shutil
import platform
import base64
import subprocess
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel,
    QPushButton, QHBoxLayout, QMessageBox, QListWidget, QListWidgetItem, QDialog,
    QMenu, QScrollArea, QInputDialog, QFileDialog, QLineEdit, QAbstractItemView
)
from PySide6.QtGui import QPixmap, QIcon, QColor
from PySide6.QtCore import Qt, QThreadPool

from ui import (
    IGDBSetupDialog, GameSearchDialog, SaveSelectionDialog,
    FlowLayout, DraggableWidget, GameNameSuggestionDialog, 
    BackupItemDelegate, LoadingDialog
)
from workers import (
    IGDBGameSearchWorker, IGDBImageDownloadWorker
)
import utils


class logger:
    @staticmethod
    def info(message):
        print(f"[INFO] {message}")
    
    @staticmethod
    def error(message):
        print(f"[ERROR] {message}")

class GameSaveBackup(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ambidex")
        self.setMinimumSize(800, 600)
        
        icon_path = "icon.ico"
        self.setWindowIcon(QIcon(icon_path))
        
        self.app_dir = os.path.dirname(os.path.abspath(__file__))
        
        self.config_file = os.path.join(self.app_dir, "config.json")
        self.config = utils.load_config(self.config_file)
        
        if not self.config.get("backup_dir"):
            self.config["backup_dir"] = os.path.join(self.app_dir, "backups")
        
        os.makedirs(self.config["backup_dir"], exist_ok=True)
            
        self.save_config()
        
        self.current_game_addition = None
        
        self.threadpool = QThreadPool.globalInstance()
        
        self.init_ui()
        
    
    # def show_first_run_dialog(self):
    #     msg_box = QMessageBox(self)
    #     msg_box.setWindowTitle("Welcome to Ambidex!")
        
    #     welcome_text = "<h2>Welcome to Ambidex!</h2>"
    #     question_text = "Would you like to enable IGDB integration to automatically fetch game covers and metadata?\n\n" \
    #                     "This requires a free Twitch account and API key."
        
    #     msg_box.setText(welcome_text + question_text)
    #     msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    #     msg_box.setDefaultButton(QMessageBox.Yes)
        
    #     reply = msg_box.exec()
        
    #     if reply == QMessageBox.Yes:
    #         self.show_api_setup()

    def init_ui(self):
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        self.backup_tab = QWidget()
        self.restore_tab = QWidget()
        
        self.tabs.addTab(self.backup_tab, "Backup")
        self.tabs.addTab(self.restore_tab, "Restore")
        
        self.setup_backup_tab()
        self.setup_restore_tab()
        self.setup_menu()
    
    def setup_menu(self):
        menu_bar = self.menuBar()
        
        settings_menu = menu_bar.addMenu("Settings")
        
        api_source_menu = settings_menu.addMenu("IGDB API Source")
        
        self.ambidex_api_action = api_source_menu.addAction("Ambidex IGDB API")
        self.ambidex_api_action.setCheckable(True)
        self.ambidex_api_action.triggered.connect(lambda checked: self.set_igdb_api_source("ambidex"))
        
        self.legacy_api_action = api_source_menu.addAction("Custom Twitch IGDB API")
        self.legacy_api_action.setCheckable(True) 
        self.legacy_api_action.triggered.connect(lambda checked: self.set_igdb_api_source("legacy"))
        
        api_source = self.config.get("igdb_api_source", "ambidex")
        self.ambidex_api_action.setChecked(api_source == "ambidex")
        self.legacy_api_action.setChecked(api_source == "legacy")
        
        
        self.api_setup_action = settings_menu.addAction("Custom IGDB API Setup")
        self.api_setup_action.triggered.connect(self.show_api_setup)
        
        api_source = self.config.get("igdb_api_source", "ambidex")
        self.api_setup_action.setEnabled(api_source == "legacy")
        
        self.ambidex_api_action.triggered.connect(lambda: self.api_setup_action.setEnabled(False))
        self.legacy_api_action.triggered.connect(lambda: self.api_setup_action.setEnabled(True))

        
        backup_dir_action = settings_menu.addAction("Set Backup Directory")
        backup_dir_action.triggered.connect(self.set_backup_directory)
    
    def setup_backup_tab(self):
        layout = QVBoxLayout(self.backup_tab)
        
        top_buttons = QHBoxLayout()
        
        self.add_game_button = QPushButton("+ Add Game Save Files")
        self.add_game_button.clicked.connect(self.add_game_save)
        top_buttons.addWidget(self.add_game_button)
        
        backup_all_button = QPushButton("Backup All Games")
        backup_all_button.clicked.connect(self.backup_all_games)
        top_buttons.addWidget(backup_all_button)
        
        layout.addLayout(top_buttons)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.game_grid_widget = DraggableWidget()
        self.game_grid_widget.game_moved.connect(self.on_game_moved)
        
        self.game_grid = FlowLayout(self.game_grid_widget)
        self.game_grid.setSpacing(10)
        self.scroll_area.setWidget(self.game_grid_widget)
        layout.addWidget(self.scroll_area)
        
        self.load_games()
        
    def load_games(self):
        while self.game_grid.count():
            item = self.game_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        
        for game_name, game_data in self.config.get("games", {}).items():
            game_widget = self.create_game_widget(game_name, game_data)
            self.game_grid.addWidget(game_widget)
            
    def backup_game(self, game_name, show_message=True, label="", color=None):
        game_data = self.config["games"].get(game_name)
        if not game_data:
            return
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        game_folder_name = utils.make_safe_filename(game_name)
        
        backup_base = os.path.abspath(os.path.normpath(self.config["backup_dir"]))
        
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
            
        backup_dir = os.path.join(backup_base, game_folder_name, timestamp)
        
        try:
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
        
        parent_dir = game_data.get("parent_dir", "")
        if parent_dir:
            try:
                with open(os.path.join(backup_dir, "parent_dir.txt"), 'w') as f:
                    f.write(parent_dir)
            except Exception as e:
                print(f"Warning: Could not write parent_dir.txt: {e}")
        
        success = True
        
        for save_path in game_data["save_paths"]:
            try:
                if not os.path.exists(save_path):
                    QMessageBox.warning(self, "Path Not Found", f"Save path does not exist: {save_path}")
                    success = False
                    continue
                
                if parent_dir and save_path.startswith(parent_dir):
                    rel_path = os.path.relpath(save_path, parent_dir)
                    dest_path = os.path.join(backup_dir, rel_path)
                else:
                    dest_path = os.path.join(backup_dir, os.path.basename(save_path))
                
                if os.path.isfile(save_path):
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                
                if os.path.isdir(save_path):
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
            backup_info = {
                "timestamp": timestamp,
                "datetime": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "directory": backup_dir,
                "label": label,
                "color": color or "#FFFFFF"
            }
            
            self.config["games"][game_name]["backups"].append(backup_info)
            self.save_config()
            
            if show_message:
                QMessageBox.information(self, "Backup Complete", f"Save files for {game_name} have been backed up successfully!")
            self.update_games_list()
        else:
            try:
                if os.path.exists(backup_dir):
                    shutil.rmtree(backup_dir)
            except Exception as e:
                print(f"Warning: Could not clean up partial backup: {e}")
    
    def backup_all_games(self):
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
            if self.config["games"][game_name].get("backups"):
                self.games_list.addItem(game_name)
    
    def show_game_backups(self, item):
        game_name = item.text()
        self.backups_list.clear()
        self.restore_button.setEnabled(False)
        
        game_data = self.config["games"].get(game_name)
        if not game_data:
            return
        
        if not hasattr(self, 'backup_delegate'):
            self.backup_delegate = BackupItemDelegate()
            self.backups_list.setItemDelegate(self.backup_delegate)
        
        backups = sorted(game_data.get("backups", []), key=lambda x: x["timestamp"], reverse=True)
        
        for i, backup in enumerate(backups):
            backup_label = backup.get("label", "")
            
            display_text = backup["datetime"]
            if backup_label:
                display_text += f" - {backup_label}"
            
            if i == 0:
                display_text += " (Latest)"
                
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, backup)
            
            if i == 0:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            
            self.backups_list.addItem(item)
        
        self.backups_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.backups_list.customContextMenuRequested.connect(self.show_backup_context_menu)
    
    def show_backup_details(self, item):
        self.selected_backup = item.data(Qt.UserRole)
        self.restore_button.setEnabled(True)
    
    def show_backup_context_menu(self, pos):
        item = self.backups_list.itemAt(pos)
        if not item:
            return
            
        self.selected_backup = item.data(Qt.UserRole)
        game_name = self.games_list.currentItem().text()
        if not game_name:
            return
            
        context_menu = QMenu(self)
        
        restore_action = context_menu.addAction("Restore This Backup")
        
        text_label_menu = QMenu("Set Text Label", self)
        context_menu.addMenu(text_label_menu)
        
        edit_text_action = text_label_menu.addAction("Edit Text Label...")
        clear_text_action = text_label_menu.addAction("Clear Text Label")
        
        color_menu = QMenu("Set Color Tag", self)
        context_menu.addMenu(color_menu)
        
        color_actions = []
        colors = [
            ("#FFFFFF", "Default"),
            ("#4CAF50", "Green"), 
            ("#2196F3", "Blue"), 
            ("#FFC107", "Yellow"), 
            ("#FF5722", "Orange"), 
            ("#E91E63", "Pink"),
            ("#9C27B0", "Purple"),
            ("#607D8B", "Gray")
        ]
        
        for color_hex, color_name in colors:
            action = color_menu.addAction(color_name)
            pixmap = QPixmap(16, 16)
            pixmap.fill(QColor(color_hex))
            action.setIcon(QIcon(pixmap))
            action.setData(color_hex)
            color_actions.append(action)
        
        context_menu.addSeparator()
        delete_action = context_menu.addAction("Delete This Backup")
        delete_action.setIcon(QIcon.fromTheme("edit-delete"))
        
        action = context_menu.exec(self.backups_list.mapToGlobal(pos))
        
        if action == restore_action:
            self.restore_backup()
        elif action == edit_text_action:
            self.edit_backup_text_label(game_name)
        elif action == clear_text_action:
            self.clear_backup_label(game_name)
        elif action == delete_action:
            self.delete_backup(game_name)
        elif action in color_actions:
            color_hex = action.data()
            self.set_backup_color(game_name, color_hex)
    
    def edit_backup_text_label(self, game_name):
        current_label = self.selected_backup.get("label", "")
        
        new_label, ok = QInputDialog.getText(
            self, "Edit Label", "Enter a label for this backup:", 
            QLineEdit.Normal, current_label
        )
        
        if not ok:
            return
            
        self.selected_backup["label"] = new_label
        
        self.update_backup_in_config(game_name, {"label": new_label})
    
    def clear_backup_label(self, game_name):
        self.selected_backup["label"] = ""
        
        self.update_backup_in_config(game_name, {"label": ""})
    
    def set_backup_color(self, game_name, color_hex):
        self.selected_backup["color"] = color_hex
        
        self.update_backup_in_config(game_name, {"color": color_hex})
    
    def delete_backup(self, game_name):
        confirm = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete this backup from {self.selected_backup['datetime']}?\n\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if confirm != QMessageBox.Yes:
            return
            
        backup_dir = self.selected_backup["directory"]
        timestamp = self.selected_backup["timestamp"]
        
        game_data = self.config["games"].get(game_name)
        if game_data:
            for i, backup in enumerate(game_data["backups"]):
                if backup["timestamp"] == timestamp:
                    del game_data["backups"][i]
                    break
                    
            self.save_config()
            
            try:
                if os.path.exists(backup_dir):
                    shutil.rmtree(backup_dir)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not delete backup directory: {e}")
            
            self.show_game_backups(self.games_list.currentItem())
    
    def update_backup_in_config(self, game_name, update_data):
        timestamp = self.selected_backup["timestamp"]
        game_data = self.config["games"].get(game_name)
        if game_data:
            for backup in game_data["backups"]:
                if backup["timestamp"] == timestamp:
                    backup.update(update_data)
                    break
                    
            self.save_config()
            
            self.show_game_backups(self.games_list.currentItem())

    def setup_restore_tab(self):
        layout = QVBoxLayout(self.restore_tab)
        
        main_layout = QHBoxLayout()
        
        left_layout = QVBoxLayout()
        
        left_layout.addWidget(QLabel("Games with backups:"))
        self.games_list = QListWidget()
        self.games_list.itemClicked.connect(self.show_game_backups)
        left_layout.addWidget(self.games_list)
        
        main_layout.addLayout(left_layout, 1)
        
        right_layout = QVBoxLayout()
        
        right_layout.addWidget(QLabel("Available backups: (Right-click for options)"))
        self.backups_list = QListWidget()
        self.backups_list.itemClicked.connect(self.show_backup_details)
        self.backups_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        right_layout.addWidget(self.backups_list)
        
        self.restore_button = QPushButton("Restore Selected Backup")
        self.restore_button.clicked.connect(self.restore_backup)
        self.restore_button.setEnabled(False)
        right_layout.addWidget(self.restore_button)
        
        main_layout.addLayout(right_layout, 2)
        
        layout.addLayout(main_layout)
        
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
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        
        image_container = QWidget()
        image_layout = QVBoxLayout(image_container)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(0)
        
        image_label = QLabel()
        image_label.setStyleSheet("border: none; background: transparent;")
        image_label.setAlignment(Qt.AlignCenter)
        
        image_width = 120
        image_height = int(image_width * (352/264))
        
        if game_data.get("image") and os.path.exists(game_data["image"]):
            pixmap = QPixmap(game_data["image"])
            image_label.setPixmap(pixmap.scaled(image_width, image_height, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            image_label.setFixedSize(image_width, image_height)
        else:
            image_label.setText(game_name)
            image_label.setStyleSheet("background-color: #333; color: white; border: 1px solid #555;")
            image_label.setFixedSize(image_width, image_height)
        
        image_layout.addWidget(image_label, 0, Qt.AlignCenter)
        layout.addWidget(image_container, 0, Qt.AlignCenter)
        
        name_label = QLabel(game_name)

        if QApplication.styleHints().colorScheme() != Qt.ColorScheme.Dark or (platform.release() != "11" or int(platform.version().split('.')[2]) < 22000):
            name_label_col = "303030"
        else:
            name_label_col = "e0e0e0"
        name_label.setStyleSheet(f"border: none; color: #{name_label_col}; padding: 4px 0;")

        name_label.setAlignment(Qt.AlignCenter)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)
        
        backup_button = QPushButton("Backup Saves")
        backup_button.clicked.connect(lambda: self.backup_game(game_name))
        layout.addWidget(backup_button)
        
        widget.setProperty("game_name", game_name)
        widget.setAcceptDrops(True)
        widget.mousePressEvent = lambda e, w=widget: self.game_grid_widget.start_drag(e, w)
        
        widget.setContextMenuPolicy(Qt.CustomContextMenu)
        widget.customContextMenuRequested.connect(lambda pos, w=widget: self.show_game_context_menu(pos, w))
        
        return widget

    def on_game_moved(self, source_name, target_name):
        if source_name == target_name:
            return
            
        games = list(self.config["games"].keys())
        source_idx = games.index(source_name)
        target_idx = games.index(target_name)
        
        games.insert(target_idx, games.pop(source_idx))
        
        new_games = {}
        for game in games:
            new_games[game] = self.config["games"][game]
        
        self.config["games"] = new_games
        self.save_config()
        self.load_games()
    
    def save_config(self):
        utils.save_config(self.config_file, self.config)

    def add_game_save(self):
        self.current_game_addition = None
        
        name_dialog = GameNameSuggestionDialog(self)
        if name_dialog.exec() != QDialog.Accepted:
            return
                
        game_name = name_dialog.selected_name
        if not game_name:
            return
        
        self.game_name_from_search = game_name
        
        loading_dialog = LoadingDialog(self, f"Searching for: '{game_name}'...")
        loading_dialog.center_on_parent()
        loading_dialog.show()
        QApplication.processEvents()
        
        igdb_api = utils.get_igdb_api_source(self.config)
        
        try:
            if (igdb_api["needs_auth"]):
                if not self.config.get("igdb_auth"):
                    logger.error("Legacy API selected but no auth data available")
                    loading_dialog.close()
                    self.continue_add_game_save(game_name, None)
                    return
                    
                worker = igdb_api["search_worker"](self.config["igdb_auth"], game_name)
            else:
                worker = igdb_api["search_worker"](game_name)
                
            worker.signals.search_complete.connect(self.on_custom_game_search_complete)
            worker.signals.search_failed.connect(lambda msg: self.on_custom_game_search_failed(msg, loading_dialog))
            worker.signals.finished.connect(loading_dialog.close)
            
            self.current_worker = worker
            
            self.threadpool.start(worker)
        except Exception as e:
            logger.error(f"Error using IGDB backend: {str(e)}")
            loading_dialog.close()
            
            self.continue_add_game_save(game_name, None)

    def on_custom_game_search_complete(self, games):
        if not hasattr(self, 'current_worker'):
            return
            
        self.current_worker = None
        
        if not games:
            QMessageBox.information(self, "No Metadata Found", 
                                  "No game metadata was found. Continuing with the provided game name.")
            
            if hasattr(self, 'game_name_from_search'):
                custom_name = self.game_name_from_search
                delattr(self, 'game_name_from_search')
                self.continue_add_game_save(custom_name, None)
            return
            
        if not hasattr(self, 'game_name_from_search'):
            return
            
        custom_name = self.game_name_from_search
        
        search_dialog = GameSearchDialog(self, None, custom_name, games=games, allow_custom_name=True)
        
        if search_dialog.exec() == QDialog.Accepted:
            if search_dialog.use_custom_name:
                self.continue_add_game_save(custom_name, None)
            elif search_dialog.selected_game:
                igdb_game_data = search_dialog.selected_game
                official_name = igdb_game_data["name"]
                self.continue_add_game_save(official_name, igdb_game_data)
            else:
                self.continue_add_game_save(custom_name, None)
        else:
            self.continue_add_game_save(custom_name, None)
            
        if hasattr(self, 'game_name_from_search'):
            delattr(self, 'game_name_from_search')
    
    def on_custom_game_search_failed(self, error_msg, loading_dialog=None):
        logger.error(f"Custom IGDB search failed: {error_msg}")
        
        if loading_dialog and loading_dialog.isVisible():
            loading_dialog.close()
        
        if hasattr(self, 'game_name_from_search'):
            custom_name = self.game_name_from_search
            delattr(self, 'game_name_from_search')
            
            QMessageBox.warning(self, "Metadata Search Failed", 
                              f"Failed to search for game metadata: {error_msg}\n\nContinuing with the provided game name.")
            
            self.continue_add_game_save(custom_name, None)
        
        if hasattr(self, 'current_worker'):
            self.current_worker = None
    
    def continue_add_game_save(self, game_name, igdb_game_data):
        loading_dialog = LoadingDialog(self, f"Fetching save locations for '{game_name}'")
        loading_dialog.center_on_parent()
        loading_dialog.show()
        QApplication.processEvents()
        
        try:
            loading_dialog.set_detail("Checking PCGamingWiki for save locations...")
            QApplication.processEvents()
            suggested_paths = utils.fetch_pcgamingwiki_save_locations(game_name)
        except Exception as e:
            logger.error(f"PCGamingWiki error: {str(e)}")
            suggested_paths = {}
        finally:
            loading_dialog.close()
        
        dialog = SaveSelectionDialog(self, game_name, None, suggested_paths)
        if dialog.exec() != QDialog.Accepted:
            return
        
        selected_paths = dialog.selected_paths
        
        if not selected_paths:
            return
        
        if len(selected_paths) == 1:
            if os.path.isdir(selected_paths[0]):
                save_parent_dir = selected_paths[0]
            else:
                save_parent_dir = os.path.dirname(selected_paths[0])
        else:
            parent_dirs = [os.path.dirname(path) if not os.path.isdir(path) else path for path in selected_paths]
            common_parent = os.path.commonpath(parent_dirs)
            save_parent_dir = common_parent
        
        self.current_game_addition = {
            "name": game_name,
            "save_paths": selected_paths,
            "parent_dir": save_parent_dir
        }
        
        if game_name not in self.config["games"]:
            self.config["games"][game_name] = {
                "save_paths": [],
                "backups": [],
                "image": "",
                "thumb_data": None,
                "parent_dir": save_parent_dir
            }
        
        for path in selected_paths:
            if path not in self.config["games"][game_name]["save_paths"]:
                self.config["games"][game_name]["save_paths"].append(path)
        
        self.save_config()
        
        if igdb_game_data and "cover" in igdb_game_data and "image_id" in igdb_game_data["cover"]:
            self.current_game_data = igdb_game_data
            self.download_cover_custom(igdb_game_data)
        else:
            self.finalize_game_addition(None, None)
            
        self.load_games()
        self.update_games_list()
        
    def download_cover_custom(self, game_data):
        try:
            if not game_data or not isinstance(game_data, dict):
                self.finalize_game_addition(None, None)
                return
                
            if "cover" not in game_data or not game_data["cover"] or "image_id" not in game_data["cover"]:
                self.finalize_game_addition(None, None)
                return
            
            images_dir = os.path.join(self.app_dir, "images")
            try:
                os.makedirs(images_dir, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create images directory: {e}")
                self.finalize_game_addition(None, None)
                return
                
            safe_name = utils.make_safe_filename(game_data["name"])
            expected_image_path = os.path.join(images_dir, f"{safe_name}.jpg")
            
            igdb_api = utils.get_igdb_api_source(self.config)
            
            if igdb_api["needs_auth"]:
                if not self.config.get("igdb_auth"):
                    logger.error("Legacy API selected but no auth data available")
                    worker = IGDBImageDownloadWorker(game_data, images_dir)
                else:
                    worker = igdb_api["image_worker"](self.config["igdb_auth"], game_data, images_dir)
            else:
                worker = igdb_api["image_worker"](game_data, images_dir)
            
            self.current_worker = worker
            
            worker.signals.image_downloaded.connect(
                lambda name, path, official_name: self.finalize_game_addition(path, official_name))
            
            worker.signals.search_failed.connect(
                lambda msg: self.handle_image_download_failure(msg, True))
            
            worker.signals.finished.connect(
                lambda: self.image_download_finished(True, expected_image_path))
            
            self.threadpool.start(worker)
        except Exception as e:
            logger.error(f"Error in download_cover_custom: {str(e)}")
            self.finalize_game_addition(None, None)

    def fetch_game_metadata(self, game_name, is_new_game=False):
        if not self.config.get("igdb_auth"):
            if is_new_game and self.current_game_addition:
                self.finalize_game_addition(None, None)
            return
        
        search_dialog = GameSearchDialog(self, self.config["igdb_auth"], game_name)
        
        if search_dialog.exec() == QDialog.Accepted and search_dialog.selected_game:
            logger.info(f"Selected game metadata for: {game_name}")
            self.current_game_data = search_dialog.selected_game
            
            if not is_new_game:
                try:
                    logger.info(f"Downloading cover for existing game: {game_name}")
                    self.download_game_cover(search_dialog.selected_game, is_new_game=False, game_name=game_name)
                except Exception as e:
                    logger.error(f"Error downloading cover: {str(e)}")
                    if game_name in self.config["games"] and "thumb_data" in search_dialog.selected_game:
                        try:
                            self.config["games"][game_name]["thumb_data"] = base64.b64encode(
                                search_dialog.selected_game["thumb_data"]).decode('utf-8')
                            self.save_config()
                            self.load_games()
                            QMessageBox.information(self, "Metadata Updated", 
                                                 f"Metadata for '{game_name}' has been updated.")
                        except Exception as e2:
                            logger.error(f"Error updating metadata directly: {str(e2)}")
            else:
                self.download_game_cover(search_dialog.selected_game, is_new_game=True)
        else:
            logger.info(f"User canceled metadata search for: {game_name}")
            if is_new_game and self.current_game_addition:
                self.finalize_game_addition(None, None)
    
    def download_game_cover(self, game_data, is_new_game=False, game_name=None):
        try:
            if not game_data or not isinstance(game_data, dict):
                if is_new_game and self.current_game_addition:
                    self.finalize_game_addition(None, None)
                else:
                    QMessageBox.warning(self, "Error", "Invalid game data for image download")
                return
                
            if "cover" not in game_data or not game_data["cover"] or "image_id" not in game_data["cover"]:
                if is_new_game and self.current_game_addition:
                    self.finalize_game_addition(None, None)
                else:
                    QMessageBox.warning(self, "No Cover Available", "This game doesn't have cover art available.")
                return
            
            images_dir = os.path.join(self.app_dir, "images")
            try:
                os.makedirs(images_dir, exist_ok=True)
            except Exception as e:
                if is_new_game and self.current_game_addition:
                    self.finalize_game_addition(None, None)
                else:
                    QMessageBox.warning(self, "Error", f"Failed to create images directory: {e}")
                return
                
            safe_name = utils.make_safe_filename(game_data["name"])
            expected_image_path = os.path.join(images_dir, f"{safe_name}.jpg")
            
            worker = IGDBImageDownloadWorker(self.config["igdb_auth"], game_data, images_dir)
            
            self.current_worker = worker
            
            if is_new_game:
                worker.signals.image_downloaded.connect(
                    lambda name, path, official_name: self.finalize_game_addition(path, official_name))
            else:
                original_game_name = game_name if game_name else game_data["name"]
                worker.signals.image_downloaded.connect(
                    lambda name, path, official_name: self.on_image_downloaded(original_game_name, path, official_name))
            
            worker.signals.search_failed.connect(
                lambda msg: self.handle_image_download_failure(msg, is_new_game))
            
            worker.signals.finished.connect(
                lambda: self.image_download_finished(is_new_game, expected_image_path))
            
            self.threadpool.start(worker)
        except Exception as e:
            logger.error(f"Error in download_game_cover: {str(e)}")
            if is_new_game and self.current_game_addition:
                self.finalize_game_addition(None, None)
            else:
                QMessageBox.warning(self, "Error", f"An unexpected error occurred: {str(e)}")

    def image_download_finished(self, is_new_game=False, expected_image_path=None):
        try:
            if is_new_game and hasattr(self, "current_game_addition") and self.current_game_addition:
                if not hasattr(self, "current_game_data") or not self.current_game_data:
                    if expected_image_path and os.path.exists(expected_image_path):
                        official_name = self.current_game_addition["name"]
                        self.finalize_game_addition(expected_image_path, official_name)
                    else:
                        self.finalize_game_addition(None, None)
        except Exception as e:
            logger.error(f"Error in image_download_finished: {str(e)}")
            if is_new_game and hasattr(self, "current_game_addition") and self.current_game_addition:
                self.finalize_game_addition(None, None)

    def handle_image_download_failure(self, error_msg, is_new_game=False):
        try:
            logger.error(f"Image download failed: {error_msg}")
            if is_new_game and self.current_game_addition:
                self.finalize_game_addition(None, None)
            else:
                QMessageBox.warning(self, "Image Download Failed", error_msg)
        except Exception as e:
            logger.error(f"Error handling image download failure: {str(e)}")
            if is_new_game and hasattr(self, "current_game_addition") and self.current_game_addition:
                self.finalize_game_addition(None, None)

    def on_image_downloaded(self, game_name, image_path, official_name):
        try:
            logger.info(f"Image downloaded for {game_name}, path: {image_path}")
            
            if game_name in self.config["games"]:
                if image_path:
                    abs_image_path = os.path.abspath(os.path.normpath(image_path))
                    if os.path.exists(abs_image_path):
                        logger.info(f"Setting image path to: {abs_image_path}")
                        self.config["games"][game_name]["image"] = abs_image_path
                    else:
                        logger.error(f"Image path doesn't exist: {abs_image_path}")
                        images_dir = os.path.join(self.app_dir, "images")
                        safe_name = utils.make_safe_filename(game_name)
                        expected_path = os.path.join(images_dir, f"{safe_name}.jpg")
                        if os.path.exists(expected_path):
                            logger.info(f"Using fallback image path: {expected_path}")
                            self.config["games"][game_name]["image"] = expected_path
                
                if hasattr(self, "current_game_data") and self.current_game_data:
                    if "thumb_data" in self.current_game_data and self.current_game_data["thumb_data"]:
                        try:
                            logger.info("Setting thumbnail data")
                            self.config["games"][game_name]["thumb_data"] = base64.b64encode(
                                self.current_game_data["thumb_data"]).decode('utf-8')
                        except Exception as e:
                            logger.error(f"Error setting thumb data: {str(e)}")
                
                if official_name and official_name != game_name:
                    logger.info(f"Game name changed from {game_name} to {official_name}")
                    if official_name not in self.config["games"]:
                        self.config["games"][official_name] = self.config["games"][game_name].copy()
                        del self.config["games"][game_name]
                        
                        QMessageBox.information(self, "Game Renamed", 
                                              f"Game has been renamed from '{game_name}' to '{official_name}'.")
                
                try:
                    logger.info("Saving config after metadata update")
                    self.save_config()
                except Exception as e:
                    logger.error(f"Error saving config: {str(e)}")
                
                try:
                    logger.info("Updating UI after metadata update")
                    self.load_games()
                    self.update_games_list()
                except Exception as e:
                    logger.error(f"Error updating UI: {str(e)}")
                
                if hasattr(self, "current_worker"):
                    logger.info("Cleaning up worker reference")
                    self.current_worker = None
                
                if hasattr(self, "current_game_data"):
                    logger.info("Cleaning up game data reference")
                    delattr(self, "current_game_data")
                
                QMessageBox.information(self, "Image Downloaded", 
                                    f"Cover image for '{official_name or game_name}' has been downloaded.")
        except Exception as e:
            logger.error(f"Uncaught error in on_image_downloaded: {str(e)}")
            try:
                self.save_config()
                self.load_games()
                self.update_games_list()
                
                if hasattr(self, "current_worker"):
                    self.current_worker = None
                if hasattr(self, "current_game_data"):
                    delattr(self, "current_game_data")
                    
                QMessageBox.information(self, "Metadata Updated", 
                                    f"Metadata for '{game_name}' has been updated.")
            except Exception as e2:
                logger.error(f"Error in on_image_downloaded fallback: {str(e2)}")
    
    def finalize_game_addition(self, image_path, official_name):
        try:
            if not self.current_game_addition:
                logger.error("No current_game_addition available in finalize_game_addition")
                return
            
            game_name = official_name if official_name else self.current_game_addition["name"]
            logger.info(f"Finalizing game addition for: {game_name}")
            
            if official_name and official_name != self.current_game_addition["name"]:
                logger.info(f"Game name changed from {self.current_game_addition['name']} to {official_name}")
                if self.current_game_addition["name"] in self.config["games"]:
                    if game_name in self.config["games"]:
                        logger.info(f"Merging game data for {game_name}")
                        for path in self.config["games"][self.current_game_addition["name"]]["save_paths"]:
                            if path not in self.config["games"][game_name]["save_paths"]:
                                self.config["games"][game_name]["save_paths"].append(path)
                        
                        if "backups" in self.config["games"][self.current_game_addition["name"]]:
                            if "backups" not in self.config["games"][game_name]:
                                self.config["games"][game_name]["backups"] = []
                            
                            self.config["games"][game_name]["backups"].extend(
                                self.config["games"][self.current_game_addition["name"]]["backups"]
                            )
                        
                        del self.config["games"][self.current_game_addition["name"]]
                    else:
                        logger.info(f"Renaming game from {self.current_game_addition['name']} to {game_name}")
                        self.config["games"][game_name] = self.config["games"][self.current_game_addition["name"]]
                        del self.config["games"][self.current_game_addition["name"]]
            
            if image_path and game_name in self.config["games"]:
                try:
                    logger.info(f"Checking image path: {image_path}")
                    abs_image_path = os.path.abspath(os.path.normpath(image_path))
                    if os.path.exists(abs_image_path):
                        logger.info(f"Setting image path to: {abs_image_path}")
                        self.config["games"][game_name]["image"] = abs_image_path
                    else:
                        logger.error(f"Image path does not exist: {abs_image_path}")
                        try:
                            images_dir = os.path.join(self.app_dir, "images")
                            safe_name = utils.make_safe_filename(game_name)
                            expected_image_path = os.path.join(images_dir, f"{safe_name}.jpg")
                            if os.path.exists(expected_image_path):
                                logger.info(f"Using fallback image path: {expected_image_path}")
                                self.config["games"][game_name]["image"] = expected_image_path
                        except Exception as img_e:
                            logger.error(f"Error in fallback image check: {str(img_e)}")
                except Exception as e:
                    logger.error(f"Error checking image path: {str(e)}")
            
            if hasattr(self, "current_game_data") and self.current_game_data and game_name in self.config["games"]:
                if "thumb_data" in self.current_game_data and self.current_game_data["thumb_data"]:
                    try:
                        logger.info("Setting thumbnail data from current_game_data")
                        self.config["games"][game_name]["thumb_data"] = base64.b64encode(
                            self.current_game_data["thumb_data"]).decode('utf-8')
                    except Exception as e:
                        logger.error(f"Error setting thumb data: {str(e)}")
            
            try:
                logger.info("Saving config after finalizing game addition")
                self.save_config()
            except Exception as e:
                logger.error(f"Error saving config during finalize: {str(e)}")
            
            try:
                logger.info("Updating UI after finalizing game addition")
                self.load_games()
                self.update_games_list()
            except Exception as e:
                logger.error(f"Error updating UI during finalize: {str(e)}")
            
            logger.info("Clearing temporary data")
            self.current_game_addition = None
            
            if hasattr(self, "current_worker"):
                logger.info("Cleaning up worker reference")
                self.current_worker = None
                
            if hasattr(self, "current_game_data"):
                logger.info("Cleaning up game data reference")
                delattr(self, "current_game_data")
            
            QMessageBox.information(self, "Game Added", 
                                   f"Game '{game_name}' has been added successfully.")
        except Exception as e:
            logger.error(f"Uncaught exception in finalize_game_addition: {str(e)}")
            self.current_game_addition = None
            if hasattr(self, "current_worker"):
                self.current_worker = None
            if hasattr(self, "current_game_data"):
                delattr(self, "current_game_data")
            QMessageBox.information(self, "Game Added", "Game has been added.")
            try:
                self.load_games()
                self.update_games_list()
            except Exception as ui_e:
                logger.error(f"Error in fallback UI update: {str(ui_e)}")
                pass
    
    def show_api_setup(self, after_setup=None):
        setup_dialog = IGDBSetupDialog(self, {
            "client_id": self.config.get("igdb_client_id", ""),
            "client_secret": self.config.get("igdb_client_secret", "")
        })
        
        if setup_dialog.exec() == QDialog.Accepted and setup_dialog.auth_data:
            self.config["igdb_client_id"] = setup_dialog.client_id_input.text().strip()
            self.config["igdb_client_secret"] = setup_dialog.client_secret_input.text().strip()
            self.config["igdb_auth"] = setup_dialog.auth_data
            self.save_config()
            
            if after_setup:
                after_setup()
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
        for game_name in list(self.config["games"].keys()):
            self.fetch_game_metadata(game_name)
            
    def show_game_context_menu(self, pos, widget):
        game_name = widget.property("game_name")
        if not game_name or game_name not in self.config["games"]:
            return
        
        context_menu = QMenu(self)
        
        rename_action = context_menu.addAction("Rename Game")
        edit_paths_action = context_menu.addAction("Edit Save Paths")
        fetch_metadata_action = context_menu.addAction("Fetch Metadata")
        custom_image_action = context_menu.addAction("Add Custom Image")
        
        open_menu = QMenu("Open Location", self)
        context_menu.addMenu(open_menu)
        
        open_backup_action = open_menu.addAction("Open Backup Directory")
        
        game_data = self.config["games"].get(game_name)
        save_path_actions = []
        
        if game_data and "save_paths" in game_data:
            for i, path in enumerate(game_data["save_paths"]):
                display_path = path
                if len(display_path) > 40:
                    display_path = "..." + display_path[-40:]
                    
                action = open_menu.addAction(f"Open Save Path: {display_path}")
                action.setData(path)
                save_path_actions.append(action)
        
        delete_action = context_menu.addAction("Delete Game")
        
        action = context_menu.exec(widget.mapToGlobal(pos))
        
        if action == rename_action:
            self.rename_game(game_name)
        elif action == edit_paths_action:
            self.edit_game_paths(game_name)
        elif action == fetch_metadata_action:
            self.fetch_game_metadata(game_name)
        elif action == custom_image_action:
            self.add_custom_image(game_name)
        elif action == open_backup_action:
            self.open_backup_directory(game_name)
        elif action in save_path_actions:
            path = action.data()
            self.open_save_path(path)
        elif action == delete_action:
            self.delete_game(game_name)

    def open_save_path(self, path):
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Path Not Found", f"The path does not exist:\n{path}")
            return
        
        try:
            if os.path.isdir(path):
                if sys.platform == 'win32':
                    os.startfile(os.path.normpath(path))
            else:
                parent_dir = os.path.dirname(path)
                if sys.platform == 'win32':
                    subprocess.run(['explorer', '/select,', os.path.normpath(path)], check=True)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open path: {e}")

    def rename_game(self, game_name):
        from PySide6.QtWidgets import QInputDialog
        
        new_name, ok = QInputDialog.getText(
            self, "Rename Game", "Enter new game name:", 
            QLineEdit.Normal, game_name
        )
        
        if not ok or not new_name or new_name == game_name:
            return
        
        if new_name in self.config["games"]:
            QMessageBox.warning(self, "Name Exists", f"A game with the name '{new_name}' already exists.")
            return
        
        self.config["games"][new_name] = self.config["games"][game_name].copy()
        del self.config["games"][game_name]
        
        self.save_config()
        self.load_games()
        self.update_games_list()
        QMessageBox.information(self, "Game Renamed", f"Game has been renamed to '{new_name}'.")
    
    def edit_game_paths(self, game_name):
        game_data = self.config["games"].get(game_name)
        if not game_data:
            return
        
        logger.info(f"Editing paths for: {game_name}")
        
        try:
            logger.info(f"Fetching PCGamingWiki data for: {game_name}")
            suggested_paths = utils.fetch_pcgamingwiki_save_locations(game_name)
            logger.info(f"PCGamingWiki returned {len(suggested_paths)} suggested paths")
        except Exception as e:
            logger.error(f"Error fetching PCGamingWiki data: {e}")
            suggested_paths = {}
        
        dialog = SaveSelectionDialog(self, game_name, self.config.get("igdb_auth"), suggested_paths)
        if dialog.exec() != QDialog.Accepted:
            return
        
        selected_paths = dialog.selected_paths
        
        if not selected_paths:
            return
        
        if len(selected_paths) == 1:
            if os.path.isdir(selected_paths[0]):
                save_parent_dir = selected_paths[0]
            else:
                save_parent_dir = os.path.dirname(selected_paths[0])
        else:
            parent_dirs = [os.path.dirname(path) if not os.path.isdir(path) else path for path in selected_paths]
            common_parent = os.path.commonpath(parent_dirs)
            save_parent_dir = common_parent
        
        self.config["games"][game_name]["save_paths"] = selected_paths
        self.config["games"][game_name]["parent_dir"] = save_parent_dir
        
        self.save_config()
        QMessageBox.information(self, "Paths Updated", f"Save paths for '{game_name}' have been updated.")
    
    def open_backup_directory(self, game_name):
        game_data = self.config["games"].get(game_name)
        if not game_data:
            return
        
        game_folder_name = utils.make_safe_filename(game_name)
        backup_dir = os.path.join(self.config["backup_dir"], game_folder_name)
        
        if not os.path.exists(backup_dir):
            try:
                os.makedirs(backup_dir, exist_ok=True)
                QMessageBox.information(self, "Directory Created", 
                                     f"Backup directory for '{game_name}' has been created.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to create backup directory: {e}")
                return
        
        if not utils.open_directory(backup_dir):
            QMessageBox.warning(self, "Error", "Failed to open directory")
    
    def delete_game(self, game_name):
        confirm = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete '{game_name}' from Ambidex?\n\nThis will not delete your backup files, but the game entry will be removed from the list.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if confirm != QMessageBox.Yes:
            return
        
        if game_name in self.config["games"]:
            del self.config["games"][game_name]
            
            self.save_config()
            
            self.load_games()
            self.update_games_list()
            QMessageBox.information(self, "Game Deleted", f"'{game_name}' has been removed.")

    def restore_backup(self):
        from PySide6.QtWidgets import QDialog, QInputDialog, QLineEdit
        
        if not hasattr(self, "selected_backup"):
            return
        
        game_name = self.games_list.currentItem().text()
        if not game_name:
            return
        
        game_data = self.config["games"].get(game_name)
        if not game_data:
            return
        
        confirm = QMessageBox.question(
            self, 
            "Confirm Restore", 
            f"This will first backup your current saves and then restore the selected backup from {self.selected_backup['datetime']}.\n\nDo you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if confirm != QMessageBox.Yes:
            return
        
        self.backup_game(game_name)
        
        backup_dir = self.selected_backup["directory"]
        parent_dir = game_data.get("parent_dir", "")
        
        parent_dir_file = os.path.join(backup_dir, "parent_dir.txt")
        if os.path.exists(parent_dir_file):
            with open(parent_dir_file, 'r') as f:
                backup_parent_dir = f.read().strip()
            if backup_parent_dir and not parent_dir:
                parent_dir = backup_parent_dir
        
        for save_path in game_data["save_paths"]:
            try:
                if parent_dir and save_path.startswith(parent_dir):
                    rel_path = os.path.relpath(save_path, parent_dir)
                    src = os.path.join(backup_dir, rel_path)
                else:
                    base_name = os.path.basename(save_path)
                    src = os.path.join(backup_dir, base_name)
                
                if not os.path.exists(src):
                    if os.path.isdir(save_path):
                        for item in os.listdir(backup_dir):
                            if item == os.path.basename(save_path) and os.path.isdir(os.path.join(backup_dir, item)):
                                src = os.path.join(backup_dir, item)
                                break
                    else:
                        for item in os.listdir(backup_dir):
                            if item == os.path.basename(save_path) and not os.path.isdir(os.path.join(backup_dir, item)):
                                src = os.path.join(backup_dir, item)
                                break
                
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

    def set_igdb_api_source(self, source, force=False):
        if source not in ["ambidex", "legacy"]:
            return
            
        if source == "legacy" and not self.config.get("igdb_auth") and not force:
            reply = QMessageBox.question(
                self,
                "IGDB API Setup Required",
                "Using the Legacy Twitch IGDB API requires setup with your Twitch Developer credentials.\n\n"
                "Would you like to set up your Twitch IGDB API credentials now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply == QMessageBox.Yes:
                self.show_api_setup(lambda: self.set_igdb_api_source("legacy"))
                return
            else:
                self.ambidex_api_action.setChecked(False)
                self.set_igdb_api_source("legacy", force=True)
                self.legacy_api_action.setChecked(True)
                return
                
        self.config["igdb_api_source"] = source
        self.save_config()
        
        self.ambidex_api_action.setChecked(source == "ambidex")
        self.legacy_api_action.setChecked(source == "legacy")

    def add_custom_image(self, game_name):
        if game_name not in self.config["games"]:
            return
            
        file_dialog = QFileDialog()
        image_file, _ = file_dialog.getOpenFileName(
            self,
            "Select Image File",
            "",
            "Image Files (*.jpg *.jpeg *.png *.webp *.bmp)"
        )
        
        if not image_file or not os.path.exists(image_file):
            return
            
        images_dir = os.path.join(self.app_dir, "images")
        try:
            os.makedirs(images_dir, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create images directory: {e}")
            return
            
        safe_name = utils.make_safe_filename(game_name)
        file_ext = os.path.splitext(image_file)[1].lower()
        dest_file = os.path.join(images_dir, f"{safe_name}{file_ext}")
        
        try:
            shutil.copy2(image_file, dest_file)
            self.config["games"][game_name]["image"] = dest_file
            self.save_config()
            self.load_games()
            QMessageBox.information(self, "Image Added", f"Custom image for '{game_name}' has been added.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to copy image: {e}")

def main():
    app = QApplication(sys.argv)
    
    icon_path = "icon.ico"
    app.setWindowIcon(QIcon(icon_path))
    
    window = GameSaveBackup()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
