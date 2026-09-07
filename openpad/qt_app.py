from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from openpad.domain import ControllerSnapshot, DriverResult, InputSnapshot
from openpad.drivers.base import ControllerDriver
from openpad.i18n import load_qt_catalogs
from openpad.services.history import BatteryHistory
from openpad.services.lighting import (
    LIGHTING_PROFILES,
    LightingSafetyState,
    create_checkpoint,
    get_profile,
    latest_private_checkpoint,
    load_safety_state,
    save_safety_state,
)
from openpad.services.settings import AppSettings, SettingsStore


TRANSLATIONS = {
    "es": {
        "home": "Resumen", "inputs": "Entradas", "battery": "Batería", "device": "Dispositivo", "profiles": "Perfiles",
        "settings": "Ajustes", "diagnostics": "Diagnóstico", "connected": "Conectado",
        "disconnected": "Desconectado", "charging": "Cargando", "not_charging": "Sin cargar",
        "full": "Carga completa", "unknown": "Estado desconocido", "power_only": "Recibiendo energía por USB",
        "battery_unavailable": "Batería no disponible", "last_update": "Última actualización",
        "connection": "Conexión", "firmware": "Firmware", "quick_actions": "Accesos rápidos",
        "refresh": "Actualizar", "open_inputs": "Probar entradas", "view_history": "Ver historial",
        "live_controller": "Mando en tiempo real", "left_stick": "Stick izquierdo",
        "right_stick": "Stick derecho", "triggers": "Gatillos", "buttons": "Botones",
        "input_note": "Lectura estándar de Linux. Las escrituras al mando permanecen deshabilitadas.",
        "battery_history": "Historial de batería", "last_24h": "24 horas", "last_7d": "7 días",
        "last_30d": "30 días", "history_empty": "El historial aparecerá después de recibir lecturas de batería.",
        "device_info": "Información del dispositivo", "model": "Modelo", "vendor_id": "ID del fabricante",
        "product_id": "ID del producto", "data_source": "Fuente de datos", "capabilities": "Capacidades verificadas",
        "read_only": "Solo lectura", "safe_control": "Control seguro", "supported": "Compatible", "not_verified": "Aún no verificado",
        "appearance": "Apariencia y acceso", "language": "Idioma", "reduced_motion": "Reducir movimiento",
        "history_enabled": "Guardar historial local", "notifications": "Notificaciones de batería",
        "privacy_note": "Todo permanece en este equipo. OpenPad Hub no usa cuentas, nube ni telemetría.",
        "system_check": "Comprobación del sistema", "repair_permissions": "Reparar permisos",
        "permission_help": "El mando está conectado, pero Linux no permite leer su canal HID.",
        "unofficial": "Proyecto comunitario no oficial", "safe_mode": "Modo seguro · sin escrituras",
        "signal": "Señal", "no_signal": "No disponible", "quit": "Salir", "open": "Abrir OpenPad Hub",
        "global_controller": "Controlador general", "live_inputs": "Lectura en vivo", "sticks": "Sticks",
        "input_unavailable": "Entradas no disponibles", "input_mode_help": "Usa 2.4 GHz / XInput para leer sticks y botones.",
        "auto_detected": "Detectados automáticamente", "lighting": "Iluminación", "live_lighting": "Iluminación en vivo",
        "rgb_profile": "Efecto activo", "rgb_zones": "Zonas del mando", "rgb_live_note": "En #0, OpenPad reordena la telemetría como Izquierda, Derecha, Logo y Centro. Los modos animados permanecen en lectura.",
        "safety_checks": "Comprobaciones de seguridad", "checkpoint": "Checkpoint privado", "readback": "Lectura de configuración", "recovery": "Recuperación", "ready": "Listo", "locked": "Pendiente", "create_checkpoint": "Crear checkpoint", "original_profiles": "Perfiles OpenPad", "preview_only": "Vista previa", "apply_profile": "Aplicar al mando", "reserved_slot": "Reserva una configuración física para OpenPad antes de habilitar escrituras.",
        "static_effect": "Estático confirmado · cuatro zonas estables", "animated_effect": "Animación detectada · alterna izquierda/derecha", "spectrum_effect": "Animación detectada · recorre todas las zonas", "effect_unverified": "Efecto sin verificar", "lighting_firmware_lock": "El modo estático ya está identificado. Aplicar seguirá bloqueado hasta completar una prueba de cambio y recuperación con lectura posterior.", "lighting_ready": "Cambio, lectura posterior y recuperación verificados. Los perfiles se aplican solo en modo estático #0.", "applying": "Aplicando…",
        "profile_collection": "Colección de perfiles", "active_profile": "Perfil activo", "active": "Activo", "selected": "Seleccionado", "verified": "Verificado", "change_verified": "Aplicado y verificado con 3 lecturas", "change_failed": "Cambio rechazado", "static_required": "Selecciona el efecto estático #0 con M + stick izquierdo antes de aplicar", "effect_modes": "Efectos del mando", "effect_read_only": "Detectado · solo lectura", "physical_shortcut": "Cambia con M + stick izquierdo", "zone_left": "Izquierda", "zone_right": "Derecha", "zone_logo": "Logo", "zone_center": "Centro", "local_verified": "LOCAL · VERIFICADO",
    },
    "en": {
        "home": "Overview", "inputs": "Inputs", "battery": "Battery", "device": "Device", "profiles": "Profiles",
        "settings": "Settings", "diagnostics": "Diagnostics", "connected": "Connected",
        "disconnected": "Disconnected", "charging": "Charging", "not_charging": "Not charging",
        "full": "Fully charged", "unknown": "Unknown state", "power_only": "Receiving USB power",
        "battery_unavailable": "Battery unavailable", "last_update": "Last update",
        "connection": "Connection", "firmware": "Firmware", "quick_actions": "Quick actions",
        "refresh": "Refresh", "open_inputs": "Test inputs", "view_history": "View history",
        "live_controller": "Live controller", "left_stick": "Left stick", "right_stick": "Right stick",
        "triggers": "Triggers", "buttons": "Buttons",
        "input_note": "Standard Linux input. Writes to the controller remain disabled.",
        "battery_history": "Battery History", "last_24h": "24 hours", "last_7d": "7 days",
        "last_30d": "30 days", "history_empty": "History will appear after battery readings are received.",
        "device_info": "Device information", "model": "Model", "vendor_id": "Vendor ID",
        "product_id": "Product ID", "data_source": "Data source", "capabilities": "Verified capabilities",
        "read_only": "Read only", "safe_control": "Safe control", "supported": "Supported", "not_verified": "Not verified yet",
        "appearance": "Appearance and access", "language": "Language", "reduced_motion": "Reduce motion",
        "history_enabled": "Save local history", "notifications": "Battery notifications",
        "privacy_note": "Everything stays on this computer. OpenPad Hub has no accounts, cloud, or telemetry.",
        "system_check": "System check", "repair_permissions": "Repair permissions",
        "permission_help": "The controller is connected, but Linux cannot read its HID channel.",
        "unofficial": "Unofficial community project", "safe_mode": "Safe mode · no writes",
        "signal": "Signal", "no_signal": "Unavailable", "quit": "Quit", "open": "Open OpenPad Hub",
        "global_controller": "Generic controller", "live_inputs": "Live input", "sticks": "Sticks",
        "input_unavailable": "Input unavailable", "input_mode_help": "Use 2.4 GHz / XInput to read sticks and buttons.",
        "auto_detected": "Detected automatically", "lighting": "Lighting", "live_lighting": "Live lighting",
        "rgb_profile": "Active effect", "rgb_zones": "Controller zones", "rgb_live_note": "In #0, OpenPad maps telemetry to Left, Right, Logo, and Center. Animated modes remain read only.",
        "safety_checks": "Safety checks", "checkpoint": "Private checkpoint", "readback": "Configured-state read-back", "recovery": "Recovery", "ready": "Ready", "locked": "Pending", "create_checkpoint": "Create checkpoint", "original_profiles": "OpenPad profiles", "preview_only": "Preview only", "apply_profile": "Apply to controller", "reserved_slot": "Reserve one physical configuration for OpenPad before writes can be enabled.",
        "static_effect": "Static confirmed · four stable zones", "animated_effect": "Animation detected · alternating left/right", "spectrum_effect": "Animation detected · moving across all zones", "effect_unverified": "Unverified effect", "lighting_firmware_lock": "Static mode is now identified. Apply stays locked until a change-and-recovery test passes with read-back.", "lighting_ready": "Change, read-back, and recovery verified. Profiles apply only in static mode #0.", "applying": "Applying…",
        "profile_collection": "Profile collection", "active_profile": "Active profile", "active": "Active", "selected": "Selected", "verified": "Verified", "change_verified": "Applied and verified with 3 reads", "change_failed": "Change rejected", "static_required": "Select static effect #0 with M + left stick before applying", "effect_modes": "Controller effects", "effect_read_only": "Detected · read only", "physical_shortcut": "Change with M + left stick", "zone_left": "Left", "zone_right": "Right", "zone_logo": "Logo", "zone_center": "Center", "local_verified": "LOCAL · VERIFIED",
    },
}
TRANSLATIONS = load_qt_catalogs(TRANSLATIONS)


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class ReadWorker(QRunnable):
    def __init__(self, driver: ControllerDriver) -> None:
        super().__init__()
        self.driver = driver
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            self.signals.finished.emit(self.driver.read())
        except Exception as exc:  # A driver error must never crash the UI.
            self.signals.failed.emit(str(exc))


