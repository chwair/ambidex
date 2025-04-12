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
    QPixmap, QIcon, QDrag, QPainter, QColor, QCursor
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
        self.resize(600, 400)
        
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
        
        self.option_group = QButtonGroup(self)
        self.files_option = QRadioButton("Select save files")
        self.directory_option = QRadioButton("Define save directory")
        self.option_group.addButton(self.files_option)
        self.option_group.addButton(self.directory_option)
        
        self.files_option.setChecked(True)
        
        options_layout = QVBoxLayout()
        options_layout.addWidget(self.files_option)
        options_layout.addWidget(self.directory_option)
        layout.addLayout(options_layout)
        
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
        self.resize(400, 300)
        
        self.suggestions = suggestions or []
        self.selected_name = ""
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter the game's title")
        form.addRow("Game Title:", self.name_input)
        layout.addLayout(form)
        
        if self.suggestions:
            layout.addWidget(QLabel("Or select from these suggestions:"))
            
            self.suggestions_list = QListWidget()
            for suggestion in self.suggestions:
                self.suggestions_list.addItem(suggestion)
            self.suggestions_list.itemClicked.connect(self.on_suggestion_clicked)
            layout.addWidget(self.suggestions_list)
        else:
            layout.addWidget(QLabel("No suggestions found based on file paths."))
        
        buttons_layout = QHBoxLayout()
        
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept_name)
        buttons_layout.addWidget(ok_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)
        
        layout.addLayout(buttons_layout)
    
    def on_suggestion_clicked(self, item):
        self.name_input.setText(item.text())
    
    def accept_name(self):
        self.selected_name = self.name_input.text()
        if self.selected_name:
            self.accept()
        else:
            QMessageBox.warning(self, "Missing Title", "Please enter or select a game title.")


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
