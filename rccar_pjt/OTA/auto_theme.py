import math
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont

# ─── Global Automotive Dark Stylesheet ───────────────────────────────────────
STYLESHEET = """
QMainWindow, QDialog { background-color: #08090F; }
QWidget { background-color: #08090F; color: #C8D8E8;
          font-family: 'Segoe UI', Arial, sans-serif; }

QTabWidget::pane { border: none; background-color: #08090F; }
QTabBar { background-color: #0A0C16; }
QTabBar::tab {
    background-color: #0A0C16; color: #3A5570;
    padding: 14px 32px; border: none;
    border-right: 1px solid #141E2C;
    font-size: 11px; font-weight: bold; letter-spacing: 2px;
    min-width: 110px;
}
QTabBar::tab:selected {
    background-color: #08090F; color: #00C8FF;
    border-top: 2px solid #00C8FF;
}
QTabBar::tab:hover:!selected { background-color: #0E1220; color: #5A80A0; }

QGroupBox {
    border: 1px solid #182535; border-radius: 8px;
    margin-top: 14px; padding-top: 4px;
    font-size: 9px; font-weight: bold;
    color: #3A5570; letter-spacing: 2px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 14px; padding: 0 6px;
    background-color: #08090F;
}

QPlainTextEdit, QTextEdit {
    background-color: #040608; color: #00CC88;
    border: 1px solid #182535; border-radius: 6px;
    font-family: 'Consolas', monospace; font-size: 11px; padding: 6px;
    selection-background-color: #003A55;
}
QScrollBar:vertical { background: #040608; width: 5px; }
QScrollBar::handle:vertical { background: #1C3050; border-radius: 2px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #040608; height: 5px; }
QScrollBar::handle:horizontal { background: #1C3050; border-radius: 2px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QProgressBar {
    border: 1px solid #182535; border-radius: 6px;
    background-color: #040608; color: #00C8FF;
    font-weight: bold; font-size: 12px; min-height: 22px; text-align: center;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #004880, stop:0.6 #0090C0, stop:1 #00C8FF);
    border-radius: 5px;
}
QLabel { background: transparent; }
"""

BTN_DPAD = """
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #18273A, stop:1 #0C1822);
    color: #6090B8; border: 1px solid #223448;
    border-radius: {r}px; font-size: {fs}px; font-weight: bold;
}}
QPushButton:hover {{
    background: #1E3050; border: 1px solid #00A0CC; color: #00D4FF;
}}
QPushButton:pressed {{
    background: #0A1C30; border: 1px solid #006080; color: #0090B0;
}}
QPushButton:disabled {{
    background: #0A0E14; border: 1px solid #10181E; color: #202830;
}}
"""

BTN_ACTION = """
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 {c1}, stop:1 {c2});
    color: white; border: 1px solid {bc};
    border-radius: 8px; font-size: 13px; font-weight: bold;
    padding: 4px 16px;
}}
QPushButton:hover {{ background: {ch}; border-color: {bc}; }}
QPushButton:pressed {{ background: {cp}; }}
QPushButton:disabled {{ background: #0C1018; border: 1px solid #141E28; color: #283840; }}
"""

def btn_dpad_style(r=10, fs=18):
    return BTN_DPAD.format(r=r, fs=fs)

def btn_action_style(kind="blue"):
    palettes = {
        "blue":  dict(c1="#005A90",c2="#003A6A",bc="#0090CC",ch="#006AA0",cp="#002A50"),
        "green": dict(c1="#006040",c2="#004028",bc="#00A060",ch="#007050",cp="#003020"),
        "red":   dict(c1="#702020",c2="#501010",bc="#CC3030",ch="#802020",cp="#400808"),
        "cyan":  dict(c1="#004A60",c2="#002A40",bc="#00A0C8",ch="#005A70",cp="#001A2C"),
    }
    p = palettes.get(kind, palettes["blue"])
    return BTN_ACTION.format(**p)


