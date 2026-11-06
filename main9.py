import os
import json
import http.server
from urllib.parse import parse_qs, urlparse

# Fetch database connection string from environment variables
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is missing! Please configure it in your Render settings.")
    import psycopg2
    return psycopg2.connect(DATABASE_URL)

# ==========================================
# 1. DATABASE TABLES MANAGEMENT & MIGRATION
# ==========================================
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create Vehicles structural mapping table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vehicles (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        make_model TEXT,
        fuel_capacity REAL
    )""")
    
    # Run Column Migrations safely
    try:
        cursor.execute("ALTER TABLE vehicles ADD COLUMN nickname TEXT;")
    except Exception:
        conn.rollback()
        
    # Create Fuel Fillups table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fuel_logs (
        id SERIAL PRIMARY KEY,
        vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE CASCADE,
        date TEXT NOT NULL,
        odometer REAL NOT NULL,
        fuel_amount REAL NOT NULL,
        total_cost REAL NOT NULL,
        is_full INTEGER
    )""")
    
    try:
        cursor.execute("ALTER TABLE fuel_logs ADD COLUMN fuel_station TEXT;")
    except Exception:
        conn.rollback()
        
    # Create Maintenance Logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS service_logs (
        id SERIAL PRIMARY KEY,
        vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE CASCADE,
        service_type TEXT NOT NULL,
        date TEXT NOT NULL,
        odometer REAL NOT NULL,
        cost REAL NOT NULL,
        notes TEXT,
        next_service_date TEXT
    )""")
    
    try:
        cursor.execute("ALTER TABLE service_logs ADD COLUMN service_station TEXT;")
    except Exception:
        conn.rollback()
        
    conn.commit()
    cursor.close()
    conn.close()

# Embedded Frontend HTML Dashboard Page
INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fuel Service Tracker (India)</title>
    <style>
        :root { --bg: #f4f6f9; --panel: #ffffff; --primary: #059669; --text: #1f2937; --border: #e5e7eb; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 10px; border-bottom: 2px solid var(--border); }
        select, input, textarea { padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px; font-size: 14px; margin-bottom: 10px; box-sizing: border-box; }
        button { background: var(--primary); color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: 500; }
        button.delete { background: #ef4444; }
        button.secondary { background: #4b5563; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px; }
        .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .full-width { grid-column: 1 / -1; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; text-align: left; }
        th, td { padding: 10px; border-bottom: 1px solid var(--border); font-size: 14px; vertical-align: top; }
        th { background: #f8fafc; font-weight: 600; }
        .form-group { display: flex; flex-direction: column; }
        .analytics-strip { display: flex; gap: 15px; margin-bottom: 20px; }
        .stat-card { background: var(--panel); padding: 15px; border-radius: 8px; border: 1px solid var(--border); flex: 1; text-align: center; }
        .stat-card h3 { margin: 0 0 5px 0; font-size: 12px; color: #6b7280; text-transform: uppercase; }
        .stat-card p { margin: 0; font-size: 20px; font-weight: bold; color: var(--primary); }
        .inline-edit { background: transparent; border: none; width: 100%; font-family: inherit; font-size: inherit; color: inherit; padding: 4px; }
        .inline-edit:focus { background: #fff; border: 1px solid var(--primary); outline: none; border-radius: 4px; }
        .notes-textarea { background: transparent; border: none; width: 100%; font-family: inherit; font-size: inherit; color: inherit; padding: 4px; resize: vertical; min-height: 40px; height: auto; }
        .notes-textarea:focus { background: #fff; border: 1px solid var(--primary); outline: none; border-radius: 4px; }
        .backup-controls { display: flex; gap: 10px; margin-top: 10px; align-items: center; }
        .alert-banner { background: #fef3c7; color: #92400e; padding: 12px; border-radius: 6px; margin-bottom: 15px; font-size: 14px; border: 1px solid #fde68a; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>⛽ Fuel & Service Tracker (₹)</h1>
            <div>
                <label for="vehicleSelect">Active Vehicle: </label>
                <select id="vehicleSelect" onchange="loadVehicleData()">
                    <option value="ALL">All Vehicles (Fleet View)</option>
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
            <!-- Vehicle Management Panel -->
            <div class="panel">
                <h2>🚗 Add New Vehicle</h2>
                <form id="vehicleForm" onsubmit="addVehicle(event)" class="form-group">
                    <input type="text" id="vNickname" placeholder="Vehicle Nickname (e.g., My Bullet, City Car)" required>
                    <input type="text" id="vName" placeholder="Official Name (e.g., Thunderbird 350)" required>
                    <input type="text" id="vType" placeholder="Type (e.g., Bike, Sedan, SUV)" required>
                    <input type="text" id="vModel" placeholder="Make / Model">
                    <input type="number" step="any" id="vCapacity" placeholder="Tank Capacity (Liters)">
                    <button type="submit">Save Vehicle</button>
                </form>
                <div style="margin-top:15px;" id="vehicleManagementList"></div>
            </div>

            <!-- Form Panels & Tools -->
            <div class="panel">
                <h2>➕ Log Entry Forms</h2>
                <div id="formViewNotice" class="alert-banner">
                    Please select an individual vehicle to log new fuel or service records.
                </div>
                <div id="formControls" style="display:none;">
                    <div style="display:flex; gap:10px; margin-bottom:15px;">
                        <button onclick="toggleForm('fuel')">New Fuel Record</button>
                        <button onclick="toggleForm('service')">New Service Entry</button>
                    </div>
                    
                    <form id="fuelForm" onsubmit="addFuel(event)" class="form-group" style="display:none;">
                        <h3>Log Fuel Fill-up</h3>
                        <input type="date" id="fDate" required>
                        <input type="number" step="any" id="fOdo" placeholder="Odometer Value (km)" required>
                        <input type="number" step="any" id="fAmount" placeholder="Fuel Amount (Liters)" required>
                        <input type="number" step="any" id="fCost" placeholder="Total Cost (₹)" required>
                        <input type="text" id="fStation" placeholder="Fuel Station (Optional)">
                        <label><input type="checkbox" id="fFull" checked value="1"> Full Tank?</label>
                        <button type="submit">Save Fuel Log</button>
                    </form>

                    <form id="serviceForm" onsubmit="addService(event)" class="form-group" style="display:none;">
                        <h3>Log Maintenance Work</h3>
                        <input type="text" id="sType" placeholder="Service Type (e.g., Oil Change, Paid Service)" required>
                        <input type="date" id="sDate" required>
                        <input type="number" step="any" id="sOdo" placeholder="Odometer Value (km)" required>
                        <input type="number" step="any" id="sCost" placeholder="Total Cost (₹)" required>
                        <input type="text" id="sStation" placeholder="Service Station / Workshop (Optional)">
                        <input type="date" id="sNextDate" placeholder="Next Service Due Date">
                        <textarea id="sNotes" placeholder="Additional Notes / Details (Human readable)"></textarea>
                        <button type="submit">Save Service Log</button>
                    </form>
                </div>

                <hr style="border:0; border-top:1px solid var(--border); margin:20px 0;">
                <h2>💾 Data Backup Tools</h2>
                <div class="backup-controls">
                    <button class="secondary" onclick="exportData()">📤 Export Backup JSON</button>
                    <input type="file" id="importFile" accept=".json" style="display:none;" onchange="importData(event)">
                    <button class="secondary" onclick="document.getElementById('importFile').click()">📥 Import Backup JSON</button>
                </div>
            </div>

            <!-- Data Tables -->
            <div class="panel full-width">
                <h2>⛽ Fuel Histories <span style="font-size:12px; font-weight:normal; color:#6b7280;">(Click cell to edit inline, press Enter to save)</span></h2>
                <table>
                    <thead><tr><th>Vehicle</th><th>Date</th><th>Odometer (km)</th><th>Amount (L)</th><th>Cost (₹)</th><th>Fuel Station</th><th>Full?</th><th>Action</th></tr></thead>
                    <tbody id="fuelTableBody"></tbody>
                </table>
            </div>

            <div class="panel full-width">
                <h2>🛠️ Maintenance Log Histories <span style="font-size:12px; font-weight:normal; color:#6b7280;">(Human readable multiline editable Notes section)</span></h2>
                <table>
                    <thead><tr><th>Vehicle</th><th>Date</th><th>Service Type</th><th>Odometer (km)</th><th>Cost (₹)</th><th>Service Station</th><th>Next Due</th><th style="width: 30%;">Notes</th><th>Action</th></tr></thead>
                    <tbody id="serviceTableBody"></tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        const API = window.location.origin;
        let currentVehicleId = 'ALL';

        window.onload = function() { loadVehicles(); };

        function toggleForm(type) {
            document.getElementById('fuelForm').style.display = type === 'fuel' ? 'flex' : 'none';
            document.getElementById('serviceForm').style.display = type === 'service' ? 'flex' : 'none';
        }

        async function loadVehicles() {
            const res = await fetch(`${API}/api/vehicles`);
            const data = await res.json();
            const select = document.getElementById('vehicleSelect');
            const mgmtDiv = document.getElementById('vehicleManagementList');
            
            select.innerHTML = '<option value="ALL">All Vehicles (Fleet View)</option>';
            mgmtDiv.innerHTML = '<h3>Registered Fleet:</h3>';
            
            data.forEach(v => {
                const displayName = v.nickname || v.name;
                select.innerHTML += `<option value="${v.id}">${displayName}</option>`;
                mgmtDiv.innerHTML += `<div style="display:flex; justify-content:space-between; margin-bottom:5px; font-size:14px;">
                    <span>• ${displayName}</span>
                    <button class="delete" style="padding:2px 6px; font-size:11px;" onclick="deleteVehicle(${v.id})">Delete</button>
                </div>`;
            });
            select.value = currentVehicleId;
            loadVehicleData();
        }

        async function addVehicle(e) {
            e.preventDefault();
            const body = {
                nickname: document.getElementById('vNickname').value,
                name: document.getElementById('vName').value,
                type: document.getElementById('vType').value,
                make_model: document.getElementById('vModel').value,
                fuel_capacity: parseFloat(document.getElementById('vCapacity').value) || 0
            };
            await fetch(`${API}/api/vehicles`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
            document.getElementById('vehicleForm').reset();
            loadVehicles();
        }

        async function deleteVehicle(id) {
            if(!confirm("Are you sure you want to remove this vehicle and all related fuel/service logs?")) return;
            await fetch(`${API}/api/vehicles/delete?id=${id}`, { method: 'DELETE' });
            if(currentVehicleId == id) currentVehicleId = 'ALL';
            loadVehicles();
        }

        function loadVehicleData() {
            currentVehicleId = document.getElementById('vehicleSelect').value;
            
            if(currentVehicleId === 'ALL') {
                document.getElementById('formViewNotice').style.display = 'block';
                document.getElementById('formControls').style.display = 'none';
            } else {
                document.getElementById('formViewNotice').style.display = 'none';
                document.getElementById('formControls').style.display = 'block';
            }
            
            fetchAnalytics();
            fetchFuelLogs();
            fetchServiceLogs();
        }

        async function fetchAnalytics() {
            const res = await fetch(`${API}/api/analytics?vehicle_id=${currentVehicleId}`);
            const a = await res.json();
            document.getElementById('statFuel').innerText = `₹${a.total_fuel_cost.toFixed(2)}`;
            document.getElementById('statService').innerText = `₹${a.total_service_cost.toFixed(2)}`;
            document.getElementById('statTco').innerText = `₹${a.tco.toFixed(2)}`;
            document.getElementById('statMileage').innerText = a.avg_mileage !== "N/A" ? `${a.avg_mileage} km/L` : "N/A";
        }

        async function fetchFuelLogs() {
            const res = await fetch(`${API}/api/fuel?vehicle_id=${currentVehicleId}`);
            const data = await res.json();
            const tbody = document.getElementById('fuelTableBody');
            tbody.innerHTML = '';
            data.forEach(r => {
                tbody.innerHTML += `<tr>
                    <td style="font-weight:600;color:#4b5563;">${r.vehicle_nickname || 'N/A'}</td>
                    <td><input class="inline-edit" value="${r.date}" onkeydown="handleEdit(event, 'fuel', 'date', ${r.id})"></td>
                    <td><input class="inline-edit" type="number" step="any" value="${r.odometer}" onkeydown="handleEdit(event, 'fuel', 'odometer', ${r.id})"></td>
                    <td><input class="inline-edit" type="number" step="any" value="${r.fuel_amount}" onkeydown="handleEdit(event, 'fuel', 'fuel_amount', ${r.id})"></td>
                    <td><input class="inline-edit" type="number" step="any" value="${r.total_cost}" onkeydown="handleEdit(event, 'fuel', 'total_cost', ${r.id})"></td>
                    <td><input class="inline-edit" value="${r.fuel_station || ''}" onkeydown="handleEdit(event, 'fuel', 'fuel_station', ${r.id})"></td>
                    <td><input class="inline-edit" type="number" value="${r.is_full}" onkeydown="handleEdit(event, 'fuel', 'is_full', ${r.id})"></td>
                    <td><button class="delete" style="padding:4px 8px; font-size:12px;" onclick="deleteRow('fuel', ${r.id})">Delete</button></td>
                </tr>`;
            });
        }

        async function fetchServiceLogs() {
            const res = await fetch(`${API}/api/service?vehicle_id=${currentVehicleId}`);
            const data = await res.json();
            const tbody = document.getElementById('serviceTableBody');
            tbody.innerHTML = '';
            data.forEach(r => {
                tbody.innerHTML += `<tr>
                    <td style="font-weight:600;color:#4b5563;">${r.vehicle_nickname || 'N/A'}</td>
                    <td><input class="inline-edit" value="${r.date}" onkeydown="handleEdit(event, 'service', 'date', ${r.id})"></td>
                    <td><input class="inline-edit" value="${r.service_type}" onkeydown="handleEdit(event, 'service', 'service_type', ${r.id})"></td>
                    <td><input class="inline-edit" type="number" step="any" value="${r.odometer}" onkeydown="handleEdit(event, 'service', 'odometer', ${r.id})"></td>
                    <td><input class="inline-edit" type="number" step="any" value="${r.cost}" onkeydown="handleEdit(event, 'service', 'cost', ${r.id})"></td>
                    <td><input class="inline-edit" value="${r.service_station || ''}" onkeydown="handleEdit(event, 'service', 'service_station', ${r.id})"></td>
                    <td><input class="inline-edit" value="${r.next_service_date || ''}" onkeydown="handleEdit(event, 'service', 'next_service_date', ${r.id})"></td>
                    <td>
                        <textarea class="notes-textarea" onblur="handleBlurEdit('service', 'notes', ${r.id}, this)">${r.notes || ''}</textarea>
                    </td>
                    <td><button class="delete" style="padding:4px 8px; font-size:12px;" onclick="deleteRow('service', ${r.id})">Delete</button></td>
                </tr>`;
            });
        }

        async function addFuel(e) {
            e.preventDefault();
            if(currentVehicleId === 'ALL') return alert("Select a specific vehicle first!");
            const body = {
                vehicle_id: parseInt(currentVehicleId),
                date: document.getElementById('fDate').value,
                odometer: parseFloat(document.getElementById('fOdo').value),
                fuel_amount: parseFloat(document.getElementById('fAmount').value),
                total_cost: parseFloat(document.getElementById('fCost').value),
                fuel_station: document.getElementById('fStation').value,
                is_full: document.getElementById('fFull').checked ? 1 : 0
            };
            await fetch(`${API}/api/fuel`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
            document.getElementById('fuelForm').reset();
            loadVehicleData();
        }

        async function addService(e) {
            e.preventDefault();
            if(currentVehicleId === 'ALL') return alert("Select a specific vehicle first!");
            const body = {
                vehicle_id: parseInt(currentVehicleId),
                service_type: document.getElementById('sType').value,
                date: document.getElementById('sDate').value,
                odometer: parseFloat(document.getElementById('sOdo').value),
                cost: parseFloat(document.getElementById('sCost').value),
                service_station: document.getElementById('sStation').value,
                notes: document.getElementById('sNotes').value,
                next_service_date: document.getElementById('sNextDate').value
            };
            await fetch(`${API}/api/service`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
            document.getElementById('serviceForm').reset();
            loadVehicleData();
        }

        async function handleEdit(e, table, field, id) {
            if (e.key === 'Enter') {
                let val = e.target.value;
                if(field === 'odometer' || field === 'fuel_amount' || field === 'total_cost' || field === 'cost' || field === 'is_full') {
                    val = parseFloat(val) || 0;
                }
                await sendUpdate(table, field, id, val);
                e.target.blur();
            }
        }

        async function handleBlurEdit(table, field, id, element) {
            let val = element.value;
            await sendUpdate(table, field, id, val);
        }

        async function sendUpdate(table, field, id, value) {
            const body = { table, field, id, value: value };
            await fetch(`${API}/api/update`, { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
            fetchAnalytics();
        }

        async function deleteRow(table, id) {
            if(!confirm("Delete this entry permanently?")) return;
            await fetch(`${API}/api/delete?table=${table}&id=${id}`, { method: 'DELETE' });
            loadVehicleData();
        }

        async function exportData() {
            const res = await fetch(`${API}/api/export`);
            const data = await res.json();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `fuel_tracker_backup_${new Date().toISOString().split('T')[0]}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }

        async function importData(e) {
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = async function(evt) {
                try {
                    const parsed = JSON.parse(evt.target.result);
                    const res = await fetch(`${API}/api/import`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(parsed)
                    });
                    const resData = await res.json();
                    alert(`Import finished! Status: ${resData.status}`);
                    loadVehicles();
                } catch(err) {
                    alert("Failed to parse JSON backup file!");
                }
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
        return  # Keep console logs uncluttered

    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(200)

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)

        if path == "/":
            self._set_headers(200, content_type="text/html")
            self.wfile.write(INDEX_HTML.encode('utf-8'))
            return

        if path == "/health":
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "API Engine Active"}).encode('utf-8'))
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        if path == "/api/vehicles":
            cursor.execute("SELECT id, name, type, make_model, fuel_capacity, nickname FROM vehicles ORDER BY id ASC")
            rows = cursor.fetchall()
            data = [{"id": r[0], "name": r[1], "type": r[2], "make_model": r[3], "fuel_capacity": r[4], "nickname": r[5]} for r in rows]
            self._set_headers(200)
            self.wfile.write(json.dumps(data).encode('utf-8'))

        elif path == "/api/fuel":
            v_id_str = query.get('vehicle_id', ['ALL'])[0]
            if v_id_str == 'ALL':
                cursor.execute("""
                    SELECT f.id, f.date, f.odometer, f.fuel_amount, f.total_cost, f.is_full, f.fuel_station, v.nickname 
                    FROM fuel_logs f JOIN vehicles v ON f.vehicle_id = v.id 
                    ORDER BY f.date DESC, f.odometer DESC
                """)
            else:
                cursor.execute("""
                    SELECT f.id, f.date, f.odometer, f.fuel_amount, f.total_cost, f.is_full, f.fuel_station, v.nickname 
                    FROM fuel_logs f JOIN vehicles v ON f.vehicle_id = v.id 
                    WHERE f.vehicle_id = %s ORDER BY f.date DESC, f.odometer DESC
                """, (int(v_id_str),))
            rows = cursor.fetchall()
            data = [{"id": r[0], "date": r[1], "odometer": r[2], "fuel_amount": r[3], "total_cost": r[4], "is_full": r[5], "fuel_station": r[6], "vehicle_nickname": r[7]} for r in rows]
            self._set_headers(200)
            self.wfile.write(json.dumps(data).encode('utf-8'))

        elif path == "/api/service":
            v_id_str = query.get('vehicle_id', ['ALL'])[0]
            if v_id_str == 'ALL':
                cursor.execute("""
                    SELECT s.id, s.date, s.next_service_date, s.service_type, s.odometer, s.cost, s.notes, s.service_station, v.nickname 
                    FROM service_logs s JOIN vehicles v ON s.vehicle_id = v.id 
                    ORDER BY s.date DESC, s.odometer DESC
                """)
            else:
                cursor.execute("""
                    SELECT s.id, s.date, s.next_service_date, s.service_type, s.odometer, s.cost, s.notes, s.service_station, v.nickname 
                    FROM service_logs s JOIN vehicles v ON s.vehicle_id = v.id 
                    WHERE s.vehicle_id = %s ORDER BY s.date DESC, s.odometer DESC
                """, (int(v_id_str),))
            rows = cursor.fetchall()
            data = [{"id": r[0], "date": r[1], "next_service_date": r[2], "service_type": r[3], "odometer": r[4], "cost": r[5], "notes": r[6], "service_station": r[7], "vehicle_nickname": r[8]} for r in rows]
            self._set_headers(200)
            self.wfile.write(json.dumps(data).encode('utf-8'))

        elif path == "/api/analytics":
            v_id_str = query.get('vehicle_id', ['ALL'])[0]
            
            if v_id_str == 'ALL':
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

                    for log in logs:
                        odo, fuel, is_full = log[0], log[1], log[2]
                        if is_full == 1:
                            if last_full_odo is not None:
                                total_distance += (odo - last_full_odo)
                                total_consumed_fuel += (pending_fuel + fuel)
                                pending_fuel = 0.0
                            last_full_odo = odo
                        else:
                            if last_full_odo is not None:
                                pending_fuel += fuel

                    if total_consumed_fuel > 0:
                        avg_mileage = round(total_distance / total_consumed_fuel, 2)

            analytics = {
                "total_fuel_cost": total_fuel_cost,
                "total_service_cost": total_service_cost,
                "tco": total_fuel_cost + total_service_cost,
                "avg_mileage": avg_mileage
            }
            self._set_headers(200)
            self.wfile.write(json.dumps(analytics).encode('utf-8'))

        elif path == "/api/export":
            # Backup Export Strategy
            cursor.execute("SELECT id, name, type, make_model, fuel_capacity, nickname FROM vehicles")
            v_rows = cursor.fetchall()
            vehicles = [{"id": r[0], "name": r[1], "type": r[2], "make_model": r[3], "fuel_capacity": r[4], "nickname": r[5]} for r in v_rows]
            
            cursor.execute("SELECT id, vehicle_id, date, odometer, fuel_amount, total_cost, is_full, fuel_station FROM fuel_logs")
            f_rows = cursor.fetchall()
            fuel_logs = [{"id": r[0], "vehicle_id": r[1], "date": r[2], "odometer": r[3], "fuel_amount": r[4], "total_cost": r[5], "is_full": r[6], "fuel_station": r[7]} for r in f_rows]
            
            cursor.execute("SELECT id, vehicle_id, service_type, date, odometer, cost, notes, next_service_date, service_station FROM service_logs")
            s_rows = cursor.fetchall()
            service_logs = [{"id": r[0], "vehicle_id": r[1], "service_type": r[2], "date": r[3], "odometer": r[4], "cost": r[5], "notes": r[6], "next_service_date": r[7], "service_station": r[8]} for r in s_rows]
            
            backup_data = {"vehicles": vehicles, "fuel_logs": fuel_logs, "service_logs": service_logs}
            self._set_headers(200)
            self.wfile.write(json.dumps(backup_data).encode('utf-8'))

        cursor.close()
        conn.close()

    def do_POST(self):
        path = urlparse(self.path).path
        content_length = int(self.headers['Content-Length'])
        data = json.loads(self.rfile.read(content_length).decode('utf-8'))

        conn = get_db_connection()
        cursor = conn.cursor()

        if path == "/api/vehicles":
            cursor.execute("""
                INSERT INTO vehicles (name, type, make_model, fuel_capacity, nickname) VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (data['name'], data['type'], data['make_model'], data['fuel_capacity'], data.get('nickname')))
            new_id = cursor.fetchone()[0]
            conn.commit()
            self._set_headers(201)
            self.wfile.write(json.dumps({"status": "created", "vehicle_id": new_id}).encode('utf-8'))

        elif path == "/api/fuel":
            cursor.execute("""
                INSERT INTO fuel_logs (vehicle_id, date, odometer, fuel_amount, total_cost, is_full, fuel_station) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (data['vehicle_id'], data['date'], data['odometer'], data['fuel_amount'], data['total_cost'], data['is_full'], data.get('fuel_station')))
            conn.commit()
            self._set_headers(201)
            self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))

        elif path == "/api/service":
            cursor.execute("""
                INSERT INTO service_logs (vehicle_id, service_type, date, odometer, cost, notes, next_service_date, service_station) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (data['vehicle_id'], data['service_type'], data['date'], data['odometer'], data['cost'], data['notes'], data['next_service_date'], data.get('service_station')))
            conn.commit()
            self._set_headers(201)
            self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))

        elif path == "/api/import":
            # Backup Import Strategy
            try:
                vehicles = data.get('vehicles', [])
                fuel_logs = data.get('fuel_logs', [])
                service_logs = data.get('service_logs', [])
                
                # To maintain key relationships cleanly across platforms, map old IDs to newly assigned database serial indexes
                id_mapping = {}
                for v in vehicles:
                    cursor.execute("""
                        INSERT INTO vehicles (name, type, make_model, fuel_capacity, nickname) VALUES (%s, %s, %s, %s, %s) RETURNING id
                    """, (v['name'], v['type'], v['make_model'], v['fuel_capacity'], v.get('nickname')))
                    new_id = cursor.fetchone()[0]
                    id_mapping[v['id']] = new_id
                    
                for f in fuel_logs:
                    new_v_id = id_mapping.get(f['vehicle_id'])
                    if new_v_id:
                        cursor.execute("""
                            INSERT INTO fuel_logs (vehicle_id, date, odometer, fuel_amount, total_cost, is_full, fuel_station) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (new_v_id, f['date'], f['odometer'], f['fuel_amount'], f['total_cost'], f['is_full'], f.get('fuel_station')))
                        
                for s in service_logs:
                    new_v_id = id_mapping.get(s['vehicle_id'])
                    if new_v_id:
                        cursor.execute("""
                            INSERT INTO service_logs (vehicle_id, service_type, date, odometer, cost, notes, next_service_date, service_station) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (new_v_id, s['service_type'], s['date'], s['odometer'], s['cost'], s['notes'], s['next_service_date'], s.get('service_station')))
                
                conn.commit()
                self._set_headers(200)
                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
            except Exception as e:
                conn.rollback()
                self._set_headers(500)
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))

        cursor.close()
        conn.close()

    def do_PUT(self):
        path = urlparse(self.path).path
        if path == "/api/update":
            content_length = int(self.headers['Content-Length'])
            data = json.loads(self.rfile.read(content_length).decode('utf-8'))
            
            table_name = "fuel_logs" if data['table'] == "fuel" else "service_logs"
            field_name = data['field']
            
            allowed_fields = ["date", "odometer", "fuel_amount", "total_cost", "is_full", "service_type", "cost", "notes", "next_service_date", "fuel_station", "service_station"]
            if field_name not in allowed_fields:
                self.send_response(400)
                self.end_headers()
                return

            conn = get_db_connection()
            cursor = conn.cursor()
            query = f"UPDATE {table_name} SET {field_name} = %s WHERE id = %s"
            cursor.execute(query, (data['value'], data['id']))
            conn.commit()
            cursor.close()
            conn.close()
            
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "updated"}).encode('utf-8'))

    def do_DELETE(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)
        
        conn = get_db_connection()
        cursor = conn.cursor()

        if path == "/api/vehicles/delete":
            v_id = int(query.get('id', [0])[0])
            cursor.execute("DELETE FROM vehicles WHERE id = %s", (v_id,))
            conn.commit()
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "deleted"}).encode('utf-8'))

        elif path == "/api/delete":
            table = query.get('table', [None])[0]
            row_id = int(query.get('id', [0])[0])
            table_name = "fuel_logs" if table == "fuel" else "service_logs"
            
            cursor.execute(f"DELETE FROM {table_name} WHERE id = %s", (row_id,))
            conn.commit()
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "deleted"}).encode('utf-8'))

        cursor.close()
        conn.close()

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8000))
    server_address = ('', port)
    httpd = http.server.HTTPServer(server_address, BackendAPIHandler)
    print(f"🚀 Live API Engine firing up on port {port}...")
    httpd.serve_forever()
