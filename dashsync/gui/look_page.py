"""Look page: how the car screen looks for this vehicle. Two tabs over one profile and one Sync to card:
the pictures and title (vehicle_page) and the colours and pages (interface_page)."""
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .interface_page import InterfacePage
from .syncbar import look_syncbar
from .vehicle_page import VehiclePage


class LookPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.syncbar = look_syncbar(state)
        tabs = QTabWidget()
        tabs.addTab(VehiclePage(state, self.syncbar), "Title and pictures")
        tabs.addTab(InterfacePage(state, self.syncbar), "Colours and pages")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(tabs, 1)
        lay.addWidget(self.syncbar)