class ActionWorker(QRunnable):
    def __init__(self, action) -> None:
        super().__init__()
        self.action = action
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            self.action()
            self.signals.finished.emit(None)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class HubViewModel(QObject):
    stateChanged = Signal()
    inputsChanged = Signal()
    historyChanged = Signal()
    settingsChanged = Signal()
    requestShow = Signal()

    def __init__(self, driver: ControllerDriver, demo: bool = False) -> None:
        super().__init__()
        self.driver = driver
        self.demo = demo
        self.settings_store = SettingsStore()
        self.settings = self.settings_store.load()
        self.history = BatteryHistory()
        self.snapshot = ControllerSnapshot(capabilities=driver.capabilities)
        self.inputs_value: dict[str, object] = InputSnapshot().to_dict()
        self.diagnostics_value: list[dict[str, str]] = []
        self.history_value: list[dict[str, int | str]] = []
        self.history_hours = 24
        self.busy_value = False
        self.lighting_busy_value = False
        self.lighting_status_value = ""
        self.lighting_status_ok = True
        self.pending_lighting_profile = ""
        self.window_visible = True
        self.last_error = ""
        self.lighting_safety_state = load_safety_state()
        existing_checkpoint = latest_private_checkpoint()
        self.lighting_checkpoint_path = self.lighting_safety_state.checkpoint_path or (str(existing_checkpoint) if existing_checkpoint else "")
        self._worker: ReadWorker | ActionWorker | None = None
        self._notified_thresholds: set[int] = set()
        self.thread_pool = QThreadPool.globalInstance()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.input_timer = QTimer(self)
        self.input_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.input_timer.timeout.connect(self._poll_inputs)
        self.input_timer.start(16)
        QTimer.singleShot(0, self.refresh)

    @Property(bool, notify=stateChanged)
    def connected(self) -> bool:
        return self.snapshot.connected

    @Property(str, notify=stateChanged)
    def model(self) -> str:
        return self.snapshot.model

    @Property(int, notify=stateChanged)
    def batteryPercent(self) -> int:
        return self.snapshot.battery_percent if self.snapshot.battery_percent is not None else -1

    @Property(str, notify=stateChanged)
    def statusKey(self) -> str:
        return self.snapshot.status_key

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self.t(self.statusKey)

    @Property(str, notify=stateChanged)
    def connection(self) -> str:
        labels = {"usb": "USB", "wireless": "2.4 GHz", "bluetooth": "Bluetooth", "disconnected": "—"}
        return labels[self.snapshot.connection.value]

    @Property(str, notify=stateChanged)
    def vendorId(self) -> str:
        return self.snapshot.vendor_id.upper()

    @Property(str, notify=stateChanged)
    def productId(self) -> str:
        return self.snapshot.product_id.upper() or "—"

    @Property(str, notify=stateChanged)
    def source(self) -> str:
        return self.snapshot.source or "—"

    @Property(str, notify=stateChanged)
    def firmware(self) -> str:
        return self.snapshot.firmware or self.t("not_verified")

    @Property(str, notify=stateChanged)
    def signalText(self) -> str:
        return f"{self.snapshot.signal_percent}%" if self.snapshot.signal_percent is not None else self.t("no_signal")

    @Property(int, notify=stateChanged)
    def rgbProfile(self) -> int:
        return self.snapshot.rgb_profile if self.snapshot.rgb_profile is not None else -1

    @Property("QVariantList", notify=stateChanged)
    def rgbZones(self) -> list[str]:
        return self.snapshot.rgb_zones

    @Property("QVariantList", notify=stateChanged)
    def lightingZoneSamples(self) -> list[dict[str, str]]:
        colors = self.snapshot.rgb_zones
        if self.snapshot.rgb_profile == 0 and len(colors) >= 5:
            return [
                {"name": self.t("zone_left"), "color": colors[1], "source": "LIVE 2"},
                {"name": self.t("zone_right"), "color": colors[2], "source": "LIVE 3"},
                {"name": self.t("zone_logo"), "color": colors[0], "source": "LIVE 1"},
                {"name": self.t("zone_center"), "color": colors[4], "source": "LIVE 5"},
            ]
        return [
            {"name": f"LIVE {index + 1}", "color": color, "source": "TELEMETRY"}
            for index, color in enumerate(colors)
        ]

    @Property(str, notify=stateChanged)
    def lightingEffectText(self) -> str:
        effect_keys = {0: "static_effect", 1: "spectrum_effect", 2: "animated_effect"}
        return self.t(effect_keys.get(self.snapshot.rgb_profile, "effect_unverified"))

    @Property(bool, notify=stateChanged)
    def lightingMotionDetected(self) -> bool:
        return self.snapshot.rgb_profile in {1, 2}

    @Property(bool, notify=stateChanged)
    def lightingStaticReady(self) -> bool:
        return self.snapshot.rgb_profile == 0

    @Property("QVariantList", constant=True)
    def lightingProfiles(self) -> list[dict[str, object]]:
        return [profile.to_dict() for profile in LIGHTING_PROFILES]

    @Property(str, notify=stateChanged)
    def lightingActiveProfileId(self) -> str:
        return self.lighting_safety_state.active_profile_id

    @Property(str, notify=stateChanged)
    def lightingActiveProfileName(self) -> str:
        try:
            return get_profile(self.lighting_safety_state.active_profile_id).name
        except ValueError:
            return "—"

    @Property(str, notify=stateChanged)
    def lightingStatusText(self) -> str:
        if self.lighting_status_value:
            return self.lighting_status_value
        if self.lighting_safety_state.active_profile_id:
            return f"{self.lightingActiveProfileName} · {self.t('verified')}"
        return self.t("lighting_firmware_lock")

    @Property(bool, notify=stateChanged)
    def lightingStatusOk(self) -> bool:
        return self.lighting_status_ok

    @Property(bool, notify=stateChanged)
    def lightingCheckpointReady(self) -> bool:
        return bool(self.lighting_checkpoint_path)

    @Property(bool, notify=stateChanged)
    def lightingReadbackReady(self) -> bool:
        return self.lighting_safety_state.readback

    @Property(bool, notify=stateChanged)
    def lightingRecoveryReady(self) -> bool:
        return self.lighting_safety_state.recovery

    @Property(bool, notify=stateChanged)
    def lightingWritesUnlocked(self) -> bool:
        return self.lightingCheckpointReady and self.lightingReadbackReady and self.lightingRecoveryReady

    @Property(str, notify=stateChanged)
    def lightingCheckpointPath(self) -> str:
        return self.lighting_checkpoint_path

    @Slot(result=str)
    def createLightingCheckpoint(self) -> str:
        try:
            path = create_checkpoint(self.snapshot)
        except (OSError, ValueError) as exc:
            self.last_error = str(exc)
            self.stateChanged.emit()
            return str(exc)
        self.lighting_checkpoint_path = str(path)
        self.lighting_safety_state = LightingSafetyState(
            checkpoint=True,
            checkpoint_path=str(path),
            reserved_configuration=self.lighting_safety_state.reserved_configuration,
        )
        save_safety_state(self.lighting_safety_state)
        self.last_error = ""
        self.stateChanged.emit()
        return ""

    @Slot(str)
    def applyLightingProfile(self, profile_id: str) -> None:
        if self.lighting_busy_value or not self.lightingWritesUnlocked:
            return
        if not self.lightingStaticReady:
            self.lighting_status_value = self.t("static_required")
            self.lighting_status_ok = False
            self.stateChanged.emit()
            return
        try:
            profile = get_profile(profile_id)
        except ValueError as exc:
            self.lighting_status_value = str(exc)
            self.lighting_status_ok = False
            self.stateChanged.emit()
            return
        self.lighting_busy_value = True
        self.pending_lighting_profile = profile.name
        self.lighting_status_value = f"{self.t('applying')} {profile.name}"
        self.lighting_status_ok = True
        self.last_error = ""
        self.stateChanged.emit()
        worker = ActionWorker(lambda: self.driver.write_settings({
            "lighting_profile_id": profile_id,
            "reserved_configuration_confirmed": True,
        }))
        self._worker = worker
        worker.signals.finished.connect(self._lighting_applied)
        worker.signals.failed.connect(self._lighting_error)
        self.thread_pool.start(worker)

    @Slot(object)
    def _lighting_applied(self, _result: object) -> None:
        self.lighting_busy_value = False
        self.lighting_safety_state = load_safety_state()
        self.lighting_checkpoint_path = self.lighting_safety_state.checkpoint_path
        self.lighting_status_value = f"{self.pending_lighting_profile} · {self.t('change_verified')}"
        self.lighting_status_ok = True
        self.pending_lighting_profile = ""
        self._worker = None
        self.stateChanged.emit()
        QTimer.singleShot(0, self.refresh)

    @Slot(str)
    def _lighting_error(self, error: str) -> None:
        self.lighting_busy_value = False
        self.lighting_safety_state = load_safety_state()
        self.lighting_checkpoint_path = self.lighting_safety_state.checkpoint_path
        self.lighting_status_value = f"{self.t('change_failed')}: {error}"
        self.lighting_status_ok = False
        self.pending_lighting_profile = ""
        self.last_error = error
        self._worker = None
        self.stateChanged.emit()

    @Property(str, notify=stateChanged)
    def lastUpdated(self) -> str:
        return self.snapshot.updated_at.astimezone().strftime("%H:%M:%S")

    @Property(bool, notify=stateChanged)
    def permissionRequired(self) -> bool:
        return self.snapshot.permission_required

    @Property(bool, notify=stateChanged)
    def busy(self) -> bool:
        return self.busy_value

    @Property(bool, notify=stateChanged)
    def lightingBusy(self) -> bool:
        return self.lighting_busy_value

    @Property("QVariantMap", notify=stateChanged)
    def capabilities(self) -> dict[str, bool]:
        return self.snapshot.capabilities.to_dict()

    @Property("QVariantMap", notify=inputsChanged)
    def inputs(self) -> dict[str, object]:
        return self.inputs_value

    @Property("QVariantList", notify=stateChanged)
    def diagnostics(self) -> list[dict[str, str]]:
        return self.diagnostics_value

    @Property("QVariantList", notify=historyChanged)
    def historyPoints(self) -> list[dict[str, int | str]]:
        return self.history_value

    @Property(str, notify=settingsChanged)
    def language(self) -> str:
        return self.settings.language

    @Property(bool, notify=settingsChanged)
    def reducedMotion(self) -> bool:
        return self.settings.reduced_motion

    @Property(bool, notify=settingsChanged)
    def historyEnabled(self) -> bool:
        return self.settings.history_enabled

    @Property(bool, notify=settingsChanged)
    def notificationsEnabled(self) -> bool:
        return self.settings.notifications_enabled

    @Slot(str, result=str)
    def t(self, key: str) -> str:
        language = self.settings.language if self.settings.language in TRANSLATIONS else "en"
        return TRANSLATIONS[language].get(key, key.replace("_", " ").title())

    @Slot()
    def _poll_inputs(self) -> None:
        try:
            current = self.driver.read_inputs().to_dict()
        except Exception:
            current = InputSnapshot().to_dict()
        if current != self.inputs_value:
            self.inputs_value = current
            self.inputsChanged.emit()

    @Slot()
    def refresh(self) -> None:
        if self.busy_value or self.lighting_busy_value:
            return
        self.busy_value = True
        self.stateChanged.emit()
        worker = ReadWorker(self.driver)
        self._worker = worker
        worker.signals.finished.connect(self._apply_result)
        worker.signals.failed.connect(self._apply_error)
        self.thread_pool.start(worker)

    @Slot(object)
    def _apply_result(self, result: DriverResult) -> None:
        self.busy_value = False
        self.snapshot = result.snapshot
        result_inputs = result.inputs.to_dict()
        if result.inputs.available or not self.inputs_value.get("available", False):
            self.inputs_value = result_inputs
            self.inputsChanged.emit()
        self.diagnostics_value = result.diagnostics
        self.last_error = ""
        if self.settings.history_enabled:
            self.history.record(self.snapshot)
        self._load_history()
        self._check_notifications()
        self._worker = None
        self.stateChanged.emit()

    @Slot(str)
    def _apply_error(self, error: str) -> None:
        self.busy_value = False
        self.lighting_busy_value = False
        self.last_error = error
        self.diagnostics_value = [{"name": "Controller", "status": "warn", "detail": error}]
        self._worker = None
        self.stateChanged.emit()

    def _load_history(self) -> None:
        if self.demo and not self.history_value:
            import time
            now = int(time.time())
            self.history_value = [
                {"timestamp": now - (24 - index) * 3600, "percent": max(18, 91 - index * 3), "chargeState": "not_charging"}
                for index in range(25)
            ]
            self.history_value[-5:] = [
                {"timestamp": now - (4 - index) * 3600, "percent": 61 + index * 3, "chargeState": "charging"}
                for index in range(5)
            ]
        elif not self.demo:
            self.history_value = self.history.query(self.snapshot.device_id, self.history_hours)
        self.historyChanged.emit()

    def _check_notifications(self) -> None:
        percent = self.snapshot.battery_percent
        if percent is None or self.snapshot.charging:
            return
        for threshold in self.settings.low_battery_thresholds:
            if percent <= threshold and threshold not in self._notified_thresholds:
                self._notified_thresholds.add(threshold)
                tray = QApplication.instance().property("openpadTray")
                if self.settings.notifications_enabled and tray:
                    tray.showMessage("OpenPad Hub", f"Low battery: {percent}%", QSystemTrayIcon.Warning, 5000)

    @Slot(int)
    def setHistoryHours(self, hours: int) -> None:
        self.history_hours = hours
        self._load_history()

    def _save_settings(self) -> None:
        self.settings_store.save(self.settings)
        self.settingsChanged.emit()
        self.stateChanged.emit()

    @Slot(str)
    def setLanguage(self, language: str) -> None:
        if language in TRANSLATIONS and language != self.settings.language:
            self.settings.language = language
            self._save_settings()

    @Slot(bool)
    def setReducedMotion(self, enabled: bool) -> None:
        self.settings.reduced_motion = enabled
        self._save_settings()

    @Slot(bool)
    def setHistoryEnabled(self, enabled: bool) -> None:
        self.settings.history_enabled = enabled
        self._save_settings()

    @Slot(bool)
    def setNotificationsEnabled(self, enabled: bool) -> None:
        self.settings.notifications_enabled = enabled
        self._save_settings()

    @Slot(bool)
    def setWindowVisible(self, visible: bool) -> None:
        self.window_visible = visible
        self.timer.setInterval(500 if visible else 12000)
        self.input_timer.setInterval(16 if visible else 250)

    @Slot()
    def repairPermissions(self) -> None:
        candidates = [
            Path(__file__).resolve().parents[1] / "enable-device-access.sh",
            Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "openpad-hub/enable-device-access.sh",
            Path("/usr/libexec/openpad-hub/enable-device-access.sh"),
        ]
        script = next((path for path in candidates if path.exists()), None)
        if script:
            from PySide6.QtCore import QProcess
            QProcess.startDetached(str(script), [])


