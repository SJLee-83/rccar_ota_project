from PySide6.QtWidgets import (QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QProgressBar, QTextEdit,
                               QGroupBox, QGridLayout, QPlainTextEdit, QFrame,
                               QSizePolicy, QApplication)
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
from PySide6.QtCore import Qt, QTimer, QTime
from PySide6.QtGui import QFont

from auto_theme import STYLESHEET, SpeedometerWidget, btn_dpad_style, btn_action_style


def _sep(vertical=True):
    """Thin separator line."""
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine if vertical else QFrame.Shape.HLine)
    f.setStyleSheet("color: #182535;")
    return f


def _info_card(title: str, value_widget: QWidget, parent=None) -> QWidget:
    """A dark card with a title label above a value widget."""
    card = QWidget(parent)
    card.setStyleSheet("""
        QWidget { background: #0C0E1A; border: 1px solid #182535; border-radius: 8px; }
        QLabel  { background: transparent; border: none; }
    """)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 10, 14, 12)
    lay.setSpacing(4)
    t = QLabel(title)
    t.setStyleSheet("font-size: 9px; font-weight: bold; letter-spacing: 2px; color: #3A5570;")
    lay.addWidget(t)
    lay.addWidget(value_widget)
    return card


class Ui_MainWindow(object):
    # ─────────────────────────────────────────────────────────────────────────
    def setupUi(self, MainWindow):
        MainWindow.setWindowTitle("RC Car Infotainment  ·  SDV Platform")
        MainWindow.resize(1280, 720)
        MainWindow.setStyleSheet(STYLESHEET)

        self.tabs = QTabWidget(MainWindow)
        self.tabs.setDocumentMode(True)
        MainWindow.setCentralWidget(self.tabs)

        font = QFont("Segoe UI", 11)
        self.tabs.setFont(font)

        self.dashboard_tab = QWidget()
        self.control_tab   = QWidget()
        self.ota_tab       = QWidget()
        self.llm_tab       = QWidget()

        self.tabs.addTab(self.dashboard_tab, "⬡  DASHBOARD")
        self.tabs.addTab(self.control_tab,   "◈  RC CONTROL")
        self.tabs.addTab(self.ota_tab,       "⬆  OTA UPDATE")
        self.tabs.addTab(self.llm_tab,       "🤖  AI")

        self._setup_dashboard()
        self._setup_control()
        self._setup_ota()
        self._setup_llm()

        # Clock timer
        self._clock_timer = QTimer()
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_clock()

    # ─── Clock ───────────────────────────────────────────────────────────────
    def _tick_clock(self):
        t = QTime.currentTime().toString("HH : mm : ss")
        if hasattr(self, '_clock_label'):
            self._clock_label.setText(t)

    # =========================================================================
    #  DASHBOARD TAB
    # =========================================================================
    def _setup_dashboard(self):
        root = QVBoxLayout(self.dashboard_tab)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top header bar ───────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(48)
        header.setStyleSheet("background:#050710; border-bottom:1px solid #182535;")
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(20, 0, 20, 0)

        logo = QLabel("● RC CAR  INFOTAINMENT")
        logo.setStyleSheet("color:#00C8FF; font-size:13px; font-weight:bold; letter-spacing:3px;")
        self._clock_label = QLabel("--:--:--")
        self._clock_label.setStyleSheet("color:#6090B0; font-size:14px; font-family:'Consolas';")
        self.mqtt_status_label = QLabel("⬤  CONNECTING")
        self.mqtt_status_label.setStyleSheet("color:#FFB800; font-size:11px; font-weight:bold; letter-spacing:1px;")

        hlay.addWidget(logo)
        hlay.addStretch()
        hlay.addWidget(self._clock_label)
        hlay.addSpacing(24)
        hlay.addWidget(self.mqtt_status_label)
        root.addWidget(header)

        # ── Main body ────────────────────────────────────────────────────────
        body = QWidget()
        blay = QHBoxLayout(body)
        blay.setContentsMargins(24, 20, 24, 20)
        blay.setSpacing(20)

        # Left: Speedometer
        left = QWidget()
        llay = QVBoxLayout(left)
        llay.setContentsMargins(0,0,0,0)
        llay.setSpacing(8)

        spd_label = QLabel("VEHICLE SPEED")
        spd_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spd_label.setStyleSheet("font-size:9px; font-weight:bold; letter-spacing:3px; color:#3A5570;")

        self.speedometer = SpeedometerWidget()
        llay.addWidget(spd_label)
        llay.addWidget(self.speedometer, 1)

        # Also keep speed_label for compatibility
        self.speed_label = QLabel("0  km/h")
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.speed_label.setStyleSheet("font-size:11px; color:#3A5570;")
        llay.addWidget(self.speed_label)
        blay.addWidget(left, 3)

        blay.addWidget(_sep(vertical=True))

        # Right: Info cards grid
        right = QWidget()
        rlay = QGridLayout(right)
        rlay.setContentsMargins(0,0,0,0)
        rlay.setSpacing(12)

        # Battery card
        self.battery_label = QLabel("— %")
        self.battery_label.setStyleSheet("font-size:28px; font-weight:bold; color:#00E878;")
        rlay.addWidget(_info_card("⚡  BATTERY", self.battery_label), 0, 0)

        # MQTT card
        self._mqtt_card_val = QLabel("OFFLINE")
        self._mqtt_card_val.setStyleSheet("font-size:20px; font-weight:bold; color:#FFB800;")
        rlay.addWidget(_info_card("◉  MQTT BROKER", self._mqtt_card_val), 0, 1)

        # RC Status card
        self._rc_status_val = QLabel("STANDBY")
        self._rc_status_val.setStyleSheet("font-size:20px; font-weight:bold; color:#5A80A0;")
        rlay.addWidget(_info_card("◈  RC CONTROL", self._rc_status_val), 1, 0)

        # OTA card
        self._ota_card_val = QLabel("IDLE")
        self._ota_card_val.setStyleSheet("font-size:20px; font-weight:bold; color:#5A80A0;")
        rlay.addWidget(_info_card("⬆  OTA STATUS", self._ota_card_val), 1, 1)

        # RA6E1 Status card
        self._ra6e1_card_val = QLabel("OFFLINE")
        self._ra6e1_card_val.setStyleSheet("font-size:20px; font-weight:bold; color:#FF4444;")
        rlay.addWidget(_info_card("◉  RA6E1 STATUS", self._ra6e1_card_val), 2, 0)

        # Sensor card
        self.sensor_label = QLabel("Sensors: Normal  |  Voice: Standby")
        self.sensor_label.setStyleSheet("font-size:16px; color:#3A6080;")
        rlay.addWidget(_info_card("◉  SENSOR STATUS", self.sensor_label), 2, 1)

        blay.addWidget(right, 4)
        root.addWidget(body, 1)

    # =========================================================================
    #  RC CONTROL TAB
    # =========================================================================
    def _setup_control(self):
        root = QHBoxLayout(self.control_tab)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(16)

        # ── Left: Command log ────────────────────────────────────────────────
        left_grp = QGroupBox("COMMAND LOG")
        ll = QVBoxLayout(left_grp)
        ll.setContentsMargins(10, 14, 10, 10)
        self.logText = QPlainTextEdit()
        self.logText.setReadOnly(True)
        self.logText.setFont(QFont("Consolas", 10))
        self.logText.setPlaceholderText("Waiting for commands...")
        ll.addWidget(self.logText)
        root.addWidget(left_grp, 3)

        root.addWidget(_sep(vertical=True))

        # ── Center: D-pad ────────────────────────────────────────────────────
        mid = QWidget()
        mid.setFixedWidth(280)
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(12)

        ctrl_lbl = QLabel("DIRECTIONAL CONTROL")
        ctrl_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ctrl_lbl.setStyleSheet("font-size:9px; font-weight:bold; letter-spacing:2px; color:#3A5570;")
        ml.addWidget(ctrl_lbl)
        ml.addSpacing(4)

        dpad_size = 78
        center_size = dpad_size   # 정사각형

        # Row 0 — Forward
        r0 = QHBoxLayout(); r0.setSpacing(4)
        self.goButton = QPushButton("▲\nFWD")
        self.goButton.setFixedSize(dpad_size, dpad_size)
        self.goButton.setStyleSheet(btn_dpad_style(r=10, fs=10))
        r0.addStretch(); r0.addWidget(self.goButton); r0.addStretch()
        ml.addLayout(r0)

        # Row 1 — Left / Mid / Right
        r1 = QHBoxLayout(); r1.setSpacing(4)
        self.leftButton = QPushButton("◀\nLEFT")
        self.midButton  = QPushButton("■\nMID")
        self.rightButton= QPushButton("▶\nRIGHT")
        for btn, sz in [(self.leftButton,dpad_size),(self.midButton,center_size),(self.rightButton,dpad_size)]:
            btn.setFixedSize(sz, dpad_size)
            btn.setStyleSheet(btn_dpad_style(r=10, fs=10))
        r1.addStretch(); r1.addWidget(self.leftButton); r1.addWidget(self.midButton)
        r1.addWidget(self.rightButton); r1.addStretch()
        ml.addLayout(r1)

        # Row 2 — Reverse
        r2 = QHBoxLayout(); r2.setSpacing(4)
        self.backButton = QPushButton("▼\nREV")
        self.backButton.setFixedSize(dpad_size, dpad_size)
        self.backButton.setStyleSheet(btn_dpad_style(r=10, fs=10))
        r2.addStretch(); r2.addWidget(self.backButton); r2.addStretch()
        ml.addLayout(r2)

        ml.addSpacing(16)
        sep2 = _sep(vertical=False)
        ml.addWidget(sep2)
        ml.addSpacing(16)

        # Start / Stop row
        ss_lbl = QLabel("VEHICLE CONTROL")
        ss_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ss_lbl.setStyleSheet("font-size:9px; font-weight:bold; letter-spacing:2px; color:#3A5570;")
        ml.addWidget(ss_lbl)

        r3 = QHBoxLayout(); r3.setSpacing(8)
        self.stopButton  = QPushButton("⬛  STOP")
        self.startButton = QPushButton("▶  START")
        self.stopButton.setMinimumHeight(48)
        self.startButton.setMinimumHeight(48)
        self.stopButton.setStyleSheet(btn_action_style("red"))
        self.startButton.setStyleSheet(btn_action_style("green"))
        r3.addWidget(self.stopButton); r3.addWidget(self.startButton)
        ml.addLayout(r3)
        ml.addStretch()

        root.addWidget(mid, 0)

        root.addWidget(_sep(vertical=True))

        # ── Right: Sensing log ───────────────────────────────────────────────
        right_grp = QGroupBox("SENSOR DATA")
        rl = QVBoxLayout(right_grp)
        rl.setContentsMargins(10, 14, 10, 10)
        self.sensingText = QPlainTextEdit()
        self.sensingText.setReadOnly(True)
        self.sensingText.setFont(QFont("Consolas", 10))
        self.sensingText.setPlaceholderText("Waiting for sensor data...")
        rl.addWidget(self.sensingText)
        root.addWidget(right_grp, 3)

    # =========================================================================
    #  OTA FIRMWARE UPDATE TAB
    # =========================================================================
    def _setup_ota(self):
        root = QHBoxLayout(self.ota_tab)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(16)

        # ── Left column: File + ESP32 test ───────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0,0,0,0)
        ll.setSpacing(12)

        # ESP32 connection test
        esp_grp = QGroupBox("ESP32 & RA6E1 CONNECTION TEST")
        el = QVBoxLayout(esp_grp)
        el.setContentsMargins(10,14,10,10); el.setSpacing(8)

        # ESP32 LED row
        esp_lbl = QLabel("ESP32 LED")
        esp_lbl.setStyleSheet("font-size:9px; font-weight:bold; letter-spacing:2px; color:#3A5570;")
        el.addWidget(esp_lbl)
        led_row = QHBoxLayout(); led_row.setSpacing(8)
        self.btn_led_on  = QPushButton("⬤  LED ON")
        self.btn_led_off = QPushButton("◯  LED OFF")
        self.btn_led_on.setMinimumHeight(38)
        self.btn_led_off.setMinimumHeight(38)
        self.btn_led_on.setStyleSheet(btn_action_style("green"))
        self.btn_led_off.setStyleSheet(btn_action_style("red"))
        led_row.addWidget(self.btn_led_on); led_row.addWidget(self.btn_led_off)
        el.addLayout(led_row)

        # RA6E1 PING row
        ra6e1_lbl = QLabel("RA6E1 BOARD")
        ra6e1_lbl.setStyleSheet("font-size:9px; font-weight:bold; letter-spacing:2px; color:#3A5570; margin-top:4px;")
        el.addWidget(ra6e1_lbl)
        ping_row = QHBoxLayout(); ping_row.setSpacing(8)
        self.btn_ping_ra6e1 = QPushButton("⬤  PING RA6E1")
        self.btn_ping_ra6e1.setMinimumHeight(38)
        self.btn_ping_ra6e1.setStyleSheet(btn_action_style("cyan"))
        self.ra6e1_ping_status = QLabel("—")
        self.ra6e1_ping_status.setStyleSheet(
            "font-size:11px; color:#3A5570; padding:4px 8px;"
            "background:#0C0E1A; border:1px solid #182535; border-radius:6px;")
        self.ra6e1_ping_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ping_row.addWidget(self.btn_ping_ra6e1, 2)
        ping_row.addWidget(self.ra6e1_ping_status, 1)
        el.addLayout(ping_row)
        ll.addWidget(esp_grp)

        # Firmware file selection
        file_grp = QGroupBox("FIRMWARE BINARY")
        fl = QVBoxLayout(file_grp)
        fl.setContentsMargins(10,14,10,12); fl.setSpacing(8)

        self.btn_select_bin = QPushButton("📂  SELECT  .BIN  FILE")
        self.btn_select_bin.setMinimumHeight(46)
        self.btn_select_bin.setStyleSheet(btn_action_style("cyan"))
        fl.addWidget(self.btn_select_bin)

        self.selected_file_label = QLabel("No file selected")
        self.selected_file_label.setStyleSheet(
            "color:#4A6880; font-size:12px; padding:4px 2px;")
        self.selected_file_label.setWordWrap(True)
        fl.addWidget(self.selected_file_label)

        fl.addWidget(_sep(vertical=False))

        meta_row = QHBoxLayout(); meta_row.setSpacing(0)
        for attr, default in [("file_size_label","SIZE  —"),
                               ("file_crc_label", "CRC32  —"),
                               ("file_chunks_label","CHUNKS  —")]:
            lbl = QLabel(default)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                "font-size:10px; color:#3A5570; letter-spacing:1px;"
                "border-right:1px solid #182535; padding:4px 8px;")
            setattr(self, attr, lbl)
            meta_row.addWidget(lbl, 1)
        self.file_chunks_label.setStyleSheet(
            "font-size:10px; color:#3A5570; letter-spacing:1px; padding:4px 8px;")
        fl.addLayout(meta_row)
        ll.addWidget(file_grp)

        # Version info
        ver_grp = QGroupBox("FIRMWARE VERSION")
        vl = QVBoxLayout(ver_grp)
        vl.setContentsMargins(10,14,10,12); vl.setSpacing(6)
        self.current_version_label = QLabel("INSTALLED   v1.0.0")
        self.current_version_label.setStyleSheet(
            "font-size:13px; color:#4A7090; font-weight:bold;")
        self.latest_version_label  = QLabel("SELECTED    —")
        self.latest_version_label.setStyleSheet(
            "font-size:13px; color:#00C8FF; font-weight:bold;")
        vl.addWidget(self.current_version_label)
        vl.addWidget(self.latest_version_label)
        ll.addWidget(ver_grp)

        ll.addStretch()
        root.addWidget(left, 4)

        root.addWidget(_sep(vertical=True))

        # ── Right column: Progress + Log + Buttons ───────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0,0,0,0)
        rl.setSpacing(12)

        # Transfer progress group
        prog_grp = QGroupBox("TRANSFER PROGRESS")
        pl = QVBoxLayout(prog_grp)
        pl.setContentsMargins(12,14,12,12); pl.setSpacing(10)

        self.ota_status_label = QLabel("Status:  Idle  —  waiting for firmware selection")
        self.ota_status_label.setStyleSheet(
            "font-size:12px; font-weight:bold; color:#5A7090; padding:2px 0;")
        pl.addWidget(self.ota_status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(26)
        pl.addWidget(self.progress_bar)

        stats_row = QHBoxLayout(); stats_row.setSpacing(8)
        self.ota_acked_label = QLabel("ACKED  0 / 0")
        self.ota_retry_label = QLabel("RETRIES  0")
        self.ota_rate_label = QLabel("RATE  0.0 KiB/s")
        self.ota_last_label = QLabel("LAST  —")
        for label in (self.ota_acked_label, self.ota_retry_label,
                      self.ota_rate_label, self.ota_last_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(
                "font-size:10px; color:#6090B0; background:#080C14;"
                "border:1px solid #182535; border-radius:5px; padding:5px;")
            stats_row.addWidget(label, 1)
        pl.addLayout(stats_row)
        rl.addWidget(prog_grp)

        # Chunk-level delivery visualization.  A row turns green only after
        # the RA6E1 has validated and written that exact chunk.
        chunk_grp = QGroupBox("CHUNK DELIVERY")
        cl = QVBoxLayout(chunk_grp)
        cl.setContentsMargins(10,14,10,10)
        self.chunk_table = QTableWidget(0, 6)
        self.chunk_table.setHorizontalHeaderLabels(
            ["ID", "BYTES", "CRC32", "STATE", "RETRY", "RTT ms"])
        self.chunk_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.chunk_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.chunk_table.setAlternatingRowColors(True)
        self.chunk_table.verticalHeader().setVisible(False)
        self.chunk_table.setMinimumHeight(180)
        header = self.chunk_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        cl.addWidget(self.chunk_table)
        rl.addWidget(chunk_grp, 2)

        # Status log
        log_grp = QGroupBox("SYSTEM LOG")
        sl = QVBoxLayout(log_grp)
        sl.setContentsMargins(10,14,10,10)
        self.status_log = QTextEdit()
        self.status_log.setReadOnly(True)
        self.status_log.setFont(QFont("Consolas", 10))
        self.status_log.setStyleSheet("""
            QTextEdit {
                background: #040810;
                color: #A0B8C8;
                border: 1px solid #182535;
                border-radius: 6px;
                padding: 6px;
                font-size: 11px;
            }
        """)
        self.status_log.setHtml(
            '<p style="color:#2A6A4A; font-size:11px; font-family:Consolas;">&gt; System Ready. Waiting for firmware selection...</p>')
        sl.addWidget(self.status_log)
        rl.addWidget(log_grp, 1)

        # Action buttons
        act_row = QHBoxLayout(); act_row.setSpacing(10)
        self.btn_start_ota = QPushButton("⬆  UPLOAD  TO  ESP32")
        self.btn_start_ota.setEnabled(False)
        self.btn_start_ota.setMinimumHeight(52)
        self.btn_start_ota.setStyleSheet(btn_action_style("green"))

        self.btn_abort_ota = QPushButton("✕  ABORT")
        self.btn_abort_ota.setEnabled(False)
        self.btn_abort_ota.setMinimumHeight(52)
        self.btn_abort_ota.setStyleSheet(btn_action_style("red"))

        act_row.addWidget(self.btn_start_ota, 3)
        act_row.addWidget(self.btn_abort_ota, 1)
        rl.addLayout(act_row)

        root.addWidget(right, 5)

    # =========================================================================
    #  AI TAB
    # =========================================================================
    def _setup_llm(self):
        root = QVBoxLayout(self.llm_tab)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        # ── Header bar: endpoint / model info ────────────────────────────────
        cfg_bar = QWidget()
        cfg_bar.setStyleSheet(
            "background:#0C0E1A; border:1px solid #182535; border-radius:8px;")
        cfg_lay = QHBoxLayout(cfg_bar)
        cfg_lay.setContentsMargins(14, 8, 14, 8)

        lbl_ep = QLabel("ENDPOINT")
        lbl_ep.setStyleSheet(
            "font-size:9px; font-weight:bold; letter-spacing:2px; color:#3A5570; border:none;")
        self.llm_endpoint_label = QLabel("https://gms.ssafy.io/gmsapi/api.openai.com/v1")
        self.llm_endpoint_label.setStyleSheet(
            "font-size:12px; color:#00C8FF; font-family:'Consolas'; border:none;")

        lbl_m = QLabel("MODEL")
        lbl_m.setStyleSheet(
            "font-size:9px; font-weight:bold; letter-spacing:2px; color:#3A5570;"
            "border-left:1px solid #182535; padding-left:14px; border-radius:0; border-right:none; border-top:none; border-bottom:none;")
        self.llm_model_label = QLabel("gpt-5.4-mini")
        self.llm_model_label.setStyleSheet(
            "font-size:12px; color:#00E878; font-family:'Consolas'; border:none;")

        self.llm_status_dot = QLabel("⬤  IDLE")
        self.llm_status_dot.setStyleSheet(
            "font-size:11px; font-weight:bold; color:#3A5570; border:none;")

        cfg_lay.addWidget(lbl_ep)
        cfg_lay.addWidget(self.llm_endpoint_label)
        cfg_lay.addSpacing(20)
        cfg_lay.addWidget(lbl_m)
        cfg_lay.addWidget(self.llm_model_label)
        cfg_lay.addStretch()
        cfg_lay.addWidget(self.llm_status_dot)
        root.addWidget(cfg_bar)

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(14)

        # ── Left: chatbot ────────────────────────────────────────────────────
        chat_grp = QGroupBox("GPT-5.5 CHATBOT")
        chat_lay = QVBoxLayout(chat_grp)
        chat_lay.setContentsMargins(10, 14, 10, 10)
        chat_lay.setSpacing(8)

        self.llm_chat_display = QTextEdit()
        self.llm_chat_display.setReadOnly(True)
        self.llm_chat_display.setFont(QFont("Segoe UI", 11))
        self.llm_chat_display.setStyleSheet("""
            QTextEdit {
                background:#040810; color:#C8D8E8;
                border:1px solid #182535; border-radius:8px;
                padding:12px; font-size:12px;
            }
        """)
        self.llm_chat_display.setHtml(
            '<p style="color:#2A4A60; font-size:12px;" font-family=Segoe UI;>'
            '&#9654; AI 탭 준비 완료.<br>'
            '챗봇은 <span style="color:#00E878;">gpt-5.4-mini</span>, '
            '음성 제어는 버튼 녹음 → STT → 명령 해석 → MQTT 전송 순서로 동작합니다.</p>'
        )
        chat_lay.addWidget(self.llm_chat_display, 1)

        self.llm_input = QPlainTextEdit()
        self.llm_input.setFixedHeight(80)
        self.llm_input.setFont(QFont("Segoe UI", 11))
        self.llm_input.setStyleSheet("""
            QPlainTextEdit {
                background:#040810; color:#E0EAF4;
                border:1px solid #182535; border-radius:6px;
                padding:8px; font-size:12px;
            }
            QPlainTextEdit:focus { border:1px solid #00A0C8; }
        """)
        self.llm_input.setPlaceholderText(
            "챗봇에게 물어볼 내용을 입력하세요.")
        chat_lay.addWidget(self.llm_input)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        self.llm_clear_btn = QPushButton("🗑  CLEAR")
        self.llm_clear_btn.setMinimumHeight(42)
        self.llm_clear_btn.setStyleSheet(
            "QPushButton{background:#0C1018;color:#4A6880;border:1px solid #1A2A3C;"
            "border-radius:8px;font-size:12px;font-weight:bold;}"
            "QPushButton:hover{background:#18242E;color:#6090A0;border-color:#2A4050;}")

        self.llm_send_btn = QPushButton("  SEND")
        self.llm_send_btn.setMinimumHeight(42)
        self.llm_send_btn.setStyleSheet(
            "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #005A90,stop:1 #003A6A);color:white;"
            "border:1px solid #0090CC;border-radius:8px;"
            "font-size:13px;font-weight:bold;}"
            "QPushButton:hover{background:#006AA0;}"
            "QPushButton:disabled{background:#0C1018;color:#283840;border-color:#141E28;}")

        btn_row.addWidget(self.llm_clear_btn, 1)
        btn_row.addWidget(self.llm_send_btn, 4)
        chat_lay.addLayout(btn_row)
        body_lay.addWidget(chat_grp, 3)

        body_lay.addWidget(_sep(vertical=True))

        # ── Right: voice command ─────────────────────────────────────────────
        voice_grp = QGroupBox("VOICE CONTROL")
        voice_lay = QVBoxLayout(voice_grp)
        voice_lay.setContentsMargins(10, 14, 10, 10)
        voice_lay.setSpacing(10)

        self.voice_command_status = QLabel("Status:  Standby  —  버튼을 누르면 명령어를 녹음합니다")
        self.voice_command_status.setStyleSheet(
            "font-size:12px; font-weight:bold; color:#5A7090; padding:2px 0;")
        voice_lay.addWidget(self.voice_command_status)

        self.voice_command_button = QPushButton("🎙  RECORD  COMMAND")
        self.voice_command_button.setMinimumHeight(56)
        self.voice_command_button.setStyleSheet(btn_action_style("cyan"))
        voice_lay.addWidget(self.voice_command_button)

        help_label = QLabel(
            "예시: “앞으로 가”, “왼쪽”, “오른쪽”, “멈춰”, “중앙으로”.\n"
            "실행 가능 명령: start · go · back · left · right · mid · stop")
        help_label.setWordWrap(True)
        help_label.setStyleSheet(
            "font-size:11px; color:#6090B0; background:#080C14;"
            "border:1px solid #182535; border-radius:6px; padding:8px;")
        voice_lay.addWidget(help_label)

        self.voice_command_log = QTextEdit()
        self.voice_command_log.setReadOnly(True)
        self.voice_command_log.setFont(QFont("Consolas", 10))
        self.voice_command_log.setStyleSheet("""
            QTextEdit {
                background:#040810; color:#A0B8C8;
                border:1px solid #182535; border-radius:8px;
                padding:10px; font-size:11px;
            }
        """)
        self.voice_command_log.setHtml(
            '<p style="color:#2A4A60;">&gt; Voice control initialized.</p>')
        voice_lay.addWidget(self.voice_command_log, 1)

        safety_label = QLabel(
            "안전 규칙: AI가 해석한 결과라도 화이트리스트 명령만 MQTT로 전송합니다.")
        safety_label.setWordWrap(True)
        safety_label.setStyleSheet("font-size:10px; color:#7A5060;")
        voice_lay.addWidget(safety_label)

        body_lay.addWidget(voice_grp, 2)
        root.addWidget(body, 1)

