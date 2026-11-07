import os
import json
import base64
import hmac
import http.server
from urllib.parse import parse_qs, urlparse

# Fetch database connection string from environment variables
DATABASE_URL = os.environ.get("DATABASE_URL")

# Optional: set APP_PASSWORD in Render to require a password (browser login prompt).
# Username can be anything; only the password is checked.
APP_PASSWORD = os.environ.get("APP_PASSWORD")


def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is missing! Please configure it in your Render settings.")
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


# ==========================================
# 1. DATABASE TABLES MANAGEMENT
# ==========================================
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vehicles (
        id SERIAL PRIMARY KEY,
        nickname TEXT,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        make_model TEXT,
        fuel_capacity REAL
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fuel_logs (
        id SERIAL PRIMARY KEY,
        vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE CASCADE,
        date TEXT NOT NULL,
        odometer REAL NOT NULL,
        fuel_amount REAL NOT NULL,
        total_cost REAL NOT NULL,
        fuel_station TEXT,
        is_full INTEGER
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS service_logs (
        id SERIAL PRIMARY KEY,
        vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE CASCADE,
        service_type TEXT NOT NULL,
        date TEXT NOT NULL,
        odometer REAL NOT NULL,
        cost REAL NOT NULL,
        service_station TEXT,
        notes TEXT,
        next_service_date TEXT
    )""")

    # Migrations for tables created by older versions of this app
    try:
        cursor.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS nickname TEXT;")
        cursor.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS make_model TEXT;")
        cursor.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS fuel_capacity REAL;")
        cursor.execute("ALTER TABLE fuel_logs ADD COLUMN IF NOT EXISTS fuel_station TEXT;")
        cursor.execute("ALTER TABLE service_logs ADD COLUMN IF NOT EXISTS service_station TEXT;")
        cursor.execute("ALTER TABLE service_logs ADD COLUMN IF NOT EXISTS notes TEXT;")
        cursor.execute("ALTER TABLE service_logs ADD COLUMN IF NOT EXISTS next_service_date TEXT;")
        conn.commit()
    except Exception as err:
        print(f"Migration warning: {err}")
        conn.rollback()

    conn.commit()
    cursor.close()
    conn.close()


# Embedded Frontend HTML Dashboard Page.
# NOTE: this is a RAW string (r"""...""") on purpose. In a normal string Python turns \' into ',
# which breaks the JavaScript inside and stops every button from working.
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fuel Service Tracker (India)</title>
    <style>
        :root { --bg: #f4f6f9; --panel: #ffffff; --primary: #059669; --text: #1f2937; --border: #e5e7eb; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; }
        .container { max-width: 1300px; margin: 0 auto; }
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 10px; border-bottom: 2px solid var(--border); }
        select, input, textarea { padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px; font-size: 14px; margin-bottom: 10px; box-sizing: border-box; width: 100%; }
        button { background: var(--primary); color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: 500; font-size: 14px; }
        button.delete { background: #ef4444; }
        button.secondary { background: #4b5563; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px; }
        .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .full-width { grid-column: 1 / -1; }

        .table-container { width: 100%; overflow-x: auto; margin-top: 10px; border: 1px solid var(--border); border-radius: 6px; }
        table { width: 100%; border-collapse: collapse; text-align: left; table-layout: fixed; }
        th, td { padding: 10px; border-bottom: 1px solid var(--border); font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; position: relative; }
        th { background: #f8fafc; font-weight: 600; user-select: none; }

        .resizer { position: absolute; right: 0; top: 0; height: 100%; width: 5px; cursor: col-resize; user-select: none; z-index: 1; }
        .resizer:hover, .resizer.resizing { background: var(--primary); width: 6px; }

        .form-group { display: flex; flex-direction: column; }
        .analytics-strip { display: flex; gap: 15px; margin-bottom: 20px; }
        .stat-card { background: var(--panel); padding: 15px; border-radius: 8px; border: 1px solid var(--border); flex: 1; text-align: center; }
        .stat-card h3 { margin: 0 0 5px 0; font-size: 12px; color: #6b7280; text-transform: uppercase; }
        .stat-card p { margin: 0; font-size: 20px; font-weight: bold; color: var(--primary); }

        .inline-edit { background: transparent; border: none; width: 100%; font-family: inherit; font-size: inherit; color: inherit; padding: 4px; box-sizing: border-box; margin-bottom: 0; }
        .inline-edit:focus { background: #fff; border: 1px solid var(--primary); outline: none; border-radius: 4px; }
        .notes-textarea { white-space: normal; word-break: break-word; resize: vertical; min-height: 32px; font-size: 13px; line-height: 1.4; padding: 4px; border: 1px solid transparent; background: transparent; width: 100%; box-sizing: border-box; margin-bottom: 0; }
        .notes-textarea:focus { background: #fff; border: 1px solid var(--primary); outline: none; border-radius: 4px; }

        /* Next-due status: coloured left stripe + badge */
        td.due-cell { border-left: 5px solid transparent; }
        td.due-green  { border-left-color: #16a34a; background: #f0fdf4; }
        td.due-yellow { border-left-color: #eab308; background: #fefce8; }
        td.due-red    { border-left-color: #dc2626; background: #fef2f2; }
        .due-badge { display: inline-block; font-size: 12px; font-weight: 600; padding: 1px 8px; border-radius: 10px; margin: 0 0 2px 4px; }
        .due-green .due-badge  { color: #166534; background: #dcfce7; }
        .due-yellow .due-badge { color: #854d0e; background: #fef08a; }
        .due-red .due-badge    { color: #991b1b; background: #fecaca; }

        .backup-controls { display: flex; gap: 10px; margin-top: 10px; align-items: center; }
        .global-warning { background: #fffbeb; border: 1px solid #fef3c7; color: #b45309; padding: 12px; border-radius: 6px; margin-bottom: 15px; font-size: 14px; font-weight: 500; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>⛽ Fuel & Service Tracker (₹)</h1>
            <div>
                <label for="vehicleSelect" style="font-weight: 600;">Active Vehicle View: </label>
                <select id="vehicleSelect" onchange="loadVehicleData()" style="width: auto; margin-bottom: 0;">
                    <option value="ALL">✨ ALL Vehicles (Combined Summary)</option>
                </select>
            </div>
        </header>

        <div class="analytics-strip">
            <div class="stat-card"><h3>Total Fuel Cost</h3><p id="statFuel">₹0.00</p></div>
            <div class="stat-card"><h3>Total Service Cost</h3><p id="statService">₹0.00</p></div>
            <div class="stat-card"><h3>Total Cost of Ownership</h3><p id="statTco">₹0.00</p></div>
            <div class="stat-card"><h3>Avg Mileage</h3><p id="statMileage">N/A</p></div>
        </div>

        <div class="grid">
            <div class="panel">
                <h2>🚗 Add New Fleet Vehicle</h2>
                <form id="vehicleForm" onsubmit="addVehicle(event)" class="form-group">
                    <input type="text" id="vNickname" placeholder="Vehicle Nickname (e.g., My Bullet, City SUV)" required>
                    <input type="text" id="vName" placeholder="Official Structural Model Name (e.g., Thunderbird 350)" required>
                    <input type="text" id="vType" placeholder="Type (e.g., Bike, Sedan, SUV)" required>
                    <input type="text" id="vModel" placeholder="Manufacturer Make / Year">
                    <input type="number" min="0" step="0.1" id="vCapacity" placeholder="Tank Fuel Capacity (Liters)">
                    <button type="submit">Save Vehicle Profile</button>
                </form>
                <div style="margin-top:15px;" id="vehicleManagementList"></div>
            </div>

            <div class="panel">
                <h2>➕ Log Entry Sheets</h2>
                <div id="globalViewNotice" class="global-warning">
                    ⚠️ To submit new log entry sheets, select a specific target vehicle profile from the header dropdown above.
                </div>

                <div id="activeFormGroup" style="display:none;">
                    <div style="display:flex; gap:10px; margin-bottom:15px;">
                        <button onclick="toggleForm('fuel')">New Fuel Record</button>
                        <button onclick="toggleForm('service')">New Service Entry</button>
                    </div>

                    <form id="fuelForm" onsubmit="addFuel(event)" class="form-group" style="display:none;">
                        <h3>Log Fuel Fill-up</h3>
                        <input type="date" id="fDate" required>
                        <input type="number" step="any" id="fOdo" placeholder="Odometer Value (km)" required>
                        <input type="number" step="any" id="fAmount" placeholder="Fuel Volume Amount (Liters)" required>
                        <input type="number" step="any" id="fCost" placeholder="Total Cost (₹)" required>
                        <input type="text" id="fStation" placeholder="Fuel Station Name (Optional)">
                        <label style="font-size:14px; margin-bottom:10px;"><input type="checkbox" id="fFull" checked value="1" style="width:auto;"> Full Tank fill?</label>
                        <button type="submit">Save Fuel Log</button>
                    </form>

                    <form id="serviceForm" onsubmit="addService(event)" class="form-group" style="display:none;">
                        <h3>Log Maintenance Work</h3>
                        <input type="text" id="sType" placeholder="Service Action Type (e.g., Engine Oil Change)" required>
                        <input type="date" id="sDate" required>
                        <input type="number" step="any" id="sOdo" placeholder="Odometer Value (km)" required>
                        <input type="number" step="any" id="sCost" placeholder="Total Cost (₹)" required>
                        <input type="text" id="sStation" placeholder="Service Station / Workshop (Optional)">
                        <input type="date" id="sNextDate" placeholder="Next Recommended Service Date Due">
                        <textarea id="sNotes" placeholder="Additional Notes / Detailed Parts List Summary"></textarea>
                        <button type="submit">Save Service Log</button>
                    </form>
                </div>

                <hr style="border:0; border-top:1px solid var(--border); margin:20px 0;">
                <h2>💾 Data Backup Management Tools</h2>
                <div class="backup-controls">
                    <button class="secondary" onclick="exportData()">📤 Export Backup JSON</button>
                    <input type="file" id="importFile" accept=".json" style="display:none;" onchange="importData(event)">
                    <button class="secondary" onclick="document.getElementById('importFile').click()">📥 Import Backup JSON</button>
                </div>
            </div>

            <div class="panel full-width">
                <h2>⛽ Fuel Histories <span style="font-size:12px; font-weight:normal; color:#6b7280;">(Drag column borders to resize. Press Enter inside a cell to save edits)</span></h2>
                <div class="table-container">
                    <table id="fuelTable">
                        <thead>
                            <tr>
                                <th style="width: 150px;">Vehicle Profile<div class="resizer"></div></th>
                                <th style="width: 120px;">Date Logged<div class="resizer"></div></th>
                                <th style="width: 140px;">Odometer (km)<div class="resizer"></div></th>
                                <th style="width: 120px;">Amount (L)<div class="resizer"></div></th>
                                <th style="width: 120px;">Cost (₹)<div class="resizer"></div></th>
                                <th style="width: 180px;">Fuel Station<div class="resizer"></div></th>
                                <th style="width: 100px;">Full Tank?<div class="resizer"></div></th>
                                <th style="width: 100px;">Action</th>
                            </tr>
                        </thead>
                        <tbody id="fuelTableBody"></tbody>
                    </table>
                </div>
            </div>

            <div class="panel full-width">
                <h2>🛠️ Maintenance Log Histories</h2>
                <div class="table-container">
                    <table id="serviceTable">
                        <thead>
                            <tr>
                                <th style="width: 150px;">Vehicle Profile<div class="resizer"></div></th>
                                <th style="width: 120px;">Service Date<div class="resizer"></div></th>
                                <th style="width: 180px;">Service Action Type<div class="resizer"></div></th>
                                <th style="width: 140px;">Odometer (km)<div class="resizer"></div></th>
                                <th style="width: 120px;">Cost (₹)<div class="resizer"></div></th>
                                <th style="width: 200px;">Service Station / Workshop<div class="resizer"></div></th>
                                <th style="width: 190px;">Next Due Date<div class="resizer"></div></th>
                                <th style="width: 300px;">Notes / Item Summaries<div class="resizer"></div></th>
                                <th style="width: 100px;">Action</th>
                            </tr>
                        </thead>
                        <tbody id="serviceTableBody"></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        const API = window.location.origin;
        let vehicleCache = {};
        let vehicleData = {};

        // Escape text before putting it into innerHTML / attribute values
        function esc(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        // Days until a YYYY-MM-DD due date (negative = overdue). Returns null if empty/invalid.
        function daysUntil(dateStr) {
            const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(dateStr || '').trim());
            if (!m) return null;
            const due = new Date(+m[1], +m[2] - 1, +m[3]);
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            return Math.round((due - today) / 86400000);
        }

        // Colour + label for the Next Due Date cell
        //   30+ days = green, 7 to 29 days = yellow, under 7 days (incl. overdue) = red
        function dueStatus(dateStr) {
            const d = daysUntil(dateStr);
            if (d === null) return { cls: '', label: '' };
            let cls = d >= 30 ? 'due-green' : (d >= 7 ? 'due-yellow' : 'due-red');
            let label;
            if (d > 1) label = 'Due in ' + d + ' days';
            else if (d === 1) label = 'Due in 1 day';
            else if (d === 0) label = 'Due today';
            else if (d === -1) label = 'Overdue by 1 day';
            else label = 'Overdue by ' + Math.abs(d) + ' days';
            return { cls: cls, label: label };
        }

        // Fetch wrapper: throws a readable error when the server returns a failure
        async function api(url, options) {
            const res = await fetch(url, options);
            let out = {};
            try { out = await res.json(); } catch (e) {}
            if (!res.ok) {
                throw new Error(out.status || ('HTTP ' + res.status));
            }
            return out;
        }

        window.onload = function() {
            loadVehicles();
            initResizableTables();
        };

        function toggleForm(type) {
            document.getElementById('fuelForm').style.display = type === 'fuel' ? 'flex' : 'none';
            document.getElementById('serviceForm').style.display = type === 'service' ? 'flex' : 'none';
        }

        function initResizableTables() {
            document.querySelectorAll('table').forEach(table => {
                const cols = table.querySelectorAll('th');
                cols.forEach(col => {
                    const resizer = col.querySelector('.resizer');
                    if (!resizer) return;

                    let startX, startWidth;

                    resizer.addEventListener('mousedown', e => {
                        startX = e.pageX;
                        startWidth = col.offsetWidth;
                        resizer.classList.add('resizing');

                        function onMouseMove(moveEvent) {
                            const currentWidth = startWidth + (moveEvent.pageX - startX);
                            if (currentWidth > 50) {
                                col.style.width = currentWidth + 'px';
                            }
                        }

                        function onMouseUp() {
                            resizer.classList.remove('resizing');
                            document.removeEventListener('mousemove', onMouseMove);
                            document.removeEventListener('mouseup', onMouseUp);
                        }

                        document.addEventListener('mousemove', onMouseMove);
                        document.addEventListener('mouseup', onMouseUp);
                        e.preventDefault();
                    });
                });
            });
        }

        async function loadVehicles() {
            try {
                const data = await api(API + '/api/vehicles');
                const select = document.getElementById('vehicleSelect');
                const mgmtDiv = document.getElementById('vehicleManagementList');
                const previous = select.value;

                let optionsHtml = '<option value="ALL">✨ ALL Vehicles (Combined Summary)</option>';
                let mgmtHtml = '<h3>Registered Fleet Profiles:</h3>';
                vehicleCache = {};
                vehicleData = {};

                data.forEach(v => {
                    const nameDisplay = v.nickname || v.name;
                    vehicleCache[v.id] = nameDisplay;
                    vehicleData[v.id] = v;
                    optionsHtml += '<option value="' + v.id + '">' + esc(nameDisplay) + '</option>';
                    mgmtHtml += '<div style="display:flex; justify-content:space-between; margin-bottom:5px; font-size:14px; background:#f8fafc; padding:6px; border-radius:4px;">' +
                        '<span>• <strong>' + esc(nameDisplay) + '</strong> (' + esc(v.type) + ')</span>' +
                        '<span><button class="secondary" style="padding:2px 6px; font-size:11px; margin-right:4px;" onclick="editVehicle(' + v.id + ')">Edit</button>' +
                        '<button class="delete" style="padding:2px 6px; font-size:11px;" onclick="deleteVehicle(' + v.id + ')">Delete Profile</button></span>' +
                    '</div>';
                });

                select.innerHTML = optionsHtml;
                mgmtDiv.innerHTML = mgmtHtml;
                // keep the same vehicle selected after a refresh, if it still exists
                if (previous && (previous === 'ALL' || vehicleData[previous])) {
                    select.value = previous;
                }
                loadVehicleData();
            } catch (err) {
                alert('Could not load vehicles: ' + err.message);
            }
        }

        async function addVehicle(e) {
            e.preventDefault();
            const capacityInput = document.getElementById('vCapacity').value.replace(/[^0-9.]/g, '');
            const body = {
                nickname: document.getElementById('vNickname').value,
                name: document.getElementById('vName').value,
                type: document.getElementById('vType').value,
                make_model: document.getElementById('vModel').value,
                fuel_capacity: parseFloat(capacityInput) || 0
            };
            try {
                await api(API + '/api/vehicles', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
                document.getElementById('vehicleForm').reset();
                loadVehicles();
            } catch (err) {
                alert('Save failed: ' + err.message);
            }
        }

        async function editVehicle(id) {
            const v = vehicleData[id];
            if (!v) return;
            const nickname = prompt("Nickname:", v.nickname || ""); if (nickname === null) return;
            const name = prompt("Model name:", v.name || ""); if (name === null) return;
            const type = prompt("Type:", v.type || ""); if (type === null) return;
            const make_model = prompt("Make / Year:", v.make_model || ""); if (make_model === null) return;
            const cap = prompt("Tank capacity (L):", v.fuel_capacity || 0); if (cap === null) return;
            try {
                await api(API + '/api/vehicles/update', {
                    method: 'PUT', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ id: id, nickname: nickname, name: name, type: type, make_model: make_model, fuel_capacity: parseFloat(cap) || 0 })
                });
                loadVehicles();
            } catch (err) {
                alert('Update failed: ' + err.message);
            }
        }

        async function deleteVehicle(id) {
            if(!confirm("Are you sure you want to drop this vehicle configuration profile alongside all attached historical logs permanently?")) return;
            try {
                await api(API + '/api/vehicles/delete?id=' + id, { method: 'DELETE' });
                loadVehicles();
            } catch (err) {
                alert('Delete failed: ' + err.message);
            }
        }

        function loadVehicleData() {
            const currentView = document.getElementById('vehicleSelect').value;
            const globalNotice = document.getElementById('globalViewNotice');
            const activeFormGroup = document.getElementById('activeFormGroup');

            if (currentView === "ALL") {
                globalNotice.style.display = 'block';
                activeFormGroup.style.display = 'none';
            } else {
                globalNotice.style.display = 'none';
                activeFormGroup.style.display = 'block';
            }

            fetchAnalytics(currentView);
            fetchFuelLogs(currentView);
            fetchServiceLogs(currentView);
        }

        async function fetchAnalytics(vId) {
            try {
                const a = await api(API + '/api/analytics?vehicle_id=' + vId);
                document.getElementById('statFuel').innerText = '₹' + a.total_fuel_cost.toFixed(2);
                document.getElementById('statService').innerText = '₹' + a.total_service_cost.toFixed(2);
                document.getElementById('statTco').innerText = '₹' + a.tco.toFixed(2);
                document.getElementById('statMileage').innerText = a.avg_mileage !== "N/A" ? a.avg_mileage + ' km/L' : "N/A";
            } catch (err) { console.error(err); }
        }

        async function fetchFuelLogs(vId) {
            try {
                const data = await api(API + '/api/fuel?vehicle_id=' + vId);
                const tbody = document.getElementById('fuelTableBody');
                let html = '';

                data.forEach(r => {
                    const vehicleLabel = vehicleCache[r.vehicle_id] || 'ID: ' + r.vehicle_id;
                    html += '<tr>' +
                        '<td><div style="font-weight:600; color:#374151;">' + esc(vehicleLabel) + '</div></td>' +
                        '<td><input class="inline-edit" value="' + esc(r.date) + '" onkeydown="handleEdit(event, \'fuel\', \'date\', ' + r.id + ')"></td>' +
                        '<td><input class="inline-edit" type="number" step="any" value="' + esc(r.odometer) + '" onkeydown="handleEdit(event, \'fuel\', \'odometer\', ' + r.id + ')"></td>' +
                        '<td><input class="inline-edit" type="number" step="any" value="' + esc(r.fuel_amount) + '" onkeydown="handleEdit(event, \'fuel\', \'fuel_amount\', ' + r.id + ')"></td>' +
                        '<td><input class="inline-edit" type="number" step="any" value="' + esc(r.total_cost) + '" onkeydown="handleEdit(event, \'fuel\', \'total_cost\', ' + r.id + ')"></td>' +
                        '<td><input class="inline-edit" value="' + esc(r.fuel_station || '') + '" onkeydown="handleEdit(event, \'fuel\', \'fuel_station\', ' + r.id + ')"></td>' +
                        '<td><input class="inline-edit" type="number" value="' + esc(r.is_full) + '" onkeydown="handleEdit(event, \'fuel\', \'is_full\', ' + r.id + ')"></td>' +
                        '<td><button class="delete" style="padding:4px 8px; font-size:12px;" onclick="deleteRow(\'fuel\', ' + r.id + ')">Delete</button></td>' +
                    '</tr>';
                });
                tbody.innerHTML = html;
            } catch (err) { console.error(err); }
        }

        async function fetchServiceLogs(vId) {
            try {
                const data = await api(API + '/api/service?vehicle_id=' + vId);
                const tbody = document.getElementById('serviceTableBody');
                let html = '';

                data.forEach(r => {
                    const vehicleLabel = vehicleCache[r.vehicle_id] || 'ID: ' + r.vehicle_id;
                    const due = dueStatus(r.next_service_date);
                    const dueBadge = due.label ? '<span class="due-badge">' + esc(due.label) + '</span>' : '';
                    html += '<tr>' +
                        '<td><div style="font-weight:600; color:#374151;">' + esc(vehicleLabel) + '</div></td>' +
                        '<td><input class="inline-edit" value="' + esc(r.date) + '" onkeydown="handleEdit(event, \'service\', \'date\', ' + r.id + ')"></td>' +
                        '<td><input class="inline-edit" value="' + esc(r.service_type) + '" onkeydown="handleEdit(event, \'service\', \'service_type\', ' + r.id + ')"></td>' +
                        '<td><input class="inline-edit" type="number" step="any" value="' + esc(r.odometer) + '" onkeydown="handleEdit(event, \'service\', \'odometer\', ' + r.id + ')"></td>' +
                        '<td><input class="inline-edit" type="number" step="any" value="' + esc(r.cost) + '" onkeydown="handleEdit(event, \'service\', \'cost\', ' + r.id + ')"></td>' +
                        '<td><input class="inline-edit" value="' + esc(r.service_station || '') + '" onkeydown="handleEdit(event, \'service\', \'service_station\', ' + r.id + ')"></td>' +
                        '<td class="due-cell ' + due.cls + '"><input class="inline-edit" value="' + esc(r.next_service_date || '') + '" onkeydown="handleEdit(event, \'service\', \'next_service_date\', ' + r.id + ')">' + dueBadge + '</td>' +
                        '<td><textarea class="notes-textarea" onblur="handleTextareaBlur(this, ' + r.id + ')" onkeydown="handleTextareaKey(event, this, ' + r.id + ')">' + esc(r.notes || '') + '</textarea></td>' +
                        '<td><button class="delete" style="padding:4px 8px; font-size:12px;" onclick="deleteRow(\'service\', ' + r.id + ')">Delete</button></td>' +
                    '</tr>';
                });
                tbody.innerHTML = html;
            } catch (err) { console.error(err); }
        }

        async function addFuel(e) {
            e.preventDefault();
            const currentView = document.getElementById('vehicleSelect').value;
            if(!currentView || currentView === "ALL") return alert("Focus a distinct vehicle profile first!");

            const body = {
                vehicle_id: parseInt(currentView),
                date: document.getElementById('fDate').value,
                odometer: parseFloat(document.getElementById('fOdo').value),
                fuel_amount: parseFloat(document.getElementById('fAmount').value),
                total_cost: parseFloat(document.getElementById('fCost').value),
                fuel_station: document.getElementById('fStation').value,
                is_full: document.getElementById('fFull').checked ? 1 : 0
            };
            try {
                await api(API + '/api/fuel', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
                document.getElementById('fuelForm').reset();
                loadVehicleData();
            } catch (err) {
                alert('Save failed: ' + err.message);
            }
        }

        async function addService(e) {
            e.preventDefault();
            const currentView = document.getElementById('vehicleSelect').value;
            if(!currentView || currentView === "ALL") return alert("Focus a distinct vehicle profile first!");

            const body = {
                vehicle_id: parseInt(currentView),
                service_type: document.getElementById('sType').value,
                date: document.getElementById('sDate').value,
                odometer: parseFloat(document.getElementById('sOdo').value),
                cost: parseFloat(document.getElementById('sCost').value),
                service_station: document.getElementById('sStation').value,
                notes: document.getElementById('sNotes').value,
                next_service_date: document.getElementById('sNextDate').value
            };
            try {
                await api(API + '/api/service', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
                document.getElementById('serviceForm').reset();
                loadVehicleData();
            } catch (err) {
                alert('Save failed: ' + err.message);
            }
        }

        async function handleEdit(e, table, field, id) {
            if (e.key === 'Enter') {
                let val = e.target.value;
                if(['odometer', 'fuel_amount', 'total_cost', 'cost', 'is_full'].includes(field)) {
                    val = parseFloat(val) || 0;
                }
                try {
                    await submitUpdate(table, field, id, val);
                    e.target.blur();
                    loadVehicleData();
                } catch (err) {
                    alert('Update failed: ' + err.message);
                }
            }
        }

        async function handleTextareaBlur(el, id) {
            try { await submitUpdate('service', 'notes', id, el.value); }
            catch (err) { alert('Update failed: ' + err.message); }
        }

        async function handleTextareaKey(e, el, id) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                try {
                    await submitUpdate('service', 'notes', id, el.value);
                    el.blur();
                    loadVehicleData();
                } catch (err) {
                    alert('Update failed: ' + err.message);
                }
            }
        }

        async function submitUpdate(table, field, id, value) {
            const body = { table: table, field: field, id: id, value: value };
            return api(API + '/api/update', { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
        }

        async function deleteRow(table, id) {
            if(!confirm("Erase this configuration row metric record permanently?")) return;
            try {
                await api(API + '/api/delete?table=' + table + '&id=' + id, { method: 'DELETE' });
                loadVehicleData();
            } catch (err) {
                alert('Delete failed: ' + err.message);
            }
        }

        async function exportData() {
            try {
                const data = await api(API + '/api/export');
                const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'fuel_tracker_backup_' + new Date().toISOString().split('T')[0] + '.json';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            } catch (err) {
                alert('Export failed: ' + err.message);
            }
        }

        async function importData(e) {
            const file = e.target.files[0];
            if (!file) return;
            if (!confirm("Importing REPLACES all existing data with the backup file. Continue?")) { e.target.value = ''; return; }
            const reader = new FileReader();
            reader.onload = async function(evt) {
                try {
                    const parsed = JSON.parse(evt.target.result);
                    const resData = await api(API + '/api/import', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(parsed)
                    });
                    alert('Import finished! Process Log State: ' + resData.status);
                    loadVehicles();
                } catch(err) {
                    alert("Import failed: " + err.message);
                }
                e.target.value = '';
            };
            reader.readAsText(file);
        }
    </script>
</body>
</html>
"""


# ==========================================
# 2. REST API REQUEST ENDPOINT HANDLER
# ==========================================
class BackendAPIHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"[{self.date_time_string()}] " + (format % args))

    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _send_json(self, payload, status=200):
        self._set_headers(status)
        self.wfile.write(json.dumps(payload).encode('utf-8'))

    def _read_json(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode('utf-8'))

    def _check_auth(self):
        """Optional password protection (enabled when APP_PASSWORD is set)."""
        if not APP_PASSWORD:
            return True
        header = self.headers.get('Authorization', '')
        if header.startswith('Basic '):
            try:
                decoded = base64.b64decode(header[6:]).decode('utf-8')
                supplied = decoded.split(':', 1)[1] if ':' in decoded else decoded
                if hmac.compare_digest(supplied.encode('utf-8'), APP_PASSWORD.encode('utf-8')):
                    return True
            except Exception:
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Fuel Tracker"')
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "Authentication required"}).encode('utf-8'))
        return False

    def do_OPTIONS(self):
        self._set_headers(200)

    # ---------------------------- GET ----------------------------
    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)

        if path == "/health":
            self._send_json({"status": "API Engine Active"})
            return

        if not self._check_auth():
            return

        if path == "/":
            self._set_headers(200, content_type="text/html; charset=utf-8")
            self.wfile.write(INDEX_HTML.encode('utf-8'))
            return

        if not path.startswith("/api/"):
            self._send_json({"status": "not found"}, 404)
            return

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            if path == "/api/vehicles":
                cursor.execute("SELECT id, nickname, name, type, make_model, fuel_capacity FROM vehicles ORDER BY id ASC")
                data = []
                for v_id, v_nick, v_name, v_type, v_model, v_cap in cursor.fetchall():
                    data.append({
                        "id": v_id, "nickname": v_nick, "name": v_name,
                        "type": v_type, "make_model": v_model, "fuel_capacity": v_cap
                    })
                self._send_json(data)

            elif path == "/api/fuel":
                v_id_str = query.get('vehicle_id', ["ALL"])[0]
                if v_id_str == "ALL":
                    cursor.execute("SELECT id, vehicle_id, date, odometer, fuel_amount, total_cost, fuel_station, is_full FROM fuel_logs ORDER BY date DESC, odometer DESC")
                else:
                    cursor.execute("SELECT id, vehicle_id, date, odometer, fuel_amount, total_cost, fuel_station, is_full FROM fuel_logs WHERE vehicle_id = %s ORDER BY date DESC, odometer DESC", (int(v_id_str),))
                data = []
                for f_id, f_v_id, f_date, f_odo, f_amt, f_cost, f_station, f_full in cursor.fetchall():
                    data.append({
                        "id": f_id, "vehicle_id": f_v_id, "date": f_date, "odometer": f_odo,
                        "fuel_amount": f_amt, "total_cost": f_cost, "fuel_station": f_station, "is_full": f_full
                    })
                self._send_json(data)

            elif path == "/api/service":
                v_id_str = query.get('vehicle_id', ["ALL"])[0]
                if v_id_str == "ALL":
                    cursor.execute("SELECT id, vehicle_id, date, next_service_date, service_type, odometer, cost, service_station, notes FROM service_logs ORDER BY date DESC, odometer DESC")
                else:
                    cursor.execute("SELECT id, vehicle_id, date, next_service_date, service_type, odometer, cost, service_station, notes FROM service_logs WHERE vehicle_id = %s ORDER BY date DESC, odometer DESC", (int(v_id_str),))
                data = []
                for s_id, s_v_id, s_date, s_next, s_type, s_odo, s_cost, s_station, s_notes in cursor.fetchall():
                    data.append({
                        "id": s_id, "vehicle_id": s_v_id, "date": s_date, "next_service_date": s_next,
                        "service_type": s_type, "odometer": s_odo, "cost": s_cost,
                        "service_station": s_station, "notes": s_notes
                    })
                self._send_json(data)

            elif path == "/api/analytics":
                v_id_str = query.get('vehicle_id', ["ALL"])[0]

                if v_id_str == "ALL":
                    cursor.execute("SELECT COALESCE(SUM(total_cost), 0) FROM fuel_logs")
                    total_fuel_cost = float(cursor.fetchone()[0])
                    cursor.execute("SELECT COALESCE(SUM(cost), 0) FROM service_logs")
                    total_service_cost = float(cursor.fetchone()[0])
                    avg_mileage = "N/A"
                else:
                    v_id = int(v_id_str)
                    cursor.execute("SELECT COALESCE(SUM(total_cost), 0) FROM fuel_logs WHERE vehicle_id = %s", (v_id,))
                    total_fuel_cost = float(cursor.fetchone()[0])
                    cursor.execute("SELECT COALESCE(SUM(cost), 0) FROM service_logs WHERE vehicle_id = %s", (v_id,))
                    total_service_cost = float(cursor.fetchone()[0])

                    cursor.execute("SELECT odometer, fuel_amount, is_full FROM fuel_logs WHERE vehicle_id = %s ORDER BY odometer ASC", (v_id,))
                    logs = cursor.fetchall()
                    avg_mileage = "N/A"
                    if len(logs) >= 2:
                        total_distance = 0.0
                        total_consumed_fuel = 0.0
                        last_full_odo = None
                        pending_fuel = 0.0

                        for l_odo, l_fuel, l_full in logs:
                            if l_full == 1:
                                if last_full_odo is not None:
                                    total_distance += (l_odo - last_full_odo)
                                    total_consumed_fuel += (pending_fuel + l_fuel)
                                    pending_fuel = 0.0
                                last_full_odo = l_odo
                            else:
                                if last_full_odo is not None:
                                    pending_fuel += l_fuel

                        if total_consumed_fuel > 0:
                            avg_mileage = round(total_distance / total_consumed_fuel, 2)

                self._send_json({
                    "total_fuel_cost": total_fuel_cost,
                    "total_service_cost": total_service_cost,
                    "tco": total_fuel_cost + total_service_cost,
                    "avg_mileage": avg_mileage
                })

            elif path == "/api/export":
                cursor.execute("SELECT id, nickname, name, type, make_model, fuel_capacity FROM vehicles")
                vehicles = []
                for v_id, v_nick, v_name, v_type, v_model, v_cap in cursor.fetchall():
                    vehicles.append({"id": v_id, "nickname": v_nick, "name": v_name, "type": v_type, "make_model": v_model, "fuel_capacity": v_cap})

                cursor.execute("SELECT id, vehicle_id, date, odometer, fuel_amount, total_cost, fuel_station, is_full FROM fuel_logs")
                fuel = []
                for f_id, f_v_id, f_date, f_odo, f_amt, f_cost, f_station, f_full in cursor.fetchall():
                    fuel.append({"id": f_id, "vehicle_id": f_v_id, "date": f_date, "odometer": f_odo, "fuel_amount": f_amt, "total_cost": f_cost, "fuel_station": f_station, "is_full": f_full})

                cursor.execute("SELECT id, vehicle_id, date, next_service_date, service_type, odometer, cost, service_station, notes FROM service_logs")
                service = []
                for s_id, s_v_id, s_date, s_next, s_type, s_odo, s_cost, s_station, s_notes in cursor.fetchall():
                    service.append({"id": s_id, "vehicle_id": s_v_id, "date": s_date, "next_service_date": s_next, "service_type": s_type, "odometer": s_odo, "cost": s_cost, "service_station": s_station, "notes": s_notes})

                self._send_json({"vehicles": vehicles, "fuel_logs": fuel, "service_logs": service})

            else:
                self._send_json({"status": "not found"}, 404)

        except Exception as err:
            if conn:
                conn.rollback()
            print(f"❌ DATABASE ERROR ENCOUNTERED (GET {path}): {err}")
            self._send_json({"status": f"Failure: {err}"}, 500)
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    # ---------------------------- POST ----------------------------
    def do_POST(self):
        if not self._check_auth():
            return
        path = urlparse(self.path).path

        try:
            data = self._read_json()
        except Exception:
            self._send_json({"status": "Invalid JSON body"}, 400)
            return

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            if path == "/api/vehicles":
                nickname = (data.get('nickname') or '').strip() or None
                name = (data.get('name') or '').strip()
                v_type = (data.get('type') or '').strip()
                make_model = (data.get('make_model') or '').strip() or None

                try:
                    fuel_capacity = float(data.get('fuel_capacity', 0))
                except (ValueError, TypeError):
                    fuel_capacity = 0.0

                if not name or not v_type:
                    self._send_json({"status": "Failure: Name and Type fields are strictly required."}, 400)
                    return

                cursor.execute("""
                    INSERT INTO vehicles (nickname, name, type, make_model, fuel_capacity)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id
                """, (nickname, name, v_type, make_model, fuel_capacity))

                row = cursor.fetchone()
                new_id = int(row[0]) if row else None
                if new_id is None:
                    raise ValueError("Database failed to return a valid vehicle ID mapping.")

                conn.commit()
                self._send_json({"status": "created", "vehicle_id": new_id}, 201)

            elif path == "/api/fuel":
                cursor.execute("""
                    INSERT INTO fuel_logs (vehicle_id, date, odometer, fuel_amount, total_cost, fuel_station, is_full)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (data['vehicle_id'], data['date'], data['odometer'], data['fuel_amount'],
                      data['total_cost'], data.get('fuel_station') or None, data.get('is_full', 1)))
                conn.commit()
                self._send_json({"status": "success"}, 201)

            elif path == "/api/service":
                cursor.execute("""
                    INSERT INTO service_logs (vehicle_id, service_type, date, odometer, cost, service_station, notes, next_service_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (data['vehicle_id'], data['service_type'], data['date'], data['odometer'], data['cost'],
                      data.get('service_station') or None, data.get('notes'), data.get('next_service_date') or None))
                conn.commit()
                self._send_json({"status": "success"}, 201)

            elif path == "/api/import":
                cursor.execute("TRUNCATE TABLE vehicles, fuel_logs, service_logs RESTART IDENTITY CASCADE;")
                v_map = {}
                for v in data.get('vehicles', []):
                    cursor.execute("""
                        INSERT INTO vehicles (nickname, name, type, make_model, fuel_capacity)
                        VALUES (%s, %s, %s, %s, %s) RETURNING id
                    """, (v.get('nickname'), v['name'], v['type'], v.get('make_model'), v.get('fuel_capacity')))
                    v_map[v['id']] = int(cursor.fetchone()[0])

                for f in data.get('fuel_logs', []):
                    if f['vehicle_id'] in v_map:
                        cursor.execute("""
                            INSERT INTO fuel_logs (vehicle_id, date, odometer, fuel_amount, total_cost, fuel_station, is_full)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (v_map[f['vehicle_id']], f['date'], f['odometer'], f['fuel_amount'],
                              f['total_cost'], f.get('fuel_station'), f.get('is_full', 1)))

                for s in data.get('service_logs', []):
                    if s['vehicle_id'] in v_map:
                        cursor.execute("""
                            INSERT INTO service_logs (vehicle_id, service_type, date, odometer, cost, service_station, notes, next_service_date)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (v_map[s['vehicle_id']], s['service_type'], s['date'], s['odometer'], s['cost'],
                              s.get('service_station'), s.get('notes'), s.get('next_service_date')))

                conn.commit()
                self._send_json({"status": "Success"})

            else:
                self._send_json({"status": "not found"}, 404)

        except Exception as err:
            if conn:
                conn.rollback()
            print(f"❌ DATABASE ERROR ENCOUNTERED (POST {path}): {err}")
            self._send_json({"status": f"Failure: {err}"}, 500)
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    # ---------------------------- PUT ----------------------------
    def do_PUT(self):
        if not self._check_auth():
            return
        path = urlparse(self.path).path

        try:
            data = self._read_json()
        except Exception:
            self._send_json({"status": "Invalid JSON body"}, 400)
            return

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            if path == "/api/vehicles/update":
                name = (data.get('name') or '').strip()
                v_type = (data.get('type') or '').strip()
                if not name or not v_type:
                    self._send_json({"status": "Name and Type are required."}, 400)
                    return
                try:
                    cap = float(data.get('fuel_capacity', 0))
                except (ValueError, TypeError):
                    cap = 0.0
                cursor.execute(
                    "UPDATE vehicles SET nickname=%s, name=%s, type=%s, make_model=%s, fuel_capacity=%s WHERE id=%s",
                    ((data.get('nickname') or '').strip() or None, name, v_type,
                     (data.get('make_model') or '').strip() or None, cap, int(data['id'])))
                conn.commit()
                self._send_json({"status": "updated"})

            elif path == "/api/update":
                table_name = "fuel_logs" if data['table'] == "fuel" else "service_logs"
                allowed = ["date", "odometer", "fuel_amount", "total_cost", "is_full", "fuel_station",
                           "service_type", "cost", "service_station", "notes", "next_service_date"]
                if data['field'] not in allowed:
                    self._send_json({"status": "field not allowed"}, 400)
                    return
                # field name is whitelisted above, so the f-string is safe here
                cursor.execute(f"UPDATE {table_name} SET {data['field']} = %s WHERE id = %s",
                               (data['value'], data['id']))
                conn.commit()
                self._send_json({"status": "updated"})

            else:
                self._send_json({"status": "not found"}, 404)

        except Exception as err:
            if conn:
                conn.rollback()
            print(f"❌ DATABASE ERROR (PUT {path}): {err}")
            self._send_json({"status": f"Failure: {err}"}, 500)
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    # ---------------------------- DELETE ----------------------------
    def do_DELETE(self):
        if not self._check_auth():
            return
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            if path == "/api/vehicles/delete":
                v_id = int(query.get('id')[0])
                cursor.execute("DELETE FROM vehicles WHERE id = %s", (v_id,))
                conn.commit()
                self._send_json({"status": "deleted"})

            elif path == "/api/delete":
                table = query.get('table')[0]
                row_id = int(query.get('id')[0])
                table_name = "fuel_logs" if table == "fuel" else "service_logs"
                cursor.execute(f"DELETE FROM {table_name} WHERE id = %s", (row_id,))
                conn.commit()
                self._send_json({"status": "deleted"})

            else:
                self._send_json({"status": "not found"}, 404)

        except Exception as err:
            if conn:
                conn.rollback()
            print(f"❌ DATABASE ERROR (DELETE {path}): {err}")
            self._send_json({"status": f"Failure: {err}"}, 500)
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8000))
    server_address = ('', port)
    httpd = http.server.ThreadingHTTPServer(server_address, BackendAPIHandler)
    print(f"🚀 Live API Engine firing up on port {port}...")
    httpd.serve_forever()
