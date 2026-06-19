#!/usr/bin/env python3

import csv
import io
import json
import math
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PyQt5.QtCore import (
    QObject,
    QProcess,
    QThread,
    QTimer,
    QUrl,
    Qt,
    pyqtSignal,
    pyqtSlot,
)
from PyQt5.QtWebChannel import QWebChannel

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
except ModuleNotFoundError:
    print("Missing PyQt5 QtWebEngine module.")
    print("Install it with:")
    print("  sudo apt install python3-pyqt5.qtwebengine python3-pyqt5.qtwebchannel")
    print("or:")
    print("  python3 -m pip install --user PyQtWebEngine PyQtWebEngine-Qt5")
    raise

from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "Omni-Trainer SITL Launcher"

DEFAULT_ARDUPILOT = os.environ.get(
    "OMNI_ARDUPILOT_ROOT",
    str(Path.home() / "ardupilot"),
)
DEFAULT_MODEL = "Omni-Trainer"
DEFAULT_EFI_SCRIPT = str(Path(__file__).resolve().parent / "scripts" / "omni_efi_mavlink_sim.py")

LOCATION_NAME = "GUI_OMNI"

DEFAULT_LAT = -7.3421715173341076
DEFAULT_LNG = 108.24335290693834
DEFAULT_ALT_MSL = 50.0
DEFAULT_HEADING = 150.0

OURAIRPORTS_AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OURAIRPORTS_NAVAIDS_URL = "https://davidmegginson.github.io/ourairports-data/navaids.csv"

AVIATION_CACHE_DIR = Path.home() / ".omni_trainer" / "aviation"
OURAIRPORTS_CACHE_FILE = AVIATION_CACHE_DIR / "ourairports_airports_navaids_overlay.json"

AVIATION_RADIUS_KM = 220.0
AVIATION_CACHE_MAX_AGE_SEC = 7 * 24 * 60 * 60


