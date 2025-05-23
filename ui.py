import os
import re
import glob
import urllib.parse
import threading
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QFormLayout, QMessageBox, QListWidget, QListWidgetItem, QFileDialog,
    QListView, QTreeView, QAbstractItemView, QRadioButton, QButtonGroup,
    QWidget, QLayout, QSizePolicy, QColorDialog, QFrame,
    QStyledItemDelegate, QScrollArea, QCheckBox,
    QApplication, QProgressBar, QStyle
)
from PySide6.QtCore import (
    Qt, QSize, Signal, QMimeData, QRect, QPoint, QThreadPool, QTimer, QPropertyAnimation, QEasingCurve, QObject, QPointF
)
from PySide6.QtGui import (
    QIcon, QDrag, QPainter, QColor, QTextDocument, QPalette, QPixmap, QPen, QPainterPath
)
from workers import LegacyIGDBAuthWorker, LegacyIGDBGameSearchWorker, LegacyAPITestWorker, IGDBGameSearchWorker
from utils import get_windows_accent_color, is_windows_11_or_later


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
        
        worker = LegacyIGDBAuthWorker(client_id, client_secret)
        worker.signals.auth_complete.connect(self.on_auth_complete)
        worker.signals.auth_failed.connect(self.on_auth_failed)
        worker.signals.finished.connect(lambda: self.test_button.setEnabled(True))
        
        self.threadpool.start(worker)
    
    def on_auth_complete(self, auth_data):
        self.auth_data = auth_data
        self.status_label.setText("Authentication successful. Testing API connection...")
        
        worker = LegacyAPITestWorker(auth_data)
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
    def __init__(self, parent=None, auth_data=None, game_name="", games=None, allow_custom_name=False):
        super().__init__(parent)
        self.setWindowTitle(f"Search for {game_name}")
        self.resize(400, 350) # Adjusted height slightly for progress bar
        
        self.auth_data = auth_data
        self.game_name = game_name
        self.selected_game = None
        self.use_custom_name = False
        self.precached_games = games
        self.allow_custom_name = allow_custom_name
        
        self.threadpool = QThreadPool.globalInstance()
        
        self.init_ui()
        
        if not self.precached_games:
            self.search_game()
        else:
            self.on_search_complete(self.precached_games)
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        self.status_label = QLabel(f"Searching for '{self.game_name}'...")
        layout.addWidget(self.status_label)

        self.loading_indicator = QProgressBar(self)
        self.loading_indicator.setRange(0, 0)  # Indeterminate
        self.loading_indicator.setTextVisible(False)
        self.loading_indicator.setFixedHeight(8)
        accent_color = get_windows_accent_color() if is_windows_11_or_later() else "#0078d4"
        self.loading_indicator.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid grey;
                border-radius: 3px;
                text-align: center;
                background-color: #444; /* Slightly darker background */
            }}
            QProgressBar::chunk {{
                background-color: {accent_color};
                width: 10px; 
                margin: 0.5px;
            }}
        """)
        self.loading_indicator.setVisible(True)  # Initially hidden
        layout.addWidget(self.loading_indicator)
        
        self.game_list = QListWidget()
        self.game_list.itemClicked.connect(self.on_game_selected)
        layout.addWidget(self.game_list)
        
        if self.allow_custom_name:
            self.custom_name_checkbox = QCheckBox(f"Use my own name: '{self.game_name}'")
            self.custom_name_checkbox.toggled.connect(self.toggle_custom_name)
            layout.addWidget(self.custom_name_checkbox)
        
        button_layout = QHBoxLayout()
        
        self.select_button = QPushButton("Select Game")
        self.select_button.clicked.connect(self.accept)
        self.select_button.setEnabled(False)
        button_layout.addWidget(self.select_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
    
    def toggle_custom_name(self, checked):
        """Handle toggling of custom name checkbox"""
        self.use_custom_name = checked
        self.game_list.setEnabled(not checked)
        
        if checked:
            self.select_button.setEnabled(True)
        elif self.selected_game:
            self.select_button.setEnabled(True)
        else:
            self.select_button.setEnabled(False)
    
    def search_game(self):
        self.status_label.setText(f"Searching for '{self.game_name}'...")
        self.loading_indicator.setVisible(True)
        if self.auth_data:
            worker = LegacyIGDBGameSearchWorker(self.auth_data, self.game_name)
        else:
            from workers import IGDBGameSearchWorker
            worker = IGDBGameSearchWorker(self.game_name)
            
        worker.signals.search_complete.connect(self.on_search_complete)
        worker.signals.search_failed.connect(self.on_search_failed)
        
        self.threadpool.start(worker)
    
    def on_search_complete(self, games):
        self.loading_indicator.setVisible(False)
        if not games:
            self.status_label.setText(f"No results found for '{self.game_name}'")
            
            if self.allow_custom_name:
                self.custom_name_checkbox.setChecked(True)
                self.toggle_custom_name(True)
            
            return
        
        self.status_label.setText(f"Found {len(games)} results for '{self.game_name}'")
        self.game_list.clear()
        
        for game in games:
            item = QListWidgetItem(game["name"])
            item.setData(Qt.UserRole, game)
            self.game_list.addItem(item)
        
        self.game_list.itemDoubleClicked.connect(self.accept)

    def on_search_failed(self, error_message):
        self.loading_indicator.setVisible(False)
        self.status_label.setText(f"Error: {error_message}")
        
        if self.allow_custom_name:
            self.custom_name_checkbox.setChecked(True)
            self.toggle_custom_name(True)
    
    def on_game_selected(self, item):
        self.selected_game = item.data(Qt.UserRole)
        
        if not hasattr(self, 'custom_name_checkbox') or not self.custom_name_checkbox.isChecked():
            self.select_button.setEnabled(True)


class LoadingDialog(QDialog):
    def __init__(self, parent=None, message="Loading..."):
        super().__init__(parent)
        self.setWindowTitle("Please wait")
        self.setFixedSize(400, 150)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        palette = self.parent().palette() if self.parent() else QApplication.palette()
        is_dark_theme = palette.color(QPalette.ColorRole.Window).value() < 128
        
        if is_dark_theme:
            bg_color = "#222222" # Dark background
            text_color = "#ffffff"
        else: # Light Mode
            bg_color = "#bbbbbb"
            text_color = "#000000"
        
        self.setStyleSheet("""
            QDialog {
                background-color: {bg_color};
                border: 1px solid #555;
                border-radius: 8px;
            }
            QLabel {
                color: {text_color};
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
    def __init__(self, parent=None, game_name="", auth_data=None, suggested_paths=None, existing_cover_art_path=None): # Added existing_cover_art_path
        super().__init__(parent)
        self.setWindowTitle("Game Save Selection")
        self.setMinimumWidth(650) # Increased width for cover art
        self.setMinimumHeight(400) # Increased height
        
        self.selected_paths = []
        self.initial_game_name = game_name # Store initial game name
        self.game_name = game_name
        self.auth_data = auth_data
        self.suggested_paths_templates = suggested_paths or {} # Store original templates
        self.threadpool = QThreadPool.globalInstance()
        self.existing_cover_art_path = existing_cover_art_path
        self.custom_cover_art_path = None
        
        self.init_ui()
        if self.game_name: # Update PCGW link if game name is initialised
            self.update_pcgw_link()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)  
        
        # Top section for game name and PCGW link
        top_section_layout = QVBoxLayout()

        # Game Name Display/Input Area
        game_name_area_layout = QHBoxLayout()

        if self.game_name:
            self.game_name_label = QLabel(f"<h2>{self.game_name}</h2>")
            self.game_name_label.setAlignment(Qt.AlignCenter)
            game_name_area_layout.addWidget(self.game_name_label, 1) # Allow label to expand
        # Removed status_label initialization here

        top_section_layout.addLayout(game_name_area_layout)
        # Removed adding status_label to top_section_layout here

        self.pcgw_link_label = QLabel()
        self.pcgw_link_label.setAlignment(Qt.AlignCenter)
        self.pcgw_link_label.setOpenExternalLinks(True)
        self.pcgw_link_label.setVisible(bool(self.game_name)) # Visible if game_name initially set
        top_section_layout.addWidget(self.pcgw_link_label)
        
        layout.addLayout(top_section_layout)
            
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget) # Main content: Cover Art | Options
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        # Right side: Options and Paths
        options_and_paths_widget = QWidget()
        options_and_paths_layout = QVBoxLayout(options_and_paths_widget)
        options_and_paths_layout.setContentsMargins(0,0,0,0)
        options_and_paths_layout.setSpacing(4)
        
        options_group = QWidget()
        options_layout_inner = QVBoxLayout(options_group) # Renamed to avoid conflict
        options_layout_inner.setContentsMargins(0, 0, 0, 0)
        options_layout_inner.setSpacing(4)  
        
        options_header = QLabel("<b>Select Save Location:</b>")
        options_header.setStyleSheet("font-size: 12px;")
        options_layout_inner.addWidget(options_header)
        
        radio_layout = QHBoxLayout()  
        radio_layout.setContentsMargins(0, 0, 0, 0)
        radio_layout.setSpacing(10)
        
        self.option_group = QButtonGroup(self)
        self.files_option = QRadioButton("Select individual save files")
        self.directory_option = QRadioButton("Define save directory")
        self.option_group.addButton(self.files_option)
        self.option_group.addButton(self.directory_option)
        
        self.directory_option.setChecked(True) # Default to "Define save directory"
        
        radio_layout.addWidget(self.directory_option)
        radio_layout.addWidget(self.files_option)
        radio_layout.addStretch(1) 
        options_layout_inner.addLayout(radio_layout)
        options_and_paths_layout.addWidget(options_group) # Add options_group to the right side
        
        suggested_label = QLabel("<b>Suggested Save Locations (double-click to use):</b>")
        suggested_label.setStyleSheet("font-size: 12px;")
        options_and_paths_layout.addWidget(suggested_label, 0, Qt.AlignLeft)
        
        self.paths_table = QListWidget()
        self.paths_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.paths_table.setItemDelegate(HTMLDelegate(self.paths_table)) # Pass parent to delegate
        self.paths_table.setMinimumHeight(100) 
        self.paths_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)  
        self.paths_table.setAlternatingRowColors(True)
        self.paths_table.setStyleSheet("""
            QListWidget::item { padding: 4px; }
            QListWidget::item:selected { 
                background-color: %ACCENT_COLOR%; 
                color: white; 
            }
        """.replace("%ACCENT_COLOR%", get_windows_accent_color() if is_windows_11_or_later() else "#0078d4"))
        self.paths_table.itemDoubleClicked.connect(self.use_suggested_path)
        
        options_and_paths_layout.addWidget(self.paths_table)
        
        content_layout.addWidget(options_and_paths_widget, 1) # Add right side to main content QHBoxLayout
        
        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area, 1)  
        
        # Hint Label
        self.hint_label = QLabel("Double-click a path to use it or click 'Proceed' to select manually.")
        self.hint_label.setStyleSheet("font-size: 9pt; color: #888;")
        self.hint_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.hint_label)
        
        button_layout = QHBoxLayout()
        
        self.proceed_button = QPushButton("Proceed")
        self.proceed_button.clicked.connect(self.handle_selection)
        button_layout.addWidget(self.proceed_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)

        # Initial population of paths_table (will be empty if no initial suggested_paths)
        # The actual population happens in update_suggested_paths
        if self.suggested_paths_templates:
             # Call a non-UI blocking update, or ensure fetch_... then update_... is called
             # For now, let's assume initial population if data is present.
             # This might need to be async if paths_dict comes from a slow source initially.
             # The current flow is: init_ui, then if game_name, fetch happens, then update_suggested_paths.
             # If no game_name, search_game_name -> fetch -> update.
             # So, direct population here might be premature or use self.suggested_paths_templates
             self.update_suggested_paths(self.suggested_paths_templates, None) # Pass None for loading_dialog if not applicable here
        else:
            item = QListWidgetItem("No suggested paths available or game not specified.")
            item.setForeground(QColor(128, 128, 128))
            item.setTextAlignment(Qt.AlignCenter)
            self.paths_table.addItem(item)
            self.paths_table.setEnabled(False)
            # Removed status_label update here
        
        if not self.game_name:
            self.proceed_button.setEnabled(False) # Disabled if no game name to start with
            if hasattr(self, 'edit_game_name_button'): # Also disable edit button if no game name
                self.edit_game_name_button.setEnabled(False)


    def update_pcgw_link(self):
        if self.game_name:
            # PCGamingWiki uses underscores for spaces and then URL encodes.
            pcgw_game_name = self.game_name.replace(" ", "_")
            pcgw_game_name_encoded = urllib.parse.quote(pcgw_game_name)
            page_url = f"https://www.pcgamingwiki.com/wiki/{pcgw_game_name_encoded}#Save_game_data_location" # Appended section
            self.pcgw_link_label.setText(f'<a href="{page_url}" style="color: {get_windows_accent_color() if is_windows_11_or_later() else "#0078d4"};">View on PCGamingWiki</a>')
            self.pcgw_link_label.setVisible(True)
        else:
            self.pcgw_link_label.setVisible(False)

    def search_game_name(self):
        # This method is for when game_name is initially empty and user searches
        game_name_to_search = ""
        if hasattr(self, 'game_name_input_search'):
            game_name_to_search = self.game_name_input_search.text().strip()
        
        if not game_name_to_search:
            QMessageBox.warning(self, "Missing Information", "Please enter a game name")
            return
        
        self.game_name = game_name_to_search # Update internal game_name
        
        # Replace status_label with ProgressDialog
        if hasattr(self, 'progress_dialog_status') and self.progress_dialog_status:
            self.progress_dialog_status.set_message(f"Searching for '{self.game_name}'...")
        else:
            self.progress_dialog_status = ProgressDialog(self, f"Searching for '{self.game_name}'...", indeterminate=True)
            # Position it appropriately, e.g., by adding to a layout or showing as a modal dialog
            # For now, let's assume it's a modal dialog that will be shown later or managed by its own show() call.
            # If it needs to be embedded, its parent and layout need to be handled.
            # Example: top_section_layout.addWidget(self.progress_dialog_status) # If it were to be embedded

        if hasattr(self, 'game_name_input_search'):
            self.game_name_input_search.setEnabled(False)
        
        # If edit button exists, update its state based on the new game_name
        if hasattr(self, 'edit_game_name_button'):
            self.edit_game_name_button.setEnabled(bool(self.game_name))
            if self.game_name and not hasattr(self, 'game_name_label'): # If label wasn't created due to no initial name
                # We need to dynamically create the label and edit button area now
                # This part might require restructuring init_ui or a dedicated method to switch states
                # For now, assume search_game_name is primarily for the initial empty state.
                # A full dynamic switch is more complex.
                pass


        loading_dialog = LoadingDialog(self, f"Searching for save locations for '{self.game_name}'")
        loading_dialog.center_on_parent()
        loading_dialog.show()
        QApplication.processEvents()
        
        if self.auth_data:
            worker = LegacyIGDBGameSearchWorker(self.auth_data, game_name_to_search)
            worker.signals.search_complete.connect(lambda games: self.on_search_complete(games, loading_dialog))
            worker.signals.search_failed.connect(lambda _: self.fetch_wiki_save_locations(game_name_to_search, loading_dialog))
            worker.signals.finished.connect(lambda: self.game_name_input_search.setEnabled(True))
            
            self.threadpool.start(worker)
        else:
            self.fetch_wiki_save_locations(game_name_to_search, loading_dialog)

    def on_search_complete(self, games, loading_dialog):
        if not games:
            # self.status_label.setText("No games found on IGDB, checking PCGamingWiki...") # Replaced
            if hasattr(self, 'progress_dialog_status') and self.progress_dialog_status:
                self.progress_dialog_status.set_message("No games found on IGDB, checking PCGamingWiki...")
            self.update_pcgw_link() # Update link even if no IGDB games
            loading_dialog.set_message("No games found on IGDB")
            loading_dialog.set_detail("Checking PCGamingWiki...")
            # Use self.game_name which was set in search_game_name
            self.fetch_wiki_save_locations(self.game_name, loading_dialog)
            return
        
        game = games[0]
        official_name = game["name"]
        self.game_name = official_name
        
        # Update UI elements that display the game name
        if hasattr(self, 'game_name_label'):
            self.game_name_label.setText(f"<h2>{self.game_name}</h2>")
        if hasattr(self, 'game_name_input_search'): # If search input was used
            self.game_name_input_search.setText(self.game_name) # Update it
            # Potentially hide search input and show label/edit button - complex UI change
        if hasattr(self, 'game_name_input_edit'): # If edit input exists
            self.game_name_input_edit.setText(self.game_name)

        self.update_pcgw_link()
        
        loading_dialog.set_message(f"Found game: {official_name}")
        loading_dialog.set_detail("Fetching save locations from PCGamingWiki...")
        self.fetch_wiki_save_locations(official_name, loading_dialog)
    
    def fetch_wiki_save_locations(self, game_name, loading_dialog):
        # self.status_label.setText(f"Fetching save locations for '{game_name}' from PCGamingWiki...") # Replaced
        if hasattr(self, 'progress_dialog_status') and self.progress_dialog_status:
            self.progress_dialog_status.set_message(f"Fetching save locations for '{game_name}' from PCGamingWiki...")
        else: # Fallback if progress_dialog_status was not initialized (e.g. direct call)
            # This might indicate a need to ensure progress_dialog_status is always available when this method is called
            # For now, create it if it doesn't exist.
            self.progress_dialog_status = ProgressDialog(self, f"Fetching save locations for '{game_name}' from PCGamingWiki...", indeterminate=True)
            # self.progress_dialog_status.show() # Or manage its visibility as needed

        self.game_name = game_name # Ensure self.game_name is current
        self.update_pcgw_link() # Update link with current game_name

        loading_dialog.setVisible(True)
        loading_dialog.raise_()
        QApplication.processEvents()  
        
        
        def fetch_thread():
            from utils import fetch_pcgamingwiki_save_locations
            paths = fetch_pcgamingwiki_save_locations(game_name)
            
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
        if loading_dialog: # Can be None if called from init_ui
            loading_dialog.close()
        
        # Close or update the status progress dialog if it exists
        if hasattr(self, 'progress_dialog_status') and self.progress_dialog_status:
            # self.progress_dialog_status.close() # Or hide it, depending on desired behavior
            # For now, let's assume it should be closed once paths are updated.
            # If it's meant to persist with a new message, update its message instead.
            pass # Decide on behavior: close, hide, or update message

        self.suggested_paths_templates = paths_dict # Store original templates
        self.paths_table.clear()
        
        all_items_for_table = [] 

        for store_type, path_template in paths_dict.items():
            path_template = re.sub(r"&lt;[^>]+&gt;", "*", path_template)
            expanded_path_template = os.path.expandvars(path_template)
            expanded_path_template = os.path.expanduser(expanded_path_template)
            print(f"Expanded path template: {expanded_path_template}") # Debugging line

            if "*" in expanded_path_template:
                try:
                    # Ensure the base directory for glob exists if pattern is like "base_dir/*"
                    glob_base = os.path.dirname(expanded_path_template)
                    if not os.path.exists(glob_base) and "*" not in glob_base : # only glob if base exists or base itself is a pattern
                         all_items_for_table.append({
                            "store": store_type, "path": expanded_path_template, "original_template": path_template,
                            "display_text": f"<b>{store_type} (pattern, base missing):</b> {expanded_path_template}",
                            "exists": False, "is_pattern_base_missing": True
                        })
                         continue

                    matches = glob.glob(expanded_path_template, recursive=False) 
                    if matches:
                        for match_path in matches:
                            is_dir = os.path.isdir(match_path)
                            all_items_for_table.append({
                                "store": store_type, "path": match_path, "original_template": path_template,
                                "display_text": f"<b>{store_type} (match):</b> {match_path}",
                                "exists": True, 
                                "is_dir": is_dir
                            })
                except Exception as e: 
                    print(f"Error globbing {expanded_path_template}: {e}")
                    all_items_for_table.append({
                        "store": store_type, "path": expanded_path_template, "original_template": path_template,
                        "display_text": f"<b>{store_type} (pattern, error):</b> {expanded_path_template}",
                        "exists": False, "is_pattern_error": True
                    })
            else: 
                path_exists = os.path.exists(expanded_path_template)
                parent_exists = os.path.exists(os.path.dirname(expanded_path_template))
                if path_exists or parent_exists: # Add if path or its parent exists
                     all_items_for_table.append({
                        "store": store_type, "path": expanded_path_template, "original_template": path_template,
                        "display_text": f"<b>{store_type}:</b> {expanded_path_template}",
                        "exists": path_exists,
                        "is_dir": os.path.isdir(expanded_path_template) if path_exists else None
                    })
        
        has_directly_usable_paths = False
        if not all_items_for_table:
            item_text = "No suggested paths found or resolved."
            if not paths_dict: # If the input paths_dict was empty
                item_text = "No suggestions provided by source."

            item = QListWidgetItem(item_text)
            item.setForeground(QColor(128, 128, 128))
            item.setTextAlignment(Qt.AlignCenter)
            self.paths_table.addItem(item)
            self.paths_table.setEnabled(False)
            # if hasattr(self, 'status_label'): # Check if status_label exists (it might not if game_name was provided initially)
            #     self.status_label.setText(item_text) # Replaced
            if hasattr(self, 'progress_dialog_status') and self.progress_dialog_status:
                self.progress_dialog_status.set_message(item_text)
                # self.progress_dialog_status.close() # Or hide, if it's no longer needed
        else:
            for data in all_items_for_table:
                item = QListWidgetItem()
                # Using setToolTip to show the original template for clarity
                item.setToolTip(f"Original template: {data['original_template']}\nResolved path: {data['path']}")
                
                # For HTMLDelegate to work, text must be set via setText.
                # If HTMLDelegate is not used, <b> tags won't render.
                # Assuming HTMLDelegate is active as per previous setup.
                item.setText(data["display_text"]) 
                
                item_is_directly_usable = data.get("exists", False) and \
                                          not data.get("is_placeholder") and \
                                          not data.get("is_pattern_no_match") and \
                                          not data.get("is_pattern_error") and \
                                          not data.get("is_pattern_base_missing")

                if item_is_directly_usable:
                    item.setForeground(QColor("#c9deff")) 
                    item.setIcon(QIcon.fromTheme("dialog-ok") or QIcon()) 
                    has_directly_usable_paths = True
                elif data.get("is_placeholder"):
                    item.setForeground(QColor("orange")) 
                elif data.get("is_pattern_no_match") or data.get("is_pattern_error") or data.get("is_pattern_base_missing"):
                    item.setForeground(QColor("red")) 
                elif data.get("exists") is False and os.path.exists(os.path.dirname(data["path"])): # Parent exists
                    item.setForeground(QColor("darkgray")) # Exists: False, but parent_exists = True
                else: 
                    item.setForeground(QColor("gray")) 
                
                item.setData(Qt.UserRole, data)
                self.paths_table.addItem(item)

            current_status_text = ""
            if has_directly_usable_paths:
                current_status_text = f"Found {len(all_items_for_table)} suggestions. Double-click a usable path."
                self.paths_table.setEnabled(True)
            elif all_items_for_table:
                 current_status_text = "Suggestions found, may require manual setup or resolution."
                 self.paths_table.setEnabled(True) 
            else: # Should be caught by the first if not all_items_for_table
                 current_status_text = "No save locations found."
                 self.paths_table.setEnabled(False)
            
            # if hasattr(self, 'status_label'):
            #     self.status_label.setText(current_status_text) # Replaced
            if hasattr(self, 'progress_dialog_status') and self.progress_dialog_status:
                self.progress_dialog_status.set_message(current_status_text)
                # If paths are found, maybe hide/close the progress dialog or update its state
                if has_directly_usable_paths or all_items_for_table:
                    # self.progress_dialog_status.close() # Example: close it
                    pass # Keep it visible with the new message for now
                else:
                    # self.progress_dialog_status.close() # No paths, close it
                    pass # Keep it visible

            elif not self.game_name: # If no game_name initially, status_label should exist
                 # This case should ideally not be hit if status_label is always created when game_name_input is.
                 print("Warning: progress_dialog_status not found where expected.")


        # Enable proceed button if game name is known, regardless of path usability
        current_game_name = ""
        if self.game_name: # Prioritize self.game_name
            current_game_name = self.game_name
        elif hasattr(self, 'game_name_input_search') and self.game_name_input_search.text().strip():
            current_game_name = self.game_name_input_search.text().strip()
        elif hasattr(self, 'game_name_input_edit') and self.game_name_input_edit.text().strip(): # Check edit field too
            current_game_name = self.game_name_input_edit.text().strip()


        if current_game_name:
            self.proceed_button.setEnabled(True)
            if hasattr(self, 'edit_game_name_button'):
                self.edit_game_name_button.setEnabled(True)
        else:
            self.proceed_button.setEnabled(False)
            if hasattr(self, 'edit_game_name_button'):
                self.edit_game_name_button.setEnabled(False)

    def use_suggested_path(self, item):
        path_data = item.data(Qt.UserRole)
        if not path_data:
            return

        path = path_data["path"]
        
        if path_data.get("exists"): 
            self.selected_paths = [path]
            if path_data.get("is_dir", os.path.isdir(path)): 
                self.directory_option.setChecked(True)
            else:
                self.files_option.setChecked(True)
            self.accept()
        elif path_data.get("is_placeholder") or \
             path_data.get("is_pattern_no_match") or \
             path_data.get("is_pattern_error") or \
             path_data.get("is_pattern_base_missing"):
            QMessageBox.information(self, "Suggestion Type", 
                                    f"This suggestion is a template or pattern and cannot be used directly:\n{path}\n\nOriginal: {path_data.get('original_template', 'N/A')}\n\nPlease use 'Proceed' for manual selection if this path needs interpretation.")
        else: # Path does not exist, not a placeholder/pattern. Try to create if parent exists.
            parent_dir = os.path.dirname(path)
            if os.path.exists(parent_dir):
                msg = QMessageBox(self)
                msg.setWindowTitle("Path Not Found")
                msg.setText(f"The suggested path does not exist:\n{path}")
                msg.setInformativeText(f"Do you want to create this directory?\n\nStore type: {path_data.get('store', 'N/A')}")
                msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
                msg.setDefaultButton(QMessageBox.Yes)
                
                result = msg.exec()
                
                if result == QMessageBox.Yes:
                    try:
                        os.makedirs(path, exist_ok=True) # Create directory
                        self.selected_paths = [path]
                        self.directory_option.setChecked(True) # Assume it's a directory if we created it
                        self.accept()
                    except Exception as e:
                        QMessageBox.critical(self, "Error", f"Failed to create directory: {e}")
                # If No or Cancel, do nothing, user can proceed manually
            else: # Parent also doesn't exist
                QMessageBox.warning(self, "Path Not Available", 
                                    f"The path or its parent directory does not exist:\n{path}\n\nPlease select a different location or define manually.")
    
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
            # Ensure game_name is set if user proceeds this way without prior search
            if not self.game_name and hasattr(self, 'game_name_input_search'):
                self.game_name = self.game_name_input_search.text().strip() 
            elif not self.game_name and hasattr(self, 'game_name_input_edit'):
                 self.game_name = self.game_name_input_edit.text().strip()
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
        accent_color = get_windows_accent_color() if is_windows_11_or_later() else "#0078d4"
        self.drop_indicator.setStyleSheet(f"background-color: {accent_color};")
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
                
                accent_color = get_windows_accent_color() if is_windows_11_or_later() else "#0078d4"
                self.drop_indicator.setStyleSheet(f"background-color: {accent_color};")
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
        self.resize(400, 75)  
        
        self.suggestions = suggestions or []
        self.selected_name = ""
        self.loading = False
        self.progress_dialog = None # Add this line
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
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
            if self.progress_dialog: # Add this block
                self.progress_dialog.accept()
            self.accept()
        else:
            QMessageBox.warning(self, "Missing Title", "Please enter or select a game title.")
    
    def set_loading(self, is_loading):
        """Show/hide the loading indicator"""
        self.loading = is_loading
        if is_loading:
            if not self.progress_dialog: # Add this block
                self.progress_dialog = ProgressDialog(self, "Searching for game name...", cancellable=False)
                self.progress_dialog.set_progress_range(0, 0) # Indeterminate progress bar
            self.progress_dialog.show() # Add this line
            # self.loading_label.setVisible(is_loading) # Remove this line
            # self.suggestions_list.setVisible(not is_loading) # Remove this line
        else: # Add this block
            if self.progress_dialog:
                self.progress_dialog.accept()
                self.progress_dialog = None
        # self.ok_button.setEnabled(not is_loading) # Remove this line
        
        if is_loading:
            self.suggestions_list.clear()
            QApplication.processEvents() 
    
    def closeEvent(self, event):
        """Handle window close events"""
        if self.loading:
            self.selected_name = ""
            if self.progress_dialog: # Add this line
                self.progress_dialog.reject() # Add this line
            self.reject()
        else:
            event.accept()

