import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QFormLayout, QMessageBox, QListWidget, QListWidgetItem, QFileDialog,
    QListView, QTreeView, QAbstractItemView, QRadioButton, QButtonGroup,
    QWidget, QLayout, QSizePolicy, QMenu, QColorDialog, QFrame,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle, QScrollArea,
    QApplication
)
from PySide6.QtCore import (
    Qt, QSize, Signal, QMimeData, QRect, QPoint, QThreadPool
)
from PySide6.QtGui import (
    QPixmap, QIcon, QDrag, QPainter, QColor, QCursor, QTextDocument
)
from workers import IGDBAuthWorker, IGDBGameSearchWorker, APITestWorker
import utils

class IGDBSetupDialog(QDialog):
    setup_complete = Signal(dict)
    
    def __init__(self, parent=None, current_settings=None):
        super().__init__(parent)
        self.setWindowTitle("IGDB API Setup")
        self.resize(500, 300)
        
        self.settings = current_settings or {}
        self.auth_data = None
        
        self.threadpool = QThreadPool.globalInstance()
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        
        self.client_id_input = QLineEdit()
        if self.settings.get("client_id"):
            self.client_id_input.setText(self.settings["client_id"])
        form.addRow("Client ID:", self.client_id_input)
        
        self.client_secret_input = QLineEdit()
        if self.settings.get("client_secret"):
            self.client_secret_input.setText(self.settings["client_secret"])
        form.addRow("Client Secret:", self.client_secret_input)
        
        layout.addLayout(form)
        
        self.status_label = QLabel()
        self.status_label.setText("Register for free at https://dev.twitch.tv/console and create an application to get a Client ID and Secret.")
        layout.addWidget(self.status_label)
        
        instructions = QLabel(
            "1. Go to https://dev.twitch.tv/console\n"
            "2. Register and create a new application\n"
            "3. Set the OAuth Redirect URL to http://localhost\n"
            "4. Set the Category to 'Application Integration'\n"
            "5. Set the Client Type to Confidential\n"
            "6. Copy the Client ID and Client Secret here"
        )
        layout.addWidget(instructions)
        
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
        
        worker = IGDBAuthWorker(client_id, client_secret)
        worker.signals.auth_complete.connect(self.on_auth_complete)
        worker.signals.auth_failed.connect(self.on_auth_failed)
        worker.signals.finished.connect(lambda: self.test_button.setEnabled(True))
        
        self.threadpool.start(worker)
    
    def on_auth_complete(self, auth_data):
        self.auth_data = auth_data
        self.status_label.setText("Authentication successful. Testing API connection...")
        
        worker = APITestWorker(auth_data)
        worker.signals.auth_complete.connect(lambda success: self.on_api_test_complete())
        worker.signals.auth_failed.connect(self.on_api_test_failed)
        
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
        self.resize(400, 200)
        
        self.auth_data = auth_data
        self.game_name = game_name
        self.selected_game = None
        
        self.threadpool = QThreadPool.globalInstance()
        
        self.init_ui()
        self.search_game()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        self.status_label = QLabel(f"Searching for '{self.game_name}'...")
        layout.addWidget(self.status_label)
        
        self.game_list = QListWidget()
        self.game_list.itemClicked.connect(self.on_game_selected)
        layout.addWidget(self.game_list)
        
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
        worker = IGDBGameSearchWorker(self.auth_data, self.game_name)
        worker.signals.search_complete.connect(self.on_search_complete)
        worker.signals.search_failed.connect(self.on_search_failed)
        
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
        
        self.game_list.itemDoubleClicked.connect(self.accept)

    def on_search_failed(self, error_message):
        self.status_label.setText(f"Error: {error_message}")
    
    def on_game_selected(self, item):
        self.selected_game = item.data(Qt.UserRole)
        self.select_button.setEnabled(True)