def _safe_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)

    a = (
        math.sin(dp / 2.0) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    )

    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _download_csv_rows(url, timeout=30):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "OmniTrainerSITLLauncher/1.0"
        }
    )

    with urllib.request.urlopen(req, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")

    return list(csv.DictReader(io.StringIO(text)))


def _load_cached_aviation_overlay():
    if not OURAIRPORTS_CACHE_FILE.exists():
        return None

    age = time.time() - OURAIRPORTS_CACHE_FILE.stat().st_mtime
    if age > AVIATION_CACHE_MAX_AGE_SEC:
        return None

    try:
        data = json.loads(OURAIRPORTS_CACHE_FILE.read_text())
        data.setdefault("airports", [])
        data.setdefault("navaids", [])
        data.setdefault("stats", {})
        data["stats"].setdefault("airports_kept", len(data.get("airports", [])))
        data["stats"].setdefault("navaids_kept", len(data.get("navaids", [])))
        return data
    except Exception:
        return None


def _save_cached_aviation_overlay(data):
    AVIATION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OURAIRPORTS_CACHE_FILE.write_text(json.dumps(data, indent=2))


def _empty_aviation_overlay(message="No cached aviation overlay loaded yet. Press Update Aviation Overlay."):
    return {
        "source": "OurAirports public CSV dataset",
        "center": {
            "lat": DEFAULT_LAT,
            "lng": DEFAULT_LNG,
            "radius_km": AVIATION_RADIUS_KM,
        },
        "airports": [],
        "navaids": [],
        "warnings": [
            message,
            "Airports and navaids are from OurAirports public data.",
            "Verify official sources before flight.",
        ],
        "stats": {
            "airports_kept": 0,
            "navaids_kept": 0,
        },
    }


def load_initial_aviation_overlay():
    cached = _load_cached_aviation_overlay()
    if cached:
        cached.setdefault("center", {})
        cached["center"].setdefault("lat", DEFAULT_LAT)
        cached["center"].setdefault("lng", DEFAULT_LNG)
        cached["center"].setdefault("radius_km", AVIATION_RADIUS_KM)
        cached.setdefault("stats", {})
        cached["stats"].setdefault("airports_kept", len(cached.get("airports", [])))
        cached["stats"].setdefault("navaids_kept", len(cached.get("navaids", [])))
        return cached

    return _empty_aviation_overlay()


def build_aviation_overlay(
    center_lat=DEFAULT_LAT,
    center_lng=DEFAULT_LNG,
    radius_km=AVIATION_RADIUS_KM,
    force_refresh=False,
    progress_callback=None,
    should_stop=None,
):
    if not force_refresh:
        cached = _load_cached_aviation_overlay()
        if cached:
            cached["center"] = {
                "lat": center_lat,
                "lng": center_lng,
                "radius_km": radius_km,
            }
            return cached

    def progress(text):
        if progress_callback:
            progress_callback(text)

    overlay = {
        "source": "OurAirports public CSV dataset",
        "center": {
            "lat": center_lat,
            "lng": center_lng,
            "radius_km": radius_km,
        },
        "airports": [],
        "navaids": [],
        "warnings": [
            "Airports and navaids are from OurAirports public data.",
            "Verify official sources before flight.",
        ],
    }

    try:
        progress("Downloading OurAirports airports.csv...")
        airport_rows = _download_csv_rows(OURAIRPORTS_AIRPORTS_URL)

        if should_stop and should_stop():
            return overlay

        progress("Downloading OurAirports navaids.csv...")
        navaid_rows = _download_csv_rows(OURAIRPORTS_NAVAIDS_URL)

        if should_stop and should_stop():
            return overlay

        progress("Filtering Indonesian airports near operating area...")

        allowed_airport_types = {
            "large_airport",
            "medium_airport",
            "small_airport",
            "heliport",
            "seaplane_base",
            "balloonport",
            "closed",
        }

        for row in airport_rows:
            if should_stop and should_stop():
                return overlay

            if row.get("iso_country") != "ID":
                continue

            lat = _safe_float(row.get("latitude_deg"))
            lng = _safe_float(row.get("longitude_deg"))

            if lat is None or lng is None:
                continue

            distance_km = _haversine_km(center_lat, center_lng, lat, lng)
            if distance_km > radius_km:
                continue

            airport_type = row.get("type", "")
            if airport_type not in allowed_airport_types:
                continue

            overlay["airports"].append(
                {
                    "ident": row.get("ident", ""),
                    "iata": row.get("iata_code", ""),
                    "name": row.get("name", ""),
                    "type": airport_type,
                    "municipality": row.get("municipality", ""),
                    "lat": lat,
                    "lng": lng,
                    "elevation_ft": _safe_float(row.get("elevation_ft")),
                    "distance_km": distance_km,
                }
            )

        progress("Filtering Indonesian navaids near operating area...")

        for row in navaid_rows:
            if should_stop and should_stop():
                return overlay

            if row.get("iso_country") != "ID":
                continue

            lat = _safe_float(row.get("latitude_deg"))
            lng = _safe_float(row.get("longitude_deg"))

            if lat is None or lng is None:
                continue

            distance_km = _haversine_km(center_lat, center_lng, lat, lng)
            if distance_km > radius_km:
                continue

            overlay["navaids"].append(
                {
                    "ident": row.get("ident", ""),
                    "name": row.get("name", ""),
                    "type": row.get("type", ""),
                    "frequency_khz": row.get("frequency_khz", ""),
                    "lat": lat,
                    "lng": lng,
                    "elevation_ft": _safe_float(row.get("elevation_ft")),
                    "distance_km": distance_km,
                }
            )

        overlay["airports"].sort(key=lambda item: item.get("distance_km", 999999.0))
        overlay["navaids"].sort(key=lambda item: item.get("distance_km", 999999.0))

        overlay["stats"] = {
            "airports_kept": len(overlay["airports"]),
            "navaids_kept": len(overlay["navaids"]),
        }

        _save_cached_aviation_overlay(overlay)

        progress(
            f"Aviation overlay complete. "
            f"Airports={len(overlay['airports'])}, "
            f"Navaids={len(overlay['navaids'])}."
        )

        return overlay

    except Exception as exc:
        fallback = _empty_aviation_overlay(
            f"Could not download OurAirports data. Using fallback WICM marker only. Error: {exc}"
        )

        fallback["source"] = "Fallback marker"
        fallback["center"] = {
            "lat": center_lat,
            "lng": center_lng,
            "radius_km": radius_km,
        }
        fallback["airports"] = [
            {
                "ident": "WICM",
                "iata": "TSY",
                "name": "Wiriadinata / Tasikmalaya fallback marker",
                "type": "small_airport",
                "municipality": "Tasikmalaya",
                "lat": -7.345483,
                "lng": 108.245422,
                "elevation_ft": None,
                "distance_km": _haversine_km(center_lat, center_lng, -7.345483, 108.245422),
            }
        ]
        fallback["stats"] = {
            "airports_kept": 1,
            "navaids_kept": 0,
        }

        return fallback


MAP_HTML = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <title>Omni-Trainer Start Location</title>

    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>

    <style>
        html, body, #map {
            height: 100%;
            width: 100%;
            margin: 0;
            padding: 0;
            background: #111;
        }

        .info {
            background: white;
            padding: 8px 10px;
            border-radius: 7px;
            font-family: Arial, sans-serif;
            font-size: 13px;
            box-shadow: 0 2px 10px rgba(0,0,0,.25);
        }

        .aviation-legend {
            background: rgba(255, 255, 255, 0.95);
            padding: 9px 11px;
            border-radius: 7px;
            font-family: Arial, sans-serif;
            font-size: 12px;
            line-height: 1.35;
            box-shadow: 0 2px 10px rgba(0,0,0,.25);
            min-width: 250px;
        }

        .legend-title {
            font-weight: bold;
            margin-bottom: 5px;
        }

        .legend-row {
            display: flex;
            align-items: center;
            margin-top: 4px;
        }

        .legend-airport {
            width: 12px;
            height: 12px;
            border: 2px solid #ffffff;
            border-radius: 50%;
            background: #2962ff;
            margin-right: 9px;
        }

        .legend-navaid {
            width: 12px;
            height: 12px;
            border: 2px solid #ffffff;
            background: #00c853;
            transform: rotate(45deg);
            margin-right: 9px;
        }

        .legend-radius {
            width: 13px;
            height: 13px;
            border: 2px solid #69f0ae;
            border-radius: 50%;
            background: rgba(105, 240, 174, 0.16);
            margin-right: 10px;
        }

        .warning {
            margin-top: 7px;
            padding-top: 6px;
            border-top: 1px solid #ddd;
            color: #8a4b00;
            font-weight: bold;
        }

        .air-label {
            color: white;
            font-family: Arial, sans-serif;
            font-size: 11px;
            font-weight: bold;
            text-shadow:
                -1px -1px 2px #000,
                 1px -1px 2px #000,
                -1px  1px 2px #000,
                 1px  1px 2px #000;
            white-space: nowrap;
        }

        .airport-label {
            color: #ffffff;
            font-family: Arial, sans-serif;
            font-size: 12px;
            font-weight: bold;
            text-shadow:
                -1px -1px 2px #000,
                 1px -1px 2px #000,
                -1px  1px 2px #000,
                 1px  1px 2px #000;
            white-space: nowrap;
        }
    </style>
