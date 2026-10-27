"""Light enterprise theme: dark navy sidebar, slate content area, white cards."""

ACCENT = "#2563EB"


def apply_light_theme(app) -> None:
    """Always use the light look, also when Windows is in dark mode.

    Without this, Qt follows the Windows dark mode for everything the style sheet does not
    paint itself (dialogs, lists, tables), which gives dark text on a dark background.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPalette

    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):
        hints.setColorScheme(Qt.ColorScheme.Light)
    pal = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#F1F5F9",
        QPalette.ColorRole.WindowText: "#0F172A",
        QPalette.ColorRole.Base: "#FFFFFF",
        QPalette.ColorRole.AlternateBase: "#F8FAFC",
        QPalette.ColorRole.Text: "#0F172A",
        QPalette.ColorRole.PlaceholderText: "#94A3B8",
        QPalette.ColorRole.Button: "#FFFFFF",
        QPalette.ColorRole.ButtonText: "#1E293B",
        QPalette.ColorRole.BrightText: "#FFFFFF",
        QPalette.ColorRole.Highlight: "#2563EB",
        QPalette.ColorRole.HighlightedText: "#FFFFFF",
        QPalette.ColorRole.ToolTipBase: "#0F172A",
        QPalette.ColorRole.ToolTipText: "#F8FAFC",
        QPalette.ColorRole.Link: "#2563EB",
        QPalette.ColorRole.Light: "#FFFFFF",
        QPalette.ColorRole.Midlight: "#E2E8F0",
        QPalette.ColorRole.Mid: "#CBD5E1",
        QPalette.ColorRole.Dark: "#94A3B8",
        QPalette.ColorRole.Shadow: "#64748B",
    }
    for role, color in colors.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor("#94A3B8"))
    app.setPalette(pal)

QSS = """
QWidget { color: #0F172A; }
QDialog, QMessageBox, QWizard, QWizardPage, QInputDialog { background: #FFFFFF; }
QListWidget, QListView, QTreeView, QTableWidget { background: #FFFFFF; color: #0F172A;
                                                  selection-background-color: #DBEAFE; selection-color: #0F172A; }
QMenu { background: #FFFFFF; color: #0F172A; border: 1px solid #E2E8F0; }
QMenu::item:selected { background: #EFF6FF; color: #0F172A; }
QMainWindow, QWidget#Content, QStackedWidget#MainStack { background: #F1F5F9; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }

/* ---------------------------------------------------------------- sidebar */
QFrame#Sidebar { background: #0F172A; }
QFrame#Logo { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3B82F6, stop:1 #6366F1); border-radius: 10px; }
QLabel#AppTitle { color: #F8FAFC; font-size: 12pt; font-weight: 700; }
QLabel#AppSubtitle { color: #94A3B8; font-size: 8.5pt; }
QListWidget#Nav { background: transparent; border: none; outline: 0; color: #CBD5E1; }
QListWidget#Nav::item { padding: 9px 10px; margin: 1px 12px; border-radius: 8px; }
QListWidget#Nav::item:hover:!selected { background: #1E293B; color: #F8FAFC; }
QListWidget#Nav::item:selected { background: #2563EB; color: #FFFFFF; font-weight: 600; }
QLabel#SideFooter { color: #64748B; font-size: 8.5pt; }
QLabel#ModeMock { background: #422006; color: #FBBF24; border-radius: 10px; padding: 4px 10px; font-weight: 700; font-size: 8.5pt; }
QPushButton#CompanyButton { background: #1E293B; color: #E2E8F0; border: 1px solid #334155; border-radius: 8px;
                            padding: 7px 10px; text-align: left; font-weight: 600; }
QPushButton#CompanyButton:hover { background: #273449; border-color: #475569; }
QPushButton#CompanyButton:pressed { background: #334155; }
QMenu#CompanyMenu { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 4px; }
QMenu#CompanyMenu::item { padding: 7px 26px 7px 26px; border-radius: 6px; color: #0F172A; }
QMenu#CompanyMenu::item:selected { background: #EFF6FF; }
QMenu#CompanyMenu::item:disabled { color: #64748B; }
QMenu#CompanyMenu::separator { height: 1px; background: #E2E8F0; margin: 4px 6px; }
QLabel#ModeLive { background: #052E16; color: #4ADE80; border-radius: 10px; padding: 4px 10px; font-weight: 700; font-size: 8.5pt; }

/* ------------------------------------------------------------------ cards */
QFrame#Card { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 14px; }
QLabel#PageTitle { font-size: 18pt; font-weight: 700; color: #0F172A; }
QLabel#PageSubtitle { color: #64748B; }
QLabel#CardTitle { font-size: 11pt; font-weight: 700; color: #0F172A; }
QLabel#FieldLabel { color: #475569; font-size: 9pt; font-weight: 600; }
QLabel#Muted { color: #64748B; }
QLabel#Chip { background: #EFF6FF; color: #1D4ED8; border-radius: 10px; padding: 3px 10px; font-weight: 600; font-size: 9pt; }
QLabel#ChipGray { background: #F1F5F9; color: #475569; border-radius: 10px; padding: 3px 10px; font-size: 9pt; }
QLabel#Mono { font-family: Consolas, 'Courier New', monospace; color: #334155; background: #F8FAFC;
              border: 1px solid #E2E8F0; border-radius: 8px; padding: 7px 9px; }
QFrame#PreviewStage { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #E2E8F0, stop:1 #CBD5E1); border-radius: 12px; }
QLabel#EmptyTitle { color: #334155; font-size: 11pt; font-weight: 600; }
QFrame#PrinterBox { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px; }

/* ---------------------------------------------------------------- buttons */
QPushButton { background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 8px; padding: 7px 16px; color: #1E293B; }
QPushButton:hover { background: #F8FAFC; border-color: #94A3B8; }
QPushButton:pressed { background: #F1F5F9; }
QPushButton:disabled { color: #94A3B8; background: #F1F5F9; border-color: #E2E8F0; }
QPushButton#Primary { background: #2563EB; color: #FFFFFF; border: none; font-weight: 600; padding: 8px 20px; }
QPushButton#Primary:hover { background: #1D4ED8; }
QPushButton#Primary:pressed { background: #1E40AF; }
QPushButton#Primary:disabled { background: #BFDBFE; color: #EFF6FF; }
QPushButton#PrintButton { background: #2563EB; color: #FFFFFF; border: none; font-weight: 700; font-size: 11pt;
                          border-radius: 10px; padding: 12px 20px; }
QPushButton#PrintButton:hover { background: #1D4ED8; }
QPushButton#PrintButton:disabled { background: #BFDBFE; color: #EFF6FF; }
QPushButton#Ghost { background: transparent; border: none; color: #475569; padding: 6px 10px; }
QPushButton#Ghost:hover { background: #F1F5F9; color: #0F172A; }
QPushButton#Ghost:disabled { color: #CBD5E1; }
QPushButton#Stepper { padding: 0; min-width: 36px; max-width: 36px; min-height: 34px; border-radius: 8px; }

/* ----------------------------------------------------------------- inputs */
QLineEdit, QComboBox, QPlainTextEdit {
    border: 1px solid #CBD5E1; border-radius: 8px; padding: 6px 10px; background: #FFFFFF; min-height: 20px;
    selection-background-color: #BFDBFE; selection-color: #0F172A;
}
QLineEdit:hover, QComboBox:hover { border-color: #94A3B8; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border: 1px solid #2563EB; }
QLineEdit:disabled, QComboBox:disabled { background: #F1F5F9; color: #94A3B8; border-color: #E2E8F0; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { border: 1px solid #CBD5E1; border-radius: 6px; padding: 4px; outline: 0;
                              selection-background-color: #EFF6FF; selection-color: #0F172A; }
QSpinBox, QDateEdit { min-height: 26px; }
QSpinBox#Copies { font-size: 11pt; font-weight: 600; }

/* ------------------------------------------------------------------ table */
QTableView { border: 1px solid #E2E8F0; border-radius: 10px; background: #FFFFFF; gridline-color: transparent;
             alternate-background-color: #F8FAFC; selection-background-color: #DBEAFE; selection-color: #0F172A; outline: 0; }
QTableView::item { padding: 0 8px; border: none; }
QTableView::item:selected { background: #DBEAFE; color: #0F172A; }
QHeaderView::section { background: #F8FAFC; color: #475569; font-weight: 600; padding: 8px; border: none;
                       border-bottom: 1px solid #E2E8F0; }

/* ------------------------------------------------------------- scrollbars */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #CBD5E1; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #94A3B8; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #CBD5E1; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* --------------------------------------------------------------- calendar */
QCalendarWidget#NiceCalendar { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; }
#NiceCalendar QWidget#qt_calendar_navigationbar { background: #FFFFFF; border-bottom: 1px solid #E2E8F0;
                                                   min-height: 40px; padding: 2px 6px; }
#NiceCalendar QToolButton { color: #0F172A; background: transparent; border: none; border-radius: 6px;
                            padding: 4px 8px; font-weight: 600; }
#NiceCalendar QToolButton:hover { background: #F1F5F9; }
#NiceCalendar QToolButton::menu-indicator { image: none; width: 0; }
#NiceCalendar QSpinBox { border: 1px solid #CBD5E1; border-radius: 6px; padding: 2px 6px; min-height: 22px; }
#NiceCalendar QMenu { background: #FFFFFF; border: 1px solid #E2E8F0; }
#NiceCalendar QMenu::item { padding: 5px 18px; }
#NiceCalendar QMenu::item:selected { background: #EFF6FF; color: #0F172A; }
#NiceCalendar QTableView { border: none; background: #FFFFFF; alternate-background-color: #FFFFFF; outline: 0;
                           selection-background-color: #2563EB; selection-color: #FFFFFF; }
#NiceCalendar QTableView::item { padding: 0; margin: 2px; border-radius: 8px; }
#NiceCalendar QTableView::item:hover { background: #EFF6FF; }
#NiceCalendar QTableView::item:selected { background: #2563EB; color: #FFFFFF; }
#NiceCalendar QAbstractItemView:disabled { color: #CBD5E1; }

QCheckBox { spacing: 8px; }
QToolTip { background: #0F172A; color: #F8FAFC; border: none; padding: 6px 8px; }
"""

BANNER_STYLES = {
    "info": "background:#EFF6FF; color:#1E40AF; border:1px solid #BFDBFE;",
    "success": "background:#ECFDF5; color:#065F46; border:1px solid #A7F3D0;",
    "warning": "background:#FFFBEB; color:#92400E; border:1px solid #FDE68A;",
    "error": "background:#FEF2F2; color:#991B1B; border:1px solid #FECACA;",
}

STATUS_COLORS = {
    "SpoolerAccepted": "#047857",
    "SubmittedToDevice": "#047857",
    "ConfirmedPrinted": "#047857",
    "Failed": "#B91C1C",
    "UnknownDelivery": "#B45309",
    "Cancelled": "#64748B",
    "Pending": "#1D4ED8",
    "Submitting": "#1D4ED8",
}