class LoadingDialog(QDialog):
    def __init__(self, parent=None, message="Loading..."):
        super().__init__(parent)
        self.setWindowTitle("Please wait")
        self.setFixedSize(400, 150)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        
        self.setStyleSheet("""
            QDialog {
                background-color: rgba(40, 40, 40, 240);
                border: 1px solid #555;
                border-radius: 8px;
            }
            QLabel {
                color: white;
                background-color: transparent;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignCenter)
        
        self.message_label = QLabel(message)
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.message_label)
        
        self.detail_label = QLabel("")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setStyleSheet("font-size: 12px; color: #aaa;")
        layout.addWidget(self.detail_label)
        
        self.setWindowOpacity(0.95)
    
    def set_message(self, message):
        self.message_label.setText(message)
    
    def set_detail(self, detail):
        self.detail_label.setText(detail)
    
    def center_on_parent(self):
        if self.parent():
            parent_pos = self.parent().geometry()
            x = parent_pos.x() + (parent_pos.width() - self.width()) // 2
            y = parent_pos.y() + (parent_pos.height() - self.height()) // 2
            self.move(x, y)


class SaveSelectionDialog(QDialog):
    def __init__(self, parent=None, game_name="", auth_data=None, suggested_paths=None):
        super().__init__(parent)
        self.setWindowTitle("Game Save Selection")
        self.setMinimumWidth(500)
        self.setMinimumHeight(300)
        
        self.selected_paths = []
        self.game_name = game_name
        self.auth_data = auth_data
        self.suggested_paths = suggested_paths or {}  # Now a dict of store types and paths
        self.threadpool = QThreadPool.globalInstance()
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)  # Reduce overall spacing
        
        # Game name display
        if self.game_name:
            name_label = QLabel(f"<h2>{self.game_name}</h2>")
            name_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(name_label)
        else:
            # Simple input for game name if not provided
            name_layout = QHBoxLayout()
            
            self.game_name_input = QLineEdit()
            self.game_name_input.setPlaceholderText("Enter the game name")
            name_layout.addWidget(self.game_name_input, 1)
            
            search_button = QPushButton("Search")
            search_button.clicked.connect(self.search_game_name)
            name_layout.addWidget(search_button)
            
            layout.addLayout(name_layout)
            
            status_layout = QHBoxLayout()
            self.status_label = QLabel("Enter a game name to search for its save location")
            status_layout.addWidget(self.status_label)
            layout.addLayout(status_layout)
        
        # Create a scroll area to contain all content and handle resizing gracefully
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)  # Tighter spacing between elements
        
        # Selection options
        options_group = QWidget()
        options_layout = QVBoxLayout(options_group)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(4)  # Reduce spacing between radio buttons
        
        options_header = QLabel("<b>Select Save Location:</b>")
        options_header.setStyleSheet("font-size: 12px;")
        options_layout.addWidget(options_header)
        
        radio_layout = QHBoxLayout()  # Use horizontal layout for radio buttons
        radio_layout.setContentsMargins(0, 0, 0, 0)
        radio_layout.setSpacing(10)
        
        self.option_group = QButtonGroup(self)
        self.files_option = QRadioButton("Select individual save files")
        self.directory_option = QRadioButton("Define save directory")
        self.option_group.addButton(self.files_option)
        self.option_group.addButton(self.directory_option)
        
        # Default selection
        self.files_option.setChecked(True)
        
        radio_layout.addWidget(self.files_option)
        radio_layout.addWidget(self.directory_option)
        radio_layout.addStretch(1)  # Add stretch to keep radio buttons left-aligned
        options_layout.addLayout(radio_layout)
        
        # Suggested paths section with improved styling - reduce margin
        suggested_label = QLabel("<b>Suggested Save Locations:</b>")
        suggested_label.setStyleSheet("font-size: 12px;")
        options_layout.addWidget(suggested_label, 0, Qt.AlignLeft)
        
        # Create a table for the paths with better fixed height
        self.paths_table = QListWidget()
        self.paths_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.paths_table.setItemDelegate(HTMLDelegate())
        self.paths_table.setMinimumHeight(50)  # Reduce minimum height
        self.paths_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)  # Use Preferred instead of Expanding
        self.paths_table.setAlternatingRowColors(True)
        self.paths_table.setStyleSheet("""
            QListWidget::item { padding: 4px; }
            QListWidget::item:selected { background-color: #0078d4; color: white; }
        """)
        self.paths_table.itemDoubleClicked.connect(self.use_suggested_path)
        
        options_layout.addWidget(self.paths_table)
        
        content_layout.addWidget(options_group)
        
        # Populate table if we have suggestions
        has_valid_paths = False
        if self.suggested_paths:
            for store_type, path in self.suggested_paths.items():
                # Check if the path exists or parent directory exists
                path_exists = os.path.exists(path)
                parent_exists = os.path.exists(os.path.dirname(path))
                
                # Only add it if the path or parent directory exists
                if path_exists or parent_exists:
                    has_valid_paths = True
                    item = QListWidgetItem()
                    
                    store_display = f"{store_type}: "
                    path_display = path
                    item.setText(f"<b>{store_display}</b>{path_display}")
                    
                    # Use font formatting instead of HTML
                    font = item.font()
                    item.setFont(font)
                    
                    # Set color using the item's foreground
                    if path_exists:
                        item.setForeground(QColor("#c9deff"))
                    else:
                        item.setForeground(QColor("gray"))
                    
                    item.setData(Qt.UserRole, {"store": store_type, "path": path, "exists": path_exists})
                    if path_exists:
                        item.setIcon(QIcon.fromTheme("dialog-ok") or QIcon())
                    self.paths_table.addItem(item)
        
        if not has_valid_paths:
            # Show placeholder
            item = QListWidgetItem("No suggested paths available on this system")
            item.setForeground(QColor(128, 128, 128))
            item.setTextAlignment(Qt.AlignCenter)
            self.paths_table.addItem(item)
            self.paths_table.setEnabled(False)
        
        # Info label for double-clicking
        if has_valid_paths:
            hint_label = QLabel("Double-click a path to use it or click 'Proceed' to select manually")
            hint_label.setAlignment(Qt.AlignCenter)
            hint_label.setStyleSheet("font-style: italic; color: #666; font-size: 10px;")  # Smaller font
            content_layout.addWidget(hint_label, 0, Qt.AlignCenter)
        
        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area, 1)  # Give it a stretch factor of 1
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.proceed_button = QPushButton("Proceed")
        self.proceed_button.clicked.connect(self.handle_selection)
        button_layout.addWidget(self.proceed_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        # Disable proceed button if no game name provided
        if not self.game_name:
            self.proceed_button.setEnabled(False)
    
    def search_game_name(self):
        game_name = self.game_name_input.text().strip()
        if not game_name:
            QMessageBox.warning(self, "Missing Information", "Please enter a game name")
            return
        
        self.game_name = game_name
        self.status_label.setText(f"Searching for '{game_name}'...")
        self.game_name_input.setEnabled(False)
        
        loading_dialog = LoadingDialog(self, f"Searching for save locations for '{game_name}'")
        loading_dialog.center_on_parent()
        loading_dialog.show()
        QApplication.processEvents()
        
        # First, try to fetch from IGDB if auth data is available
        if self.auth_data:
            worker = IGDBGameSearchWorker(self.auth_data, game_name)
            worker.signals.search_complete.connect(lambda games: self.on_search_complete(games, loading_dialog))
            worker.signals.search_failed.connect(lambda _: self.fetch_wiki_save_locations(game_name, loading_dialog))
            worker.signals.finished.connect(lambda: self.game_name_input.setEnabled(True))
            
            self.threadpool.start(worker)
        else:
            # If no IGDB auth, go straight to PCGamingWiki
            self.fetch_wiki_save_locations(game_name, loading_dialog)

    def on_search_complete(self, games, loading_dialog):
        if not games:
            # No results from IGDB, try PCGamingWiki with original name
            self.status_label.setText("No games found on IGDB, checking PCGamingWiki...")
            loading_dialog.set_message("No games found on IGDB")
            loading_dialog.set_detail("Checking PCGamingWiki...")
            self.fetch_wiki_save_locations(self.game_name_input.text().strip(), loading_dialog)
            return
        
        # Use the first result's official name
        game = games[0]
        official_name = game["name"]
        self.game_name = official_name
        self.game_name_input.setText(official_name)
        
        # Now fetch save locations with the official name
        loading_dialog.set_message(f"Found game: {official_name}")
        loading_dialog.set_detail("Fetching save locations from PCGamingWiki...")
        self.fetch_wiki_save_locations(official_name, loading_dialog)
    
    def fetch_wiki_save_locations(self, game_name, loading_dialog):
        self.status_label.setText(f"Fetching save locations for '{game_name}' from PCGamingWiki...")
        
        # Make sure the loading overlay is visible
        loading_dialog.setVisible(True)
        loading_dialog.raise_()
        QApplication.processEvents()  # Force UI update
        
        # Run in a separate thread to avoid freezing the UI
        import threading
        
        def fetch_thread():
            from utils import fetch_pcgamingwiki_save_locations
            paths = fetch_pcgamingwiki_save_locations(game_name)
            
            # Update the UI in the main thread
            from PySide6.QtCore import QMetaObject, Qt, Q_ARG, QObject
            QMetaObject.invokeMethod(
                self, "update_suggested_paths", 
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(QObject, paths),
                Q_ARG(QObject, loading_dialog)
            )
        
        thread = threading.Thread(target=fetch_thread)
        thread.daemon = True
        thread.start()
    
    def update_suggested_paths(self, paths_dict, loading_dialog):
        # Hide the loading overlay
        loading_dialog.close()
        
        self.suggested_paths = paths_dict
        self.paths_table.clear()
        
        has_valid_paths = False
        for store_type, path in self.suggested_paths.items():
            # Check if the path exists or parent directory exists
            path_exists = os.path.exists(path)
            parent_exists = os.path.exists(os.path.dirname(path))
            
            # Only add it if the path or parent directory exists
            if path_exists or parent_exists:
                has_valid_paths = True
                item = QListWidgetItem()
                
                # Don't use HTML formatting to avoid rendering issues
                store_display = f"{store_type}: "
                path_display = path
                item.setText(f"{store_display}{path_display}")
                
                # Use font formatting instead of HTML
                font = item.font()
                font.setBold(True)  # Make store type bold
                item.setFont(font)
                
                # Set color using the item's foreground
                if path_exists:
                    item.setForeground(QColor("darkgreen"))
                else:
                    item.setForeground(QColor("gray"))
                
                item.setData(Qt.UserRole, {"store": store_type, "path": path, "exists": path_exists})
                if path_exists:
                    item.setIcon(QIcon.fromTheme("dialog-ok") or QIcon())
                self.paths_table.addItem(item)
        
        if not has_valid_paths:
            path_count = len(paths_dict)
            if path_count > 0:
                self.status_label.setText(f"Found {path_count} save locations, but none exist on this system")
            else:
                self.status_label.setText("No save locations found")
                
            # Show placeholder
            item = QListWidgetItem("No suggested paths available on this system")
            item.setForeground(QColor(128, 128, 128))
            item.setTextAlignment(Qt.AlignCenter)
            self.paths_table.addItem(item)
            self.paths_table.setEnabled(False)
        else:
            self.status_label.setText(f"Found {len(paths_dict)} suggested save locations")
            self.paths_table.setEnabled(True)
        
        # Enable the proceed button now that we've finished searching
        self.proceed_button.setEnabled(True)
    
    def showEvent(self, event):
        # Ensure overlay covers the entire dialog when shown
        if hasattr(self, 'loading_overlay'):
            self.loading_overlay.setGeometry(0, 0, self.width(), self.height())
        super().showEvent(event)
    
    def resizeEvent(self, event):
        # Ensure loading overlay covers the entire dialog when resized
        if hasattr(self, 'loading_overlay'):
            self.loading_overlay.setGeometry(0, 0, self.width(), self.height())
        super().resizeEvent(event)
    
    def use_suggested_path(self, item):
        path_data = item.data(Qt.UserRole)
        if not path_data:  # No data means it's the placeholder
            return
            
        path = path_data["path"]
        
        if path_data["exists"]:
            # If it exists, select it directly
            self.selected_paths = [path]
            if os.path.isdir(path):
                self.directory_option.setChecked(True)
            else:
                self.files_option.setChecked(True)
            self.accept()
        else:
            # If parent directory exists but not the path itself
            parent_dir = os.path.dirname(path)
            if os.path.exists(parent_dir):
                # If it doesn't exist, ask what to do
                msg = QMessageBox(self)
                msg.setWindowTitle("Path Not Found")
                msg.setText(f"The suggested path does not exist:\n{path}")
                msg.setInformativeText(f"Do you want to create this directory?\n\nStore type: {path_data['store']}")
                msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
                msg.setDefaultButton(QMessageBox.Yes)
                
                result = msg.exec()
                
                if result == QMessageBox.Yes:
                    # Create directory
                    try:
                        os.makedirs(path, exist_ok=True)
                        self.selected_paths = [path]
                        self.directory_option.setChecked(True)
                        self.accept()
                    except Exception as e:
                        QMessageBox.critical(self, "Error", f"Failed to create directory: {e}")
                elif result == QMessageBox.No:
                    # Proceed with normal selection
                    if self.files_option.isChecked():
                        self.select_files()
                    else:
                        self.define_directory()
            else:
                QMessageBox.warning(
                    self, 
                    "Path Not Available", 
                    f"The parent directory does not exist:\n{parent_dir}\n\nPlease select a different location."
                )
    
    def handle_selection(self):
        if self.files_option.isChecked():
            self.select_files()
        else:
            self.define_directory()
    
    def select_files(self):
        file_dialog = QFileDialog(self)
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        file_dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        
        file_view = file_dialog.findChild(QListView, "listView")
        if file_view:
            file_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        
        tree_view = file_dialog.findChild(QTreeView)
        if tree_view:
            tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        
        if not file_dialog.exec():
            return
        
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
    game_moved = Signal(str, str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.drag_indicator = None
        self.drop_indicator = QWidget(self)
        self.drop_indicator.setFixedWidth(2)
        self.drop_indicator.setStyleSheet("background-color: #0078d4;")
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
            while target_widget and not target_widget.property("game_name"):
                target_widget = target_widget.parent()
            
            if target_widget:
                target_pos = target_widget.pos()
                target_center = target_pos.x() + target_widget.width() / 2
                
                if pos.x() < target_center:
                    self.drop_indicator.setGeometry(
                        target_pos.x() - 1,
                        target_pos.y(),
                        2,
                        target_widget.height()
                    )
                else:
                    self.drop_indicator.setGeometry(
                        target_pos.x() + target_widget.width() - 1,
                        target_pos.y(),
                        2,
                        target_widget.height()
                    )
                
                self.drop_indicator.setStyleSheet("background-color: #0078d4;")
                self.drop_indicator.raise_()
                self.drop_indicator.show()
                return
        
        self.drop_indicator.hide()

    def start_drag(self, event, widget):
        if event.button() == Qt.LeftButton:
            pixmap = widget.grab()
            
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            painter.fillRect(pixmap.rect(), QColor(0, 0, 0, 180))
            painter.end()
            
            drag = QDrag(widget)
            mime_data = QMimeData()
            mime_data.setText(widget.property("game_name"))
            drag.setMimeData(mime_data)
            drag.setPixmap(pixmap)
            drag.setHotSpot(event.position().toPoint())
            
            drag.exec(Qt.MoveAction)


class BackupLabelDialog(QDialog):
    """Dialog for adding or editing labels and color tags for save backups"""
    def __init__(self, parent=None, current_label="", current_color=None):
        super().__init__(parent)
        self.setWindowTitle("Save Backup Label")
        self.resize(400, 200)
        
        self.selected_label = current_label
        self.selected_color = current_color or QColor("#FFFFFF")
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        self.label_input = QLineEdit()
        self.label_input.setText(self.selected_label)
        self.label_input.setPlaceholderText("Enter a descriptive label for this save")
        form.addRow("Label:", self.label_input)
        layout.addLayout(form)
        
        color_layout = QHBoxLayout()
        
        self.color_preview = QFrame()
        self.color_preview.setFixedSize(40, 40)
        self.color_preview.setStyleSheet(f"background-color: {self.selected_color.name()}; border: 1px solid #888;")
        color_layout.addWidget(self.color_preview)
        
        color_button = QPushButton("Select Color")
        color_button.clicked.connect(self.select_color)
        color_layout.addWidget(color_button)
        
        presets_layout = QHBoxLayout()
        presets = [
            ("#4CAF50", "Green"), 
            ("#2196F3", "Blue"), 
            ("#FFC107", "Yellow"), 
            ("#FF5722", "Orange"), 
            ("#E91E63", "Pink"),
            ("#9C27B0", "Purple"),
            ("#607D8B", "Gray"),
            ("#FFFFFF", "White")
        ]
        
        for color_hex, color_name in presets:
            preset_btn = QPushButton()
            preset_btn.setFixedSize(30, 30)
            preset_btn.setStyleSheet(f"background-color: {color_hex}; border: 1px solid #888;")
            preset_btn.setToolTip(color_name)
            preset_btn.clicked.connect(lambda checked=False, hex=color_hex: self.use_preset_color(hex))
            presets_layout.addWidget(preset_btn)
        
        layout.addLayout(color_layout)
        layout.addLayout(presets_layout)
        
        buttons_layout = QHBoxLayout()
        
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.accept)
        buttons_layout.addWidget(save_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)
        
        layout.addLayout(buttons_layout)
        
    def select_color(self):
        color = QColorDialog.getColor(self.selected_color, self, "Choose Color Tag")
        if color.isValid():
            self.selected_color = color
            self.color_preview.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #888;")
    
    def use_preset_color(self, color_hex):
        self.selected_color = QColor(color_hex)
        self.color_preview.setStyleSheet(f"background-color: {color_hex}; border: 1px solid #888;")
    
    def get_values(self):
        return self.label_input.text(), self.selected_color.name()


class GameNameSuggestionDialog(QDialog):
    """Dialog for suggesting game names based on file paths"""
    def __init__(self, parent=None, suggestions=None):
        super().__init__(parent)
        self.setWindowTitle("Game Title")
        self.resize(400, 75)  # Increase height to accommodate suggestions list
        
        self.suggestions = suggestions or []
        self.selected_name = ""
        self.loading = False
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Add description label
        description = QLabel("Enter or select a name for this game:")
        description.setStyleSheet("font-weight: bold;")
        layout.addWidget(description)
        
        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter the game's title")
        form.addRow("Game Title:", self.name_input)
        layout.addLayout(form)
        
        buttons_layout = QHBoxLayout()
        
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept_name)
        buttons_layout.addWidget(self.ok_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)
        
        layout.addLayout(buttons_layout)
        
        # Populate suggestions if available
        if self.suggestions:
            self.populate_suggestions(self.suggestions)
    
    def populate_suggestions(self, suggestions):
        """Populate the suggestions list"""
        self.suggestions_list.clear()
        if suggestions:
            self.suggestions_list.addItems(suggestions)
            self.suggestions_list.setCurrentRow(0) if suggestions else None
        else:
            self.suggestions_list.addItem("No suggestions available")
            self.suggestions_list.setEnabled(False)
    
    def on_suggestion_clicked(self, item):
        """Handle suggestion click"""
        self.name_input.setText(item.text())
    
    def on_suggestion_double_clicked(self, item):
        """Handle suggestion double-click by accepting the dialog"""
        self.name_input.setText(item.text())
        self.accept_name()
    
    def accept_name(self):
        """Validate and accept the entered name"""
        self.selected_name = self.name_input.text().strip()
        if self.selected_name:
            self.accept()
        else:
            QMessageBox.warning(self, "Missing Title", "Please enter or select a game title.")
    
    def set_loading(self, is_loading):
        """Show/hide the loading indicator"""
        self.loading = is_loading
        self.loading_label.setVisible(is_loading)
        self.suggestions_list.setVisible(not is_loading)
        self.ok_button.setEnabled(not is_loading)
        
        if is_loading:
            self.suggestions_list.clear()
            QApplication.processEvents()  # Force UI update
    
    def closeEvent(self, event):
        """Handle window close events"""
        if self.loading:
            # If loading, interpret as cancel
            self.selected_name = ""
            self.reject()
        else:
            # Normal close behavior
            event.accept()

class HTMLDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        text = index.data()
        doc = QTextDocument()
        doc.setHtml(text)
        doc.setTextWidth(option.rect.width())
        painter.translate(option.rect.topLeft())
        doc.drawContents(painter)
        painter.restore()

    def sizeHint(self, option, index):
        doc = QTextDocument()
        doc.setHtml(index.data())
        doc.setTextWidth(option.rect.width())
        return doc.size().toSize()

class BackupItemDelegate(QStyledItemDelegate):
    """Custom delegate for backup items to show color bar on left side"""
    def paint(self, painter, option, index):
        backup = index.data(Qt.UserRole)
        if not backup:
            return super().paint(painter, option, index)
        
        color_hex = backup.get("color", "#FFFFFF")
        
        super().paint(painter, option, index)
        
        if color_hex and color_hex != "#FFFFFF":
            painter.save()
            
            color_bar_width = 2
            color_rect = QRect(option.rect)
            color_rect.setWidth(color_bar_width)
            painter.fillRect(color_rect, QColor(color_hex))
            
            painter.restore()