class HTMLDelegate(QStyledItemDelegate):
    def __init__(self, parent=None): # Added parent argument
        super().__init__(parent) # Call super with parent

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


class Toast(QFrame):
    closed = Signal() # Ensure QObject is imported for Signal
    ICON_SIZE = QSize(18, 18) # Define standard icon size

    def __init__(self, parent, message, icon_type="info", duration=3000):
        super().__init__(parent)
        
        self.setObjectName("ToastClassWindow")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.Tool | 
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self.setFixedWidth(300)

        self.accent_color = get_windows_accent_color() if is_windows_11_or_later() else "#0078D4"
        
        palette = self.parent().palette() if self.parent() else QApplication.palette()
        is_dark_theme = palette.color(QPalette.ColorRole.Window).value() < 128

        if is_dark_theme:
            self.bg_color = QColor("#2D2D2D")
            self.text_color = QColor("#F0F0F0")
            self.border_color = QColor("#4A4A4A")
            self.close_button_color = QColor("#A0A0A0")
            self.close_button_hover_color = QColor("#FFFFFF")
        else:
            self.bg_color = QColor("#F0F0F0")
            self.text_color = QColor("#2D2D2D")
            self.border_color = QColor("#C0C0C0")
            self.close_button_color = QColor("#505050")
            self.close_button_hover_color = QColor("#000000")

        # Icon qcolor is primarily for custom-drawn icons like success
        success_icon_color = QColor("#48C774")

        self.bg_color_str = self.bg_color.name()
        self.text_color_str = self.text_color.name()
        self.border_color_str = self.border_color.name()
        self.close_button_color_str = self.close_button_color.name()
        self.close_button_hover_color_str = self.close_button_hover_color.name()

        self.content_frame = QFrame(self)
        self.content_frame.setObjectName("toastContentFrame")
        self.content_frame.setStyleSheet(f"""
            #toastContentFrame {{
                background-color: {self.bg_color_str};
                border-radius: 6px;
                border: 1px solid {self.border_color_str};
            }}
            QLabel {{
                color: {self.text_color_str};
                background-color: transparent;
                font-size: 9pt;
            }}
            #messageLabel {{
                padding-right: 3px; 
            }}
            #closeButton {{
                background-color: transparent;
                color: {self.close_button_color_str};
                border: none;
                font-size: 12pt;
                font-weight: bold;
                padding: 0px; 
            }}
            #closeButton:hover {{
                color: {self.close_button_hover_color_str};
            }}
            #iconLabel {{
                /* Styling for pixmap container, not text icon */
                /* Removed color, font-size, font-weight */
                /* Padding and min-width are handled by setFixedSize and layout spacing */
                /* text-align: center; (setAlignment is used for pixmap) */
            }}
        """)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0,0,0,0)
        outer_layout.addWidget(self.content_frame)
        self.setLayout(outer_layout)

        content_layout = QHBoxLayout(self.content_frame)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(6)
        content_layout.setAlignment(Qt.AlignVCenter)  # Ensure vertical centering

        icon_pixmap = QPixmap()
        style = QApplication.style()

        if icon_type == "success":
            pixmap = QPixmap(self.ICON_SIZE)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            pen = QPen(success_icon_color)
            pen.setWidth(2) # Adjusted for ICON_SIZE
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setRenderHint(QPainter.Antialiasing)
            
            w, h = self.ICON_SIZE.width(), self.ICON_SIZE.height()
            path = QPainterPath()
            path.moveTo(QPointF(w * 0.20, h * 0.50))
            path.lineTo(QPointF(w * 0.45, h * 0.75))
            path.lineTo(QPointF(w * 0.80, h * 0.25))
            painter.drawPath(path)
            painter.end()
            icon_pixmap = pixmap
        elif icon_type == "warning":
            icon_pixmap = style.standardPixmap(QStyle.StandardPixmap.SP_MessageBoxWarning)
        elif icon_type == "error":
            icon_pixmap = style.standardPixmap(QStyle.StandardPixmap.SP_MessageBoxCritical)
        else:  # "info" or default
            icon_pixmap = style.standardPixmap(QStyle.StandardPixmap.SP_MessageBoxInformation)
        
        icon_label = QLabel()
        icon_label.setObjectName("iconLabel")
        if not icon_pixmap.isNull():
            icon_label.setPixmap(icon_pixmap.scaled(self.ICON_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        icon_label.setFixedSize(self.ICON_SIZE)
        icon_label.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)  # Center pixmap vertically and horizontally

        content_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
        
        message_label = QLabel(message)
        message_label.setObjectName("messageLabel")
        message_label.setWordWrap(True)
        message_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        content_layout.addWidget(message_label, 1)
        
        self.adjustSize() # Adjust height based on content

        self.opacity_animation = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_animation.setDuration(300) # Slightly longer fade
        self.opacity_animation.setStartValue(0.0)
        self.opacity_animation.setEndValue(1.0) # Fade to full opacity
        self.opacity_animation.setEasingCurve(QEasingCurve.InOutCubic) # Smoother easing
        self.opacity_animation.start()
        
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.start_closing)
        if duration > 0:
            self.timer.start(duration)
    
    def close_toast(self):
        self.start_closing()
    
    def start_closing(self):
        self.opacity_animation.setDirection(QPropertyAnimation.Backward)
        self.opacity_animation.finished.connect(self.on_close_animation_finished)
        self.opacity_animation.start()
    
    def on_close_animation_finished(self):
        if self.windowOpacity() == 0:
            self.closed.emit()
            # self.deleteLater() # Let ToastManager handle removal from its list first
            self.close() # Close the widget itself

    def showEvent(self, event):
        # We no longer manually position here, ToastManager handles it.
        super().showEvent(event)
        # Opacity animation starts when shown
        self.opacity_animation.setDirection(QPropertyAnimation.Forward)
        self.opacity_animation.start()