def _tray_icon() -> QIcon:
    themed = QIcon.fromTheme("input-gaming")
    if not themed.isNull():
        return themed
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#7C5CFF"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), 0x84, "O")
    painter.end()
    return QIcon(pixmap)


def _claim_instance(name: str) -> QLocalServer | None:
    socket = QLocalSocket()
    socket.connectToServer(name)
    if socket.waitForConnected(120):
        socket.write(b"show")
        socket.waitForBytesWritten(120)
        return None
    QLocalServer.removeServer(name)
    server = QLocalServer()
    return server if server.listen(name) else None


def run_gui(driver: ControllerDriver, background: bool = False, demo: bool = False) -> int:
    app = QApplication(sys.argv[:1])
    app.setApplicationName("OpenPad Hub")
    app.setOrganizationName("OpenPad Community")
    app.setQuitOnLastWindowClosed(False)

    server = _claim_instance("openpad-hub" if not demo else f"openpad-hub-demo-{os.getpid()}")
    if server is None:
        return 0

    hub = HubViewModel(driver, demo=demo)
    engine = QQmlApplicationEngine()
    engine.warnings.connect(lambda warnings: [print(error.toString(), file=sys.stderr) for error in warnings])
    engine.rootContext().setContextProperty("hub", hub)
    engine.rootContext().setContextProperty("startHidden", background)
    qml_path = Path(__file__).resolve().parent / "ui/Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        print(f"No se pudo cargar la interfaz QML: {qml_path}", file=sys.stderr)
        return 2
    window = engine.rootObjects()[0]

    tray = QSystemTrayIcon(_tray_icon(), app)
    menu = QMenu()
    open_action = QAction(hub.t("open"), menu)
    refresh_action = QAction(hub.t("refresh"), menu)
    quit_action = QAction(hub.t("quit"), menu)
    menu.addAction(open_action)
    menu.addAction(refresh_action)
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.setToolTip("OpenPad Hub")
    tray.show()
    app.setProperty("openpadTray", tray)

    def show_window() -> None:
        window.show()
        window.raise_()
        window.requestActivate()

    open_action.triggered.connect(show_window)
    refresh_action.triggered.connect(hub.refresh)
    quit_action.triggered.connect(app.quit)
    tray.activated.connect(lambda reason: show_window() if reason == QSystemTrayIcon.Trigger else None)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), show_window()))
    hub.stateChanged.connect(
        lambda: tray.setToolTip(
            f"OpenPad Hub · {hub.batteryPercent}% · {hub.statusText}" if hub.batteryPercent >= 0 else f"OpenPad Hub · {hub.statusText}"
        )
    )
    if not background:
        QTimer.singleShot(0, show_window)
    return app.exec()
