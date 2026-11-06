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
    
    try:
        cursor.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS nickname TEXT;")
        cursor.execute("ALTER TABLE fuel_logs ADD COLUMN IF NOT EXISTS fuel_station TEXT;")
        cursor.execute("ALTER TABLE service_logs ADD COLUMN IF NOT EXISTS service_station TEXT;")
        conn.commit()
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
        
        .inline-edit { background: transparent; border: none; width: 100%; font-family: inherit; font-size: inherit; color: inherit; padding: 4px; box-sizing: border-box; }
        .inline-edit:focus { background: #fff; border: 1px solid var(--primary); outline: none; border-radius: 4px; }
        .notes-textarea { white-space: normal; word-break: break-word; resize: vertical; min-height: 32px; font-size: 13px; line-height: 1.4; padding: 4px; border: 1px solid transparent; background: transparent; width: 100%; box-sizing: border-box; }
        .notes-textarea:focus { background: #fff; border: 1px solid var(--primary); outline: none; border-radius: 4px; }
        
        /* Dynamic Due Alert Badges */
        .badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; margin-top: 4px; text-transform: uppercase; }
        .badge-overdue { background-color: #fee2e2; color: #dc2626; border: 1px solid #fca5a5; }
        .badge-warning { background-color: #fef3c7; color: #d97706; border: 1px solid #fcd34d; }
        .badge-safe { background-color: #d1fae5; color: #059669; border: 1px solid #6ee7b7; }
        
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
            <div class="stat-card"><h3>Total Fuel Cost</h3><p id=statFuel>₹0.00</p></div>
            <div class="stat-card"><h3>Total Service Cost</h3><p id=statService>₹0.00</p></div>
            <div class="stat-card"><h3>Total Cost of Ownership</h3><p id=statTco>₹0.00</p></div>
            <div class="stat-card"><h3>Avg Mileage</h3><p id=statMileage>N/A</p></div>
        </div>

        <div class="grid">
            <div class="panel">
                <h2>🚗 Add New Fleet Vehicle</h2>
                <form id="vehicleForm" onsubmit="addVehicle(event)" class="form-group">
                    <input type="text" id="vNickname" placeholder="Vehicle Nickname (e.g., My Bullet, City SUV)" required>
                    <input type="text" id="vName" placeholder="Official Structural Model Name (e.g., Thunderbird 350)" required>
                    <input type="text" id="vType" placeholder="Type (e.g., Bike, Sedan, SUV)" required>
                    <input type="text" id="vModel" placeholder="Manufacturer Make / Year">
                    <input type="number" step="any" id="vCapacity" placeholder="Tank Fuel Capacity (Liters)">
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
                        <label style="font-size:14px; margin-bottom:10px;"><input type="checkbox" id="fFull" checked value="1"> Full Tank fill?</label>
                        <button type="submit">Save Fuel Log</button>
                    </form>

                    <form id="serviceForm" onsubmit="addService(event)" class="form-group" style="display:none;">
                        <h3>Log Maintenance Work</h3>
                        <input type="text" id="sType" placeholder="Service Action Type (e.g., Engine Oil Change)" required>
                        <input type="date" id="sDate" required>
                        <input type="number" step="any" id="sOdo" placeholder="Odometer Value (km)" required>
                        <input type="number" step="any" id="sCost" placeholder="Total Cost (₹)" required>
                        <input type="text" id="sStation" placeholder="Workshop / Service Station Name (Optional)">
                        <input type="date" id="sNextDate" placeholder="Next Recommended Service Date Due">
                        <textarea id="sNotes" placeholder="Additional Notes / Detailed Parts List Summary"></textarea>
                        <button type="submit">Save Service Log</button>
                    </form>
                </div>

                <hr style="border:0; border-top:1px solid var(--border); margin:20px 0;">
                <h2>💾 Data Backup Management Tools</h2>
                <div class="backup-controls">
                    <button class="secondary" onclick="exportData()">📤 Export Cloud Backup JSON</button>
                    <input type="file" id="importFile" accept=".json" style="display:none;" onchange="importData(event)">
                    <button class="secondary" onclick="document.getElementById('importFile').click()">📥 Import Local Backup JSON</button>
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
                                <th style="width: 140px;">Vehicle Profile<div class="resizer"></div></th>
                                <th style="width: 120px;">Service Date<div class="resizer"></div></th>
                                <th style="width: 160px;">Service Action Type<div class="resizer"></div></th>
                                <th style="width: 140px;">Odometer (km)<div class="resizer"></div></th>
                                <th style="width: 120px;">Cost (₹)<div class="resizer"></div></th>
                                <th style="width: 180px;">Service Station / Workshop<div class="resizer"></div></th>
                                <th style="width: 180px;">Next Due Date & Status<div class="resizer"></div></th>
                                <th style="width: 250px;">Notes / Item Summaries<div class="resizer"></div></th>
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

        function calculateDueBadge(dateStr) {
            if (!dateStr || dateStr.trim() === "") return "";
            
            const targetDate = new Date(dateStr);
            if (isNaN(targetDate.getTime())) return "";
            
            const today = new Date();
            today.setHours(0,0,0,0);
            targetDate.setHours(0,0,0,0);
            
            const diffTime = targetDate.getTime() - today.getTime();
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
            
            if (diffDays < 0) {
                return `<br><span class="badge badge-overdue">🟥 Overdue by \${Math.abs(diffDays)} Days</span>`;
            } else if (diffDays === 0) {
                return `<br><span class="badge badge-overdue">🚨 Due Today!</span>`;
            } else if (diffDays <= 30) {
                return `<br><span class="badge badge-warning">🟨 Due in \${diffDays} Days</span>`;
            } else {
                return `<br><span class="badge badge-safe">🟩 Safe (\${diffDays} Days Left)</span>`;
            }
        }

        async function loadVehicles() {
            const res = await fetch(\`\${API}/api/vehicles\`);
            const data = await res.json();
            const select = document.getElementById('vehicleSelect');
            const mgmtDiv = document.getElementById('vehicleManagementList');
            
            select.innerHTML = '<option value="ALL">✨ ALL Vehicles (Combined Summary)</option>';
            mgmtDiv.innerHTML = '<h3>Registered Fleet Profiles:</h3>';
            vehicleCache = {};
            
            data.forEach(v => {
                const nameDisplay = v.nickname || v.name;
                vehicleCache[v.id] = nameDisplay;
                select.innerHTML += `<option value="\${v.id}">\${nameDisplay}</option>`;
                mgmtDiv.innerHTML += `<div style="display:flex; justify-content:space-between; margin-bottom:5px; font-size:14px; background:#f8fafc; padding:6px; border-radius:4px;">
                    <span>• <strong>\${nameDisplay}</strong> (\${v.type})</span>
                    <button class="delete" style="padding:2px 6px; font-size:11px;" onclick="deleteVehicle(\${v.id})">Delete Profile</button>
                </div>`;
            });
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
            await fetch(\`\${API}/api/vehicles\`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
            document.getElementById('vehicleForm').reset();
            loadVehicles();
        }

        async function deleteVehicle(id) {
            if(!confirm("Are you sure you want to drop this vehicle configuration profile alongside all attached historical logs permanently?")) return;
            await fetch(\`\${API}/api/vehicles/delete?id=\${id}\`, { method: 'DELETE' });
            loadVehicles();
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
            const url = vId === "ALL" ? `\${API}/api/analytics?vehicle_id=0` : `\${API}/api/analytics?vehicle_id=\${vId}`;
            const res = await fetch(url);
            const a = await res.json();
            document.getElementById('statFuel').innerText = `₹\${a.total_fuel_cost.toFixed(2)}`;
            document.getElementById('statService').innerText = `₹\${a.total_service_cost.toFixed(2)}`;
            document.getElementById('statTco').innerText = `₹\${a.tco.toFixed(2)}`;
            document.getElementById('statMileage').innerText = a.avg_mileage !== "N/A" ? `\${a.avg_mileage} km/L` : "N/A";
        }

        async function fetchFuelLogs(vId) {
            const url = vId === "ALL" ? `\${API}/api/fuel?vehicle_id=0` : `\${API}/api/fuel?vehicle_id=\${vId}`;
            const res = await fetch(url);
            const data = await res.json();
            const tbody = document.getElementById('fuelTableBody');
            tbody.innerHTML = '';
            
            data.forEach(r => {
                const vehicleLabel = vehicleCache[r.vehicle_id] || `ID: \${r.vehicle_id}`;
                tbody.innerHTML += `<tr>
                    <td><div style="font-weight:600; color:#374151;">\${vehicleLabel}</div></td>
                    <td><input class="inline-edit" value="\${r.date}" onkeydown="handleEdit(event, 'fuel', 'date', \${r.id})"></td>
                    <td><input class="inline-edit" type="number" step="any" value="\${r.odometer}" onkeydown="handleEdit(event, 'fuel', 'odometer', \${r.id})"></td>
                    <td><input class="inline-edit" type="number" step="any" value="\${r.fuel_amount}" onkeydown="handleEdit(event, 'fuel', 'fuel_amount', \${r.id})"></td>
                    <td><input class="inline-edit" type="number" step="any" value="\${r.total_cost}" onkeydown="handleEdit(event, 'fuel', 'total_cost', \${r.id})"></td>
                    <td><input class="inline-edit" value="\${r.fuel_station || ''}" onkeydown="handleEdit(event, 'fuel', 'fuel_station', \${r.id})"></td>
                    <td><input class="inline-edit" type="number" value="\${r.is_full}" onkeydown="handleEdit(event, 'fuel', 'is_full', \${r.id})"></td>
                    <td><button class="delete" style="padding:4px 8px; font-size:12px;" onclick="deleteRow('fuel', \${r.id})">Delete</button></td>
                </tr>`;
            });
        }

        async function fetchServiceLogs(vId) {
            const url = vId === "ALL" ? `\${API}/api/service?vehicle_id=0` : `\${API}/api/service?vehicle_id=\${vId}`;
            const res = await fetch(url);
            const data = await res.json();
            const tbody = document.getElementById('serviceTableBody');
            tbody.innerHTML = '';
            
            data.forEach(r => {
                const vehicleLabel = vehicleCache[r.vehicle_id] || `ID: \${r.vehicle_id}`;
                const badgeHtml = calculateDueBadge(r.next_service_date);
                tbody.innerHTML += `<tr>
                    <td><div style="font-weight:600; color:#374151;">	ext{\${vehicleLabel}}</div></td>
                    <td><input class="inline-edit" value="\${r.date}" onkeydown="handleEdit(event, 'service', 'date', \${r.id})"></td>
                    <td><input class="inline-edit" value="\${r.service_type}" onkeydown="handleEdit(event, 'service', 'service_type', \${r.id})"></td>
                    <td><input class="inline-edit" type="number" step="any" value="\${r.odometer}" onkeydown="handleEdit(event, 'service', 'odometer', \${r.id})"></td>
                    <td><input class="inline-edit" type="number" step="any" value="\${r.cost}" onkeydown="handleEdit(event, 'service', 'cost', \${r.id})"></td>
                    <td><input class="inline-edit" value="\${r.service_station || ''}" onkeydown="handleEdit(event, 'service', 'service_station', \${r.id})"></td>
                    <td><input class="inline-edit" value="\${r.next_service_date || ''}" onkeydown="handleEdit(event, 'service', 'next_service_date', \${r.id})">\${badgeHtml}</td>
                    <td><textarea class="notes-textarea" onblur="handleTextareaBlur(this, \${r.id})" onkeydown="handleTextareaKey(event, this, \${r.id})">\${r.notes || ''}</textarea></td>
                    <td><button class="delete" style="padding:4px 8px; font-size:12px;" onclick="deleteRow('service', \${r.id})">Delete</button></td>
                </tr>`;
            });
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
            await fetch(\`\${API}/api/fuel\`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
            document.getElementById('fuelForm').reset();
            loadVehicleData();
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
            await fetch(\`\${API}/api/service\`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
            document.getElementById('serviceForm').reset();
            loadVehicleData();
        }

        async function handleEdit(e, table, field, id) {
            if (e.key === 'Enter') {
                let val = e.target.value;
                if(['odometer', 'fuel_amount', 'total_cost', 'cost', 'is_full'].includes(field)) {
                    val = parseFloat(val) || 0;
                }
                await submitUpdate(table, field, id, val);
                e.target.blur();
                loadVehicleData();
            }
        }

        async function handleTextareaBlur(el, id) {
            await submitUpdate('service', 'notes', id, el.value);
        }

        async function handleTextareaKey(e, el, id) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                await submitUpdate('service', 'notes', id, el.value);
                el.blur();
                loadVehicleData();
            }
        }

        async function submitUpdate(table, field, id, value) {
            const body = { table, field, id, value };
            await fetch(\`\${API}/api/update\`, { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
        }

        async function deleteRow(table, id) {
            if(!confirm("Erase this configuration row metric record permanently?")) return;
            await fetch(\`\${API}/api/delete?table=\${table}&id=\${id}\`, { method: 'DELETE' });
            loadVehicleData();
        }

        async function exportData() {
            const res = await fetch(\`\${API}/api/export\`);
            const data = await res.json();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = \`fuel_tracker_backup_\${new Date().toISOString().split('T')[0]}.json\`;
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
                    const res = await fetch(\`\${API}/api/import\`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(parsed)
                    });
                    const resData = await res.json();
                    alert(\`Import finished! Process Log State: \${resData.status}\`);
                    loadVehicles();
                } catch(err) {
                    alert("Parsing file format error! Validate target backup setup.");
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
        return  # Keep terminal logs clean

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
            cursor.execute("SELECT id, nickname, name, type, make_model, fuel_capacity FROM vehicles ORDER BY id ASC")
            rows = cursor.fetchall()
            data = [{"id": r[0], "nickname": r[1], "name": r[2], "type": r[3], "make_model": r[4], "fuel_capacity": r[5]} for r in rows]
            self._set_headers(200)
            self.wfile.write(json.dumps(data).encode('utf-8'))

        elif path == "/api/fuel":
            v_id_str = query.get('vehicle_id', ["0"])[0]
            if v_id_str == "0" or v_id_str == "ALL":
                cursor.execute("SELECT id, vehicle_id, date, odometer, fuel_amount, total_cost, fuel_station, is_full FROM fuel_logs ORDER BY date DESC, odometer DESC")
            else:
                cursor.execute("SELECT id, vehicle_id, date, odometer, fuel_amount, total_cost, fuel_station, is_full FROM fuel_logs WHERE vehicle_id = %s ORDER BY date DESC, odometer DESC", (int(v_id_str),))
            rows = cursor.fetchall()
            data = [{"id": r[0], "vehicle_id": r[1], "date": r[2], "odometer": r[3], "fuel_amount": r[4], "total_cost": r[5], "fuel_station": r[6], "is_full": r[7]} for r in rows]
            self._set_headers(200)
            self.wfile.write(json.dumps(data).encode('utf-8'))

        elif path == "/api/service":
            v_id_str = query.get('vehicle_id', ["0"])[0]
            if v_id_str == "0" or v_id_str == "ALL":
                cursor.execute("SELECT id, vehicle_id, date, next_service_date, service_type, odometer, cost, service_station, notes FROM service_logs ORDER BY date DESC, odometer DESC")
            else:
                cursor.execute("SELECT id, vehicle_id, date, next_service_date, service_type, odometer, cost, service_station, notes FROM service_logs WHERE vehicle_id = %s ORDER BY date DESC, odometer DESC", (int(v_id_str),))
            rows = cursor.fetchall()
            data = [{"id": r[0], "vehicle_id": r[1], "date": r[2], "next_service_date": r[3], "service_type": r[4], "odometer": r[5], "cost": r[6], "service_station": r[7], "notes": r[8]} for r in rows]
            self._set_headers(200)
            self.wfile.write(json.dumps(data).encode('utf-8'))

        elif path == "/api/analytics":
            v_id_str = query.get('vehicle_id', ["0"])[0]
            
            if v_id_str == "0" or v_id_str == "ALL":
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
            cursor.execute("SELECT id, nickname, name, type, make_model, fuel_capacity FROM vehicles")
            v_rows = cursor.fetchall()
            vehicles = [{"id": r[0], "nickname": r[1], "name": r[2], "type": r[3], "make_model": r[4], "fuel_capacity": r[5]} for r in v_rows]

            cursor.execute("SELECT id, vehicle_id, date, odometer, fuel_amount, total_cost, fuel_station, is_full FROM fuel_logs")
            f_rows = cursor.fetchall()
            fuel = [{"id": r[0], "vehicle_id": r[1], "date": r[2], "odometer": r[3], "fuel_amount": r[4], "total_cost": r[5], "fuel_station": r[6], "is_full": r[7]} for r in f_rows]

            cursor.execute("SELECT id, vehicle_id, date, next_service_date, service_type, odometer, cost, service_station, notes FROM service_logs")
            s_rows = cursor.fetchall()
            service = [{"id": r[0], "vehicle_id": r[1], "date": r[2], "next_service_date": r[3], "service_type": r[4], "odometer": r[5], "cost": r[6], "service_station": r[7], "notes": r[8]} for r in s_rows]

            backup = {"vehicles": vehicles, "fuel_logs": fuel, "service_logs": service}
            self._set_headers(200)
            self.wfile.write(json.dumps(backup).encode('utf-8'))

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
                INSERT INTO vehicles (nickname, name, type, make_model, fuel_capacity) VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (data.get('nickname'), data['name'], data['type'], data['make_model'], data['fuel_capacity']))
            new_id = cursor.fetchone()[0]
            conn.commit()
            self._set_headers(201)
            self.wfile.write(json.dumps({"status": "created", "vehicle_id": new_id}).encode('utf-8'))

        elif path == "/api/fuel":
            cursor.execute("""
                INSERT INTO fuel_logs (vehicle_id, date, odometer, fuel_amount, total_cost, fuel_station, is_full) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (data['vehicle_id'], data['date'], data['odometer'], data['fuel_amount'], data['total_cost'], data.get('fuel_station'), data['is_full']))
            conn.commit()
            self._set_headers(201)
            self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))

        elif path == "/api/service":
            cursor.execute("""
                INSERT INTO service_logs (vehicle_id, service_type, date, odometer, cost, service_station, notes, next_service_date) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (data['vehicle_id'], data['service_type'], data['date'], data['odometer'], data['cost'], data.get('service_station'), data['notes'], data['next_service_date']))
            conn.commit()
            self._set_headers(201)
            self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))

        elif path == "/api/import":
            try:
                cursor.execute("TRUNCATE TABLE vehicles, fuel_logs, service_logs RESTART IDENTITY CASCADE;")
                
                v_map = {}
                for v in data.get('vehicles', []):
                    cursor.execute("""
                        INSERT INTO vehicles (nickname, name, type, make_model, fuel_capacity) VALUES (%s, %s, %s, %s, %s) RETURNING id
                    """, (v.get('nickname'), v['name'], v['type'], v.get('make_model'), v.get('fuel_capacity')))
                    v_map[v['id']] = cursor.fetchone()[0]

                for f in data.get('fuel_logs', []):
                    if f['vehicle_id'] in v_map:
                        cursor.execute("""
                            INSERT INTO fuel_logs (vehicle_id, date, odometer, fuel_amount, total_cost, fuel_station, is_full) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (v_map[f['vehicle_id']], f['date'], f['odometer'], f['fuel_amount'], f['total_cost'], f.get('fuel_station'), f['is_full']))

                for s in data.get('service_logs', []):
                    if s['vehicle_id'] in v_map:
                        cursor.execute("""
                            INSERT INTO service_logs (vehicle_id, service_type, date, odometer, cost, service_station, notes, next_service_date) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (v_map[s['vehicle_id']], s['service_type'], s['date'], s['odometer'], s['cost'], s.get('service_station'), s.get('notes'), s.get('next_service_date')))

                conn.commit()
                self._set_headers(200)
                self.wfile.write(json.dumps({"status": "Success"}).encode('utf-8'))
            except Exception as err:
                conn.rollback()
                self._set_headers(500)
                self.wfile.write(json.dumps({"status": f"Failure: {str(err)}"}).encode('utf-8'))

        cursor.close()
        conn.close()

    def do_PUT(self):
        path = urlparse(self.path).path
        if path == "/api/update":
            content_length = int(self.headers['Content-Length'])
            data = json.loads(self.rfile.read(content_length).decode('utf-8'))
            
            table_name = "fuel_logs" if data['table'] == "fuel" else "service_logs"
            field_name = data['field']
            
            allowed_fields = ["date", "odometer", "fuel_amount", "total_cost", "is_full", "service_type", "cost", "service_station", "notes", "next_service_date"]
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
            v_id = int(query.get('id')[0])
            cursor.execute("DELETE FROM vehicles WHERE id = %s", (v_id,))
            conn.commit()
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "deleted"}).encode('utf-8'))

        elif path == "/api/delete":
            table = query.get('table')[0]
            row_id = int(query.get('id')[0])
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