# ─── Custom Speedometer Widget ────────────────────────────────────────────────
class SpeedometerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._max = 200
        self.setMinimumSize(240, 240)
        self.setSizePolicy(
            __import__('PySide6.QtWidgets', fromlist=['QSizePolicy']).QSizePolicy.Policy.Expanding,
            __import__('PySide6.QtWidgets', fromlist=['QSizePolicy']).QSizePolicy.Policy.Expanding,
        )

    def setValue(self, value):
        self._value = max(0, min(int(value), self._max))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        sz = min(w, h) - 16
        rx, ry = (w - sz) / 2, (h - sz) / 2
        rect = QRectF(rx, ry, sz, sz)
        cx, cy = rect.center().x(), rect.center().y()
        radius = sz / 2

        # Outer glow ring
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#0A0E18")))
        p.drawEllipse(rect)
        pen = QPen(QColor("#101C2C"), 2)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect.adjusted(2,2,-2,-2))

        arc_rect = rect.adjusted(18, 18, -18, -18)
        START = 225 * 16
        SPAN  = -270 * 16

        # Track arc (background)
        p.setPen(QPen(QColor("#182535"), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(arc_rect, START, SPAN)

        # Progress arc
        ratio = self._value / self._max
        if ratio < 0.6:   arc_color = QColor("#00C8FF")
        elif ratio < 0.8: arc_color = QColor("#FFB800")
        else:             arc_color = QColor("#FF4444")
        if ratio > 0:
            p.setPen(QPen(arc_color, 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(arc_rect, START, int(SPAN * ratio))

        # Tick marks + labels
        for i in range(11):
            angle_deg = 225 - 27 * i
            angle_rad = math.radians(angle_deg)
            is_major = (i % 2 == 0)
            r_out = radius - 20
            r_in  = radius - (32 if is_major else 28)
            x1 = cx + r_out * math.cos(angle_rad)
            y1 = cy - r_out * math.sin(angle_rad)
            x2 = cx + r_in  * math.cos(angle_rad)
            y2 = cy - r_in  * math.sin(angle_rad)
            tick_c = QColor("#2A4060") if is_major else QColor("#1A2C40")
            p.setPen(QPen(tick_c, 2 if is_major else 1))
            p.drawLine(QPointF(x1,y1), QPointF(x2,y2))
            if is_major:
                lr = radius - 46
                lx = cx + lr * math.cos(angle_rad)
                ly = cy - lr * math.sin(angle_rad)
                p.setPen(QPen(QColor("#3A5570")))
                p.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
                p.drawText(QRectF(lx-14, ly-8, 28, 16),
                           Qt.AlignmentFlag.AlignCenter, str(i*20))

        # Needle
        na = math.radians(225 - 270 * ratio)
        nl = radius - 32
        nx, ny = cx + nl*math.cos(na), cy - nl*math.sin(na)
        p.setPen(QPen(QColor("#FF5020"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx, cy), QPointF(nx, ny))

        # Hub
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#FF5020"))); p.drawEllipse(QPointF(cx,cy), 7, 7)
        p.setBrush(QBrush(QColor("#CC3010"))); p.drawEllipse(QPointF(cx,cy), 4, 4)

        # Digital speed — proportional to sz so it never clips
        spd_fs = max(14, int(sz * 0.11))
        p.setPen(QPen(QColor("#FFFFFF")))
        p.setFont(QFont("Segoe UI", spd_fs, QFont.Weight.Bold))
        spd_h = spd_fs * 2 + 4
        spd_rect = QRectF(cx - sz * 0.24, cy + sz * 0.04, sz * 0.48, spd_h)
        p.drawText(spd_rect, Qt.AlignmentFlag.AlignCenter, str(self._value))

        unit_fs = max(8, int(sz * 0.042))
        p.setPen(QPen(QColor("#3A6080")))
        p.setFont(QFont("Segoe UI", unit_fs))
        unit_y = spd_rect.bottom() + 4
        unit_rect = QRectF(cx - sz * 0.18, unit_y, sz * 0.36, unit_fs * 2 + 4)
        p.drawText(unit_rect, Qt.AlignmentFlag.AlignCenter, "km/h")