class ToastManager(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.main_window = parent # This should be the main window
        self.toasts = []
        self.spacing = 8 # Reduced spacing
        self.padding_from_edge = 15 # Distance from parent window edges
    
    def show_toast(self, message, icon_type="info", duration=3000):
        # Pass self.parent (main window) as the parent to Toast
        toast = Toast(self.main_window, message, icon_type, duration)
        toast.closed.connect(lambda t=toast: self.remove_toast(t)) # Pass toast instance
        self.toasts.append(toast)
        self._update_positions()
        toast.show()
        return toast
    
    def remove_toast(self, toast):
        if toast in self.toasts:
            self.toasts.remove(toast)
            toast.deleteLater() # Now actually delete the toast widget
            self._update_positions()
    
    def _update_positions(self):
        if not self.main_window or not self.toasts:
            return

        parent_rect = self.main_window.frameGeometry()
        
        # Get the screen the main window is on
        window_handle = self.main_window.windowHandle()
        screen = window_handle.screen() if window_handle and self.main_window.isVisible() else QApplication.primaryScreen()
        # Fallback to primaryScreen if windowHandle is not valid (e.g. window not shown yet)
        # or if main_window is not visible, its screen might be None.
        if screen is None:
            screen = QApplication.primaryScreen()
            
        screen_geometry = screen.availableGeometry()
        
        # Start position for the top of the *lowest* (newest) toast
        current_toast_top_y = parent_rect.bottom() - self.spacing
        
        for toast in reversed(self.toasts): # Newest (bottom) to oldest (top)
            toast_height = toast.height()
            toast_width = toast.width()
            
            # Adjust current_toast_top_y to be the top of *this* toast
            current_toast_top_y -= toast_height
            
            # Calculate X position (left edge of toast)
            x = parent_rect.right() - toast_width - self.spacing
            
            # Clamp to screen edges
            # Ensure toast's top-left (final_x, final_y) keeps the toast within screen bounds
            final_x = max(screen_geometry.left(), min(x, screen_geometry.right() - toast_width))
            final_y = max(screen_geometry.top(), min(current_toast_top_y, screen_geometry.bottom() - toast_height))

            toast.move(final_x, final_y)
            
            # Prepare y for the next toast above this one
            current_toast_top_y -= self.spacing


class ProgressDialog(LoadingDialog):
    def __init__(self, parent=None, message="Operation in progress...", cancellable=False, indeterminate=False): # Added indeterminate
        super().__init__(parent, message)
        self.setFixedSize(500, 180)
        
        layout = self.layout()
        
        self.progress_bar = QProgressBar()
        if indeterminate:
            self.progress_bar.setRange(0, 0) # For indeterminate progress
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)

        # Correct theme detection and color application
        palette = QApplication.palette() # Use QApplication.palette() for global theme
        # Check the base color of the window background for a more reliable dark/light mode detection
        # A common heuristic: if the luminance of the base background color is low, it's likely a dark theme.
        # QColor.value() returns the HSV value, which is related to brightness.
        # Alternatively, check against a known dark color like QColor(Qt.black) or a light one like QColor(Qt.white)
        # For simplicity, let's assume if the window background is darker than a threshold, it's dark mode.
        # A more robust method might involve checking specific style hints or environment variables if available.
        
        # A simple check: if the average of R, G, B components is less than 128, assume dark theme.
        window_bg_color = palette.color(QPalette.ColorRole.Window)
        is_dark_theme = (window_bg_color.red() + window_bg_color.green() + window_bg_color.blue()) / 3 < 128


        if is_dark_theme:
            progress_bar_bg_color = "#222222" # Dark background
            progress_bar_chunk_color = get_windows_accent_color() if is_windows_11_or_later() else "#0078D4" # Accent color for chunk
            progress_bar_border_color = "#555555" # Dark border
            progress_bar_text_color = "#E0E0E0" # Light text
            cancel_button_bg_color = "#333333"
            cancel_button_text_color = "white"
            cancel_button_border_color = "#555555"
            cancel_button_hover_bg_color = "#444444"
            cancel_button_pressed_bg_color = "#222222"
        else: # Light Mode
            progress_bar_bg_color = "#F0F0F0"  # Light gray background
            progress_bar_chunk_color = get_windows_accent_color() if is_windows_11_or_later() else "#0053A0" # Darker blue for light mode chunk
            progress_bar_border_color = "#B0B0B0" # Medium gray border
            progress_bar_text_color = "#202020" # Dark text
            cancel_button_bg_color = "#E0E0E0"
            cancel_button_text_color = "black"
            cancel_button_border_color = "#B0B0B0"
            cancel_button_hover_bg_color = "#D0D0D0"
            cancel_button_pressed_bg_color = "#C0C0C0"

        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {progress_bar_border_color};
                border-radius: 3px;
                text-align: center;
                background-color: {progress_bar_bg_color};
                color: {progress_bar_text_color}; /* Added text color */
                min-height: 20px;
            }}
            
            QProgressBar::chunk {{
                background-color: {progress_bar_chunk_color};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self.progress_bar)
        
        if cancellable:
            button_layout = QHBoxLayout()
            cancel_button = QPushButton("Cancel")
            cancel_button.clicked.connect(self.reject)
            cancel_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {cancel_button_bg_color};
                    color: {cancel_button_text_color};
                    border: 1px solid {cancel_button_border_color};
                    border-radius: 3px;
                    padding: 5px;
                    min-width: 80px;
                }}
                QPushButton:hover {{
                    background-color: {cancel_button_hover_bg_color};
                }}
                QPushButton:pressed {{
                    background-color: {cancel_button_pressed_bg_color};
                }}
            """)
            button_layout.addStretch()
            button_layout.addWidget(cancel_button)
            button_layout.addStretch()
            layout.addLayout(button_layout)
    
    def set_progress(self, value):
        self.progress_bar.setValue(value)
    
    def set_progress_range(self, min_value, max_value):
        self.progress_bar.setRange(min_value, max_value)