</head>

<body>
<div id="map"></div>

<script>
    let bridge = null;

    new QWebChannel(qt.webChannelTransport, function(channel) {
        bridge = channel.objects.bridge;
    });

    const startLat = -7.3421715173341076;
    const startLng = 108.24335290693834;

    const aviationData = __AVIATION_OVERLAY_DATA__;

    const map = L.map('map', {
        preferCanvas: true
    }).setView([startLat, startLng], 12);

    map.createPane('aviationPane');
    map.getPane('aviationPane').style.zIndex = 430;

    map.createPane('aviationLabelPane');
    map.getPane('aviationLabelPane').style.zIndex = 650;
    map.getPane('aviationLabelPane').style.pointerEvents = 'none';

    const osm = L.tileLayer(
        'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        {
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap contributors'
        }
    );

    const topo = L.tileLayer(
        'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
        {
            maxZoom: 17,
            attribution: 'Map data: &copy; OpenStreetMap contributors, SRTM | Map style: &copy; OpenTopoMap'
        }
    );

    const esriImagery = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        {
            maxZoom: 19,
            attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community'
        }
    );

    const esriLabels = L.tileLayer(
        'https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
        {
            maxZoom: 19,
            attribution: 'Labels &copy; Esri'
        }
    );

    const hybrid = L.layerGroup([esriImagery, esriLabels]);
    hybrid.addTo(map);

    const aviationOverlay = L.layerGroup();
    const airportLayer = L.layerGroup().addTo(aviationOverlay);
    const navaidLayer = L.layerGroup().addTo(aviationOverlay);
    const aviationRadiusLayer = L.layerGroup().addTo(aviationOverlay);

    const airportStyle = {
        pane: 'aviationPane',
        radius: 6,
        color: '#ffffff',
        weight: 2,
        opacity: 1.0,
        fillColor: '#2962ff',
        fillOpacity: 0.95
    };

    const navaidStyle = {
        pane: 'aviationPane',
        radius: 5,
        color: '#ffffff',
        weight: 2,
        opacity: 1.0,
        fillColor: '#00c853',
        fillOpacity: 0.95
    };

    function htmlEscape(value) {
        if (value === null || value === undefined) {
            return '';
        }

        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function addTextLabel(group, lat, lng, text, className) {
        const icon = L.divIcon({
            className: className,
            html: htmlEscape(text),
            iconSize: null,
            iconAnchor: [0, 0]
        });

        return L.marker([lat, lng], {
            icon: icon,
            pane: 'aviationLabelPane',
            interactive: false
        }).addTo(group);
    }

    function addAirport(group, airport) {
        const ident = airport.ident || airport.iata || 'AIRPORT';
        const name = airport.name || '';
        const elev = airport.elevation_ft !== null && airport.elevation_ft !== undefined
            ? airport.elevation_ft + ' ft'
            : 'N/A';

        const marker = L.circleMarker([airport.lat, airport.lng], airportStyle).addTo(group);

        marker.bindPopup(
            '<b>' + htmlEscape(ident) + '</b><br>' +
            htmlEscape(name) + '<br>' +
            'Type: ' + htmlEscape(airport.type || 'N/A') + '<br>' +
            'Municipality: ' + htmlEscape(airport.municipality || 'N/A') + '<br>' +
            'Elevation: ' + htmlEscape(elev) + '<br>' +
            'Distance: ' + Number(airport.distance_km || 0).toFixed(1) + ' km<br>' +
            '<span style="color:#8a4b00;"><b>Verify with official source before flight.</b></span>'
        );

        addTextLabel(group, airport.lat + 0.006, airport.lng + 0.006, ident, 'airport-label');
        return marker;
    }

    function addNavaid(group, navaid) {
        const ident = navaid.ident || 'NAVAID';
        const name = navaid.name || '';
        const freq = navaid.frequency_khz ? navaid.frequency_khz + ' kHz' : 'N/A';

        const marker = L.circleMarker([navaid.lat, navaid.lng], navaidStyle).addTo(group);

        marker.bindPopup(
            '<b>' + htmlEscape(ident) + '</b><br>' +
            htmlEscape(name) + '<br>' +
            'Type: ' + htmlEscape(navaid.type || 'N/A') + '<br>' +
            'Frequency: ' + htmlEscape(freq) + '<br>' +
            'Distance: ' + Number(navaid.distance_km || 0).toFixed(1) + ' km<br>' +
            '<span style="color:#8a4b00;"><b>Verify with official source before flight.</b></span>'
        );

        addTextLabel(group, navaid.lat + 0.006, navaid.lng + 0.006, ident, 'air-label');
        return marker;
    }

    function addAviationRadius() {
        if (!aviationData || !aviationData.center) {
            return;
        }

        const center = aviationData.center;
        const radiusMeters = Number(center.radius_km || 220) * 1000.0;

        const circle = L.circle([center.lat, center.lng], {
            pane: 'aviationPane',
            radius: radiusMeters,
            color: '#69f0ae',
            weight: 2,
            opacity: 0.65,
            fillColor: '#69f0ae',
            fillOpacity: 0.03
        }).addTo(aviationRadiusLayer);

        circle.bindPopup(
            '<b>Aviation data filter radius</b><br>' +
            'Radius: ' + Number(center.radius_km || 0).toFixed(0) + ' km'
        );
    }

    function renderAviationOverlay() {
        if (!aviationData) {
            return;
        }

        addAviationRadius();

        if (Array.isArray(aviationData.airports)) {
            aviationData.airports.forEach(function(airport) {
                addAirport(airportLayer, airport);
            });
        }

        if (Array.isArray(aviationData.navaids)) {
            aviationData.navaids.forEach(function(navaid) {
                addNavaid(navaidLayer, navaid);
            });
        }
    }

    renderAviationOverlay();
    aviationOverlay.addTo(map);

    L.control.layers(
        {
            "Satellite Hybrid": hybrid,
            "Satellite": esriImagery,
            "Terrain": topo,
            "Street Map": osm
        },
        {
            "Aviation Overlay": aviationOverlay,
            "Airports": airportLayer,
            "Navaids": navaidLayer,
            "Aviation Filter Radius": aviationRadiusLayer
        },
        {
            collapsed: false
        }
    ).addTo(map);

    const legend = L.control({position: 'bottomright'});
    legend.onAdd = function() {
        const div = L.DomUtil.create('div', 'aviation-legend');

        const airportCount = aviationData && aviationData.airports ? aviationData.airports.length : 0;
        const navaidCount = aviationData && aviationData.navaids ? aviationData.navaids.length : 0;
        const source = aviationData && aviationData.source ? aviationData.source : 'OurAirports';

        div.innerHTML =
            '<div class="legend-title">Aviation Overlay</div>' +

            '<div class="legend-row">' +
            '<div class="legend-airport"></div>' +
            '<div>Airports: ' + airportCount + '</div>' +
            '</div>' +

            '<div class="legend-row">' +
            '<div class="legend-navaid"></div>' +
            '<div>Navaids: ' + navaidCount + '</div>' +
            '</div>' +

            '<div class="legend-row">' +
            '<div class="legend-radius"></div>' +
            '<div>Overlay filter radius</div>' +
            '</div>' +

            '<div style="margin-top:7px;">Source: ' + htmlEscape(source) + '</div>' +

            '<div class="warning">' +
            'For simulation only.' +
            '</div>';

        return div;
    };
    legend.addTo(map);

    let marker = L.marker([startLat, startLng], {draggable: true}).addTo(map);

    const info = L.control({position: 'bottomleft'});
    info.onAdd = function() {
        this._div = L.DomUtil.create('div', 'info');
        this.update(startLat, startLng);
        return this._div;
    };

    info.update = function(lat, lng) {
        const airportCount = aviationData && aviationData.airports ? aviationData.airports.length : 0;
        const navaidCount = aviationData && aviationData.navaids ? aviationData.navaids.length : 0;

        this._div.innerHTML =
            '<b>Simulation start point</b><br>' +
            'Lat: ' + lat.toFixed(7) + '<br>' +
            'Lng: ' + lng.toFixed(7) + '<br>' +
            'Click map or drag marker.<br><br>' +
            '<b>Aviation data:</b><br>' +
            airportCount + ' airports, ' + navaidCount + ' navaids';
    };

    info.addTo(map);

    function notifyPython(latlng) {
        marker.setLatLng(latlng);
        info.update(latlng.lat, latlng.lng);

        if (bridge) {
            bridge.locationSelected(latlng.lat, latlng.lng);
        }
    }

    map.on('click', function(e) {
        notifyPython(e.latlng);
    });

    marker.on('dragend', function(e) {
        notifyPython(marker.getLatLng());
    });

    function setMarker(lat, lng) {
        const ll = L.latLng(lat, lng);
        marker.setLatLng(ll);
        map.setView(ll, map.getZoom());
        info.update(lat, lng);
    }
</script>
</body>
</html>
"""


class MapBridge(QObject):
    location_changed = pyqtSignal(float, float)

    @pyqtSlot(float, float)
    def locationSelected(self, lat, lng):
        self.location_changed.emit(float(lat), float(lng))


class ProcessRunner(QObject):
    output = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, name):
        super().__init__()
        self.name = name
        self.proc = None

    def is_running(self):
        return self.proc is not None and self.proc.state() != QProcess.NotRunning

    def start(self, cmd, cwd=None):
        self.stop()

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)

        if cwd:
            self.proc.setWorkingDirectory(str(cwd))

        self.proc.readyReadStandardOutput.connect(self._read_output)
        self.proc.finished.connect(self._finished)

        self.output.emit("")
        self.output.emit(f"[{self.name}] $ {' '.join(cmd)}")

        self.proc.start(cmd[0], cmd[1:])

        if not self.proc.waitForStarted(5000):
            self.output.emit(f"[{self.name}] ERROR: failed to start process.")

    def stop(self):
        if self.proc is None:
            return

        if self.proc.state() != QProcess.NotRunning:
            self.output.emit(f"[{self.name}] stopping...")
            self.proc.terminate()

            if not self.proc.waitForFinished(2500):
                self.proc.kill()
                self.proc.waitForFinished(2500)

        self.proc = None

    def _read_output(self):
        if not self.proc:
            return

        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not data:
            return

        for line in data.rstrip().splitlines():
            self.output.emit(f"[{self.name}] {line}")

    def _finished(self, exit_code, exit_status):
        self.output.emit(f"[{self.name}] finished. exit_code={exit_code}, status={exit_status}")
        self.finished.emit(self.name)


class AviationWorker(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, center_lat, center_lng):
        super().__init__()
        self.cancelled = False
        self.center_lat = center_lat
        self.center_lng = center_lng

    @pyqtSlot()
    def run(self):
        try:
            data = build_aviation_overlay(
                center_lat=self.center_lat,
                center_lng=self.center_lng,
                radius_km=AVIATION_RADIUS_KM,
                force_refresh=True,
                progress_callback=self.progress.emit,
                should_stop=lambda: self.cancelled,
            )
            self.finished.emit(data)
        except Exception as exc:
            self.error.emit(str(exc))

    def cancel(self):
        self.cancelled = True


class OmniLauncher(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(APP_NAME)
        self.resize(1320, 820)

        self.bridge = MapBridge()
        self.bridge.location_changed.connect(self.on_map_location)

        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)

        self.install_runner = ProcessRunner("INSTALL")
        self.sitl_runner = ProcessRunner("SITL")
        self.efi_runner = ProcessRunner("EFI")

        self.install_runner.output.connect(self.log)
        self.sitl_runner.output.connect(self.log)
        self.efi_runner.output.connect(self.log)

        self.aviation_overlay_data = load_initial_aviation_overlay()
        self.aviation_thread = None
        self.aviation_worker = None

        self._build_ui()

        self.selected_lat.setValue(DEFAULT_LAT)
        self.selected_lng.setValue(DEFAULT_LNG)
        self.home_alt_msl.setValue(DEFAULT_ALT_MSL)
        self.heading_deg.setValue(DEFAULT_HEADING)

        stats = self.aviation_overlay_data.get("stats", {})
        airports = stats.get("airports_kept", len(self.aviation_overlay_data.get("airports", [])))
        navaids = stats.get("navaids_kept", len(self.aviation_overlay_data.get("navaids", [])))

        self.status(f"Ready. Loaded overlay: {airports} airports, {navaids} navaids.")

    def _build_ui(self):
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        top_splitter = QSplitter(Qt.Horizontal)

        self.map_view = QWebEngineView()
        self.map_view.page().setWebChannel(self.channel)
        self.reload_map_html()
        self.map_view.setMinimumWidth(720)

        side_panel = self._build_side_panel()

        top_splitter.addWidget(self.map_view)
        top_splitter.addWidget(side_panel)
        top_splitter.setStretchFactor(0, 4)
        top_splitter.setStretchFactor(1, 1)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(2000)
        self.log_box.setPlaceholderText("Simulation log will appear here.")

        bottom_box = QGroupBox("Log")
        bottom_layout = QVBoxLayout(bottom_box)
        bottom_layout.addWidget(self.log_box)

        main_splitter = QSplitter(Qt.Vertical)
        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(bottom_box)
        main_splitter.setStretchFactor(0, 5)
        main_splitter.setStretchFactor(1, 2)

        root_layout.addWidget(main_splitter)
        self.setCentralWidget(root)

    def _build_side_panel(self):
        panel = QWidget()
        panel.setMinimumWidth(360)
        panel.setMaximumWidth(470)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel("Omni-Trainer SITL")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")

        hint = QLabel("1. Pick start point on map\n2. Check altitude and heading\n3. Start simulation")
        hint.setStyleSheet("color: #555;")

        layout.addWidget(title)
        layout.addWidget(hint)

        start_box = QGroupBox("Start Point")
        start_grid = QGridLayout(start_box)

        self.selected_lat = QDoubleSpinBox()
        self.selected_lng = QDoubleSpinBox()
        self.home_alt_msl = QDoubleSpinBox()
        self.heading_deg = QDoubleSpinBox()
        self.alt_offset = QDoubleSpinBox()

        self.selected_lat.setDecimals(7)
        self.selected_lng.setDecimals(7)
        self.home_alt_msl.setDecimals(2)
        self.heading_deg.setDecimals(1)
        self.alt_offset.setDecimals(1)

        self.selected_lat.setRange(-90.0, 90.0)
        self.selected_lng.setRange(-180.0, 180.0)
        self.home_alt_msl.setRange(-500.0, 9000.0)
        self.heading_deg.setRange(0.0, 359.9)
        self.alt_offset.setRange(-100.0, 1000.0)
        self.alt_offset.setValue(0.0)

        fetch_btn = QPushButton("Update Terrain Altitude")
        fetch_btn.clicked.connect(self.fetch_elevation_for_current)

        self.refresh_aviation_btn = QPushButton("Update Aviation Overlay")
        self.refresh_aviation_btn.clicked.connect(self.refresh_aviation_overlay)

        start_grid.addWidget(QLabel("Latitude"), 0, 0)
        start_grid.addWidget(self.selected_lat, 0, 1)

        start_grid.addWidget(QLabel("Longitude"), 1, 0)
        start_grid.addWidget(self.selected_lng, 1, 1)

        start_grid.addWidget(QLabel("Home alt MSL, m"), 2, 0)
        start_grid.addWidget(self.home_alt_msl, 2, 1)

        start_grid.addWidget(QLabel("Heading, deg"), 3, 0)
        start_grid.addWidget(self.heading_deg, 3, 1)

        start_grid.addWidget(QLabel("Alt offset, m"), 4, 0)
        start_grid.addWidget(self.alt_offset, 4, 1)

        start_grid.addWidget(fetch_btn, 5, 0, 1, 2)
        start_grid.addWidget(self.refresh_aviation_btn, 6, 0, 1, 2)

        layout.addWidget(start_box)

        sim_box = QGroupBox("Simulation")
        sim_grid = QGridLayout(sim_box)

        self.ardupilot_path = QLineEdit(DEFAULT_ARDUPILOT)
        self.model_name = QLineEdit(DEFAULT_MODEL)
        self.efi_script = QLineEdit(DEFAULT_EFI_SCRIPT)

        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_ardupilot)

        sim_grid.addWidget(QLabel("ArduPilot"), 0, 0)
        sim_grid.addWidget(self.ardupilot_path, 0, 1)
        sim_grid.addWidget(browse_btn, 0, 2)

        sim_grid.addWidget(QLabel("Model"), 1, 0)
        sim_grid.addWidget(self.model_name, 1, 1, 1, 2)

        sim_grid.addWidget(QLabel("EFI script"), 2, 0)
        sim_grid.addWidget(self.efi_script, 2, 1, 1, 2)

        self.start_efi_checkbox = QCheckBox("Start EFI injector")
        self.start_efi_checkbox.setChecked(True)

        self.open_console_checkbox = QCheckBox("Open console")
        self.open_console_checkbox.setChecked(True)

        self.open_map_checkbox = QCheckBox("Open MAVProxy map")
        self.open_map_checkbox.setChecked(True)

        self.efi_rate = QSpinBox()
        self.efi_rate.setRange(1, 50)
        self.efi_rate.setValue(10)

        self.output_gcs = QLineEdit("udp:127.0.0.1:14550")
        self.efi_connect = QLineEdit("tcp:127.0.0.1:5762")

        sim_grid.addWidget(self.start_efi_checkbox, 3, 0, 1, 2)
        sim_grid.addWidget(QLabel("EFI Hz"), 3, 2)
        sim_grid.addWidget(self.efi_rate, 3, 3)

        sim_grid.addWidget(self.open_console_checkbox, 4, 0, 1, 2)
        sim_grid.addWidget(self.open_map_checkbox, 4, 2, 1, 2)

        sim_grid.addWidget(QLabel("GCS out"), 5, 0)
        sim_grid.addWidget(self.output_gcs, 5, 1, 1, 3)

        sim_grid.addWidget(QLabel("EFI port"), 6, 0)
        sim_grid.addWidget(self.efi_connect, 6, 1, 1, 3)

        layout.addWidget(sim_box)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(
            "padding: 8px; border-radius: 6px; background: #eeeeee; color: #222;"
        )
        self.status_label.setWordWrap(True)

        layout.addWidget(self.status_label)

        button_row_1 = QHBoxLayout()

        self.install_btn = QPushButton("Install Tools")
        self.install_btn.clicked.connect(self.install_dependencies)

        self.start_btn = QPushButton("Start Simulation")
        self.start_btn.setStyleSheet("font-weight: bold; padding: 8px;")
        self.start_btn.clicked.connect(self.start_simulation)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setStyleSheet("padding: 8px;")
        self.stop_btn.clicked.connect(self.stop_simulation)

        button_row_1.addWidget(self.install_btn)
        button_row_1.addWidget(self.start_btn)
        button_row_1.addWidget(self.stop_btn)

        layout.addLayout(button_row_1)
        layout.addStretch(1)

        return panel

    def reload_map_html(self):
        embedded_json = json.dumps(self.aviation_overlay_data).replace("</", "<\\/")
        map_html = MAP_HTML.replace("__AVIATION_OVERLAY_DATA__", embedded_json)
        self.map_view.setHtml(map_html, QUrl("qrc:///"))

    def update_overlay_center(self):
        self.aviation_overlay_data.setdefault("center", {})
        self.aviation_overlay_data["center"]["lat"] = self.selected_lat.value()
        self.aviation_overlay_data["center"]["lng"] = self.selected_lng.value()
        self.aviation_overlay_data["center"]["radius_km"] = AVIATION_RADIUS_KM

    def log(self, text):
        self.log_box.appendPlainText(text.rstrip())

    def status(self, text):
        self.status_label.setText(text)
        self.statusBar().showMessage(text)

    def browse_ardupilot(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select ArduPilot root",
            self.ardupilot_path.text()
        )

        if directory:
            self.ardupilot_path.setText(directory)

    def ardupilot_root(self):
        return Path(self.ardupilot_path.text()).expanduser().resolve()

    def validate_paths(self):
        root = self.ardupilot_root()

        sim_vehicle = root / "Tools" / "autotest" / "sim_vehicle.py"
        model_dir = root / "Tools" / "autotest" / "aircraft" / self.model_name.text()
        efi = root / self.efi_script.text()

        if not root.exists():
            raise RuntimeError(f"ArduPilot root does not exist:\n{root}")

        if not sim_vehicle.exists():
            raise RuntimeError(f"sim_vehicle.py not found:\n{sim_vehicle}")

        if not model_dir.exists():
            raise RuntimeError(f"Model directory not found:\n{model_dir}")

        if self.start_efi_checkbox.isChecked() and not efi.exists():
            raise RuntimeError(f"EFI script not found:\n{efi}")

    def on_map_location(self, lat, lng):
        self.selected_lat.setValue(lat)
        self.selected_lng.setValue(lng)
        self.fetch_elevation_for_current()

    def fetch_elevation_for_current(self):
        lat = self.selected_lat.value()
        lng = self.selected_lng.value()

        self.status("Fetching terrain elevation...")

        try:
            url = f"https://api.opentopodata.org/v1/srtm30m?locations={lat:.7f},{lng:.7f}"

            with urllib.request.urlopen(url, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))

            if data.get("status") not in ("OK", "ok"):
                raise RuntimeError(str(data))

            results = data.get("results", [])
            if not results:
                raise RuntimeError("No elevation result returned.")

            elev = results[0].get("elevation")
            if elev is None:
                raise RuntimeError("Elevation is null for this point.")

            msl = float(elev) + float(self.alt_offset.value())
            self.home_alt_msl.setValue(msl)

            self.status(f"Terrain elevation: {elev:.1f} m MSL. Home set to {msl:.1f} m MSL.")

        except Exception as exc:
            self.status("Terrain lookup failed. Enter Home altitude MSL manually.")
            QMessageBox.warning(
                self,
                "Terrain elevation lookup failed",
                "Could not fetch terrain elevation.\n\n"
                "You can still enter Home altitude MSL manually.\n\n"
                f"Error: {exc}"
            )

    def refresh_aviation_overlay(self):
        if self.aviation_thread and self.aviation_thread.isRunning():
            self.status("Aviation overlay update is already running.")
            return

        self.update_overlay_center()

        self.status("Updating aviation overlay...")
        self.log("[AVIATION] Downloading OurAirports airports and navaids.")

        self.refresh_aviation_btn.setEnabled(False)
        self.refresh_aviation_btn.setText("Updating Overlay...")

        self.aviation_thread = QThread(self)
        self.aviation_worker = AviationWorker(
            center_lat=self.selected_lat.value(),
            center_lng=self.selected_lng.value(),
        )
        self.aviation_worker.moveToThread(self.aviation_thread)

        self.aviation_thread.started.connect(self.aviation_worker.run)
        self.aviation_worker.progress.connect(self.on_aviation_progress)
        self.aviation_worker.finished.connect(self.on_aviation_finished)
        self.aviation_worker.error.connect(self.on_aviation_error)

        self.aviation_worker.finished.connect(self.aviation_thread.quit)
        self.aviation_worker.error.connect(self.aviation_thread.quit)
        self.aviation_worker.finished.connect(self.aviation_worker.deleteLater)
        self.aviation_worker.error.connect(self.aviation_worker.deleteLater)
        self.aviation_thread.finished.connect(self.aviation_thread.deleteLater)

        self.aviation_thread.start()

    def on_aviation_progress(self, text):
        self.log(f"[AVIATION] {text}")
        self.status(text)

    def on_aviation_finished(self, data):
        self.aviation_overlay_data = data
        self.reload_map_html()

        stats = data.get("stats", {})
        airports = stats.get("airports_kept", len(data.get("airports", [])))
        navaids = stats.get("navaids_kept", len(data.get("navaids", [])))

        self.log(
            f"[AVIATION] Updated overlay. "
            f"airports={airports}, navaids={navaids}"
        )

        self.status(f"Aviation overlay updated. Airports={airports}, navaids={navaids}.")

        self.refresh_aviation_btn.setEnabled(True)
        self.refresh_aviation_btn.setText("Update Aviation Overlay")

        self.aviation_thread = None
        self.aviation_worker = None

    def on_aviation_error(self, error_text):
        self.status("Aviation overlay update failed.")
        self.log(f"[AVIATION] ERROR: {error_text}")

        self.refresh_aviation_btn.setEnabled(True)
        self.refresh_aviation_btn.setText("Update Aviation Overlay")

        self.aviation_thread = None
        self.aviation_worker = None

        QMessageBox.warning(
            self,
            "Aviation overlay update failed",
            "Could not update aviation overlay.\n\n"
            f"Error: {error_text}"
        )

    def write_location(self):
        root = self.ardupilot_root()
        locations_file = root / "Tools" / "autotest" / "locations.txt"

        if not locations_file.exists():
            raise RuntimeError(f"locations.txt not found:\n{locations_file}")

        lat = self.selected_lat.value()
        lng = self.selected_lng.value()
        alt = self.home_alt_msl.value()
        hdg = self.heading_deg.value()

        new_line = f"{LOCATION_NAME}={lat:.7f},{lng:.7f},{alt:.2f},{hdg:.1f}\n"

        lines = locations_file.read_text().splitlines(True)
        output = []
        replaced = False

        for line in lines:
            if line.startswith(f"{LOCATION_NAME}="):
                output.append(new_line)
                replaced = True
            else:
                output.append(line)

        if not replaced:
            if output and not output[-1].endswith("\n"):
                output[-1] += "\n"
            output.append(new_line)

        locations_file.write_text("".join(output))

        self.log(f"[APP] Wrote start location: {new_line.strip()}")

    def install_dependencies(self):
        root = self.ardupilot_root()

        self.log_box.clear()
        self.status("Installing/checking required tools...")

        cmd = [
            "bash",
            "-lc",
            (
                "set -e\n"
                "echo '[1/5] Installing Ubuntu packages...'\n"
                "sudo apt update\n"
                "sudo apt install -y "
                "git python3-pip python3-setuptools python3-wheel "
                "python3-pyqt5 python3-pyqt5.qtwebengine python3-pyqt5.qtwebchannel "
                "jsbsim xterm\n"
                "echo '[2/5] Installing Python MAVLink tools...'\n"
                "python3 -m pip install --user --upgrade pymavlink MAVProxy\n"
                "echo '[3/5] Running ArduPilot prerequisite script if available...'\n"
                f"cd '{root}'\n"
                "if [ -x Tools/environment_install/install-prereqs-ubuntu.sh ]; then\n"
                "    Tools/environment_install/install-prereqs-ubuntu.sh -y || true\n"
                "else\n"
                "    echo 'No install-prereqs-ubuntu.sh found, skipping.'\n"
                "fi\n"
                "echo '[4/5] Checking sim_vehicle.py...'\n"
                "test -f Tools/autotest/sim_vehicle.py\n"
                "echo '[5/5] Done.'\n"
            )
        ]

        self.install_runner.start(cmd, cwd=root)

    def build_sitl_command(self):
        root = self.ardupilot_root()

        args = [
            "./Tools/autotest/sim_vehicle.py",
            "-v",
            "ArduPlane",
            "-f",
            f"jsbsim:{self.model_name.text().strip()}",
            "-L",
            LOCATION_NAME,
        ]

        if self.open_console_checkbox.isChecked():
            args.append("--console")

        if self.open_map_checkbox.isChecked():
            args.append("--map")

        output = self.output_gcs.text().strip()
        if output:
            args.append(f"--out={output}")

        bash_cmd = (
            "export PATH=\"$PATH:$HOME/.local/bin:$HOME/jsbsim/build/src\"; "
            + " ".join(args)
        )

        return ["bash", "-lc", bash_cmd], root

    def build_efi_command(self):
        root = self.ardupilot_root()

        script = self.efi_script.text().strip()
        connect = self.efi_connect.text().strip()
        rate = self.efi_rate.value()

        bash_cmd = (
            f"python3 '{script}' "
            f"--connect '{connect}' "
            f"--rate {rate} "
            f"--print-rate 2"
        )

        return ["bash", "-lc", bash_cmd], root

    def start_simulation(self):
        try:
            self.validate_paths()
            self.write_location()
        except Exception as exc:
            QMessageBox.critical(self, "Cannot start simulation", str(exc))
            self.status("Start failed.")
            return

        self.log_box.clear()
        self.status("Starting Omni-Trainer SITL...")

        sitl_cmd, root = self.build_sitl_command()
        self.sitl_runner.start(sitl_cmd, cwd=root)

        if self.start_efi_checkbox.isChecked():
            efi_cmd, efi_root = self.build_efi_command()
            QTimer.singleShot(6000, lambda: self.efi_runner.start(efi_cmd, cwd=efi_root))

        self.status("Simulation started. Open your GCS and connect to the configured output.")

    def stop_simulation(self):
        self.status("Stopping simulation...")

        self.efi_runner.stop()
        self.sitl_runner.stop()

        try:
            subprocess.run(
                [
                    "bash",
                    "-lc",
                    (
                        "pkill -f JSBSim || true; "
                        "pkill -f arduplane || true; "
                        "pkill -f sim_vehicle.py || true; "
                        "pkill -f omni_efi_mavlink_sim.py || true"
                    ),
                ],
                check=False,
            )
        except Exception:
            pass

        self.status("Simulation stopped.")

    def closeEvent(self, event):
        if self.aviation_worker is not None:
            self.aviation_worker.cancel()

        self.stop_simulation()
        event.accept()


def main():
    app = QApplication(sys.argv)
    win = OmniLauncher()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
