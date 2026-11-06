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
    
    # Create Vehicles structural mapping table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vehicles (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        make_model TEXT,
        fuel_capacity REAL
    )""")
    
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
    
    conn.commit()
    cursor.close()
    conn.close()

# ==========================================
# 2. REST API REQUEST ENDPOINT HANDLER
# ==========================================
class BackendAPIHandler(http.server.BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        return  # Silences logging loops to keep the console clean

    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")  # Allows frontend to talk to this backend
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(200)

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)

        # Health-check route
        if path == "/" or path == "/health":
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "API Engine Active"}).encode('utf-8'))
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        if path == "/api/vehicles":
            cursor.execute("SELECT id, name, type, make_model, fuel_capacity FROM vehicles ORDER BY id ASC")
            rows = cursor.fetchall()
            data = [{"id": r[0], "name": r[1], "type": r[2], "make_model": r[3], "fuel_capacity": r[4]} for r in rows]
            self._set_headers(200)
            self.wfile.write(json.dumps(data).encode('utf-8'))

        elif path == "/api/fuel":
            v_id = int(query.get('vehicle_id', [0])[0])
            cursor.execute("SELECT id, date, odometer, fuel_amount, total_cost, is_full FROM fuel_logs WHERE vehicle_id = %s ORDER BY date DESC, odometer DESC", (v_id,))
            rows = cursor.fetchall()
            data = [{"id": r[0], "date": r[1], "odometer": r[2], "fuel_amount": r[3], "total_cost": r[4], "is_full": r[5]} for r in rows]
            self._set_headers(200)
            self.wfile.write(json.dumps(data).encode('utf-8'))

        elif path == "/api/service":
            v_id = int(query.get('vehicle_id', [0])[0])
            cursor.execute("SELECT id, date, next_service_date, service_type, odometer, cost, notes FROM service_logs WHERE vehicle_id = %s ORDER BY date DESC, odometer DESC", (v_id,))
            rows = cursor.fetchall()
            data = [{"id": r[0], "date": r[1], "next_service_date": r[2], "service_type": r[3], "odometer": r[4], "cost": r[5], "notes": r[6]} for r in rows]
            self._set_headers(200)
            self.wfile.write(json.dumps(data).encode('utf-8'))

        elif path == "/api/analytics":
            v_id = int(query.get('vehicle_id', [0])[0])
            
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
                INSERT INTO vehicles (name, type, make_model, fuel_capacity) VALUES (%s, %s, %s, %s) RETURNING id
            """, (data['name'], data['type'], data['make_model'], data['fuel_capacity']))
            new_id = cursor.fetchone()[0]
            conn.commit()
            self._set_headers(201)
            self.wfile.write(json.dumps({"status": "created", "vehicle_id": new_id}).encode('utf-8'))

        elif path == "/api/fuel":
            cursor.execute("""
                INSERT INTO fuel_logs (vehicle_id, date, odometer, fuel_amount, total_cost, is_full) VALUES (%s, %s, %s, %s, %s, %s)
            """, (data['vehicle_id'], data['date'], data['odometer'], data['fuel_amount'], data['total_cost'], data['is_full']))
            conn.commit()
            self._set_headers(201)
            self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))

        elif path == "/api/service":
            cursor.execute("""
                INSERT INTO service_logs (vehicle_id, service_type, date, odometer, cost, notes, next_service_date) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (data['vehicle_id'], data['service_type'], data['date'], data['odometer'], data['cost'], data['notes'], data['next_service_date']))
            conn.commit()
            self._set_headers(201)
            self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))

        cursor.close()
        conn.close()

    def do_PUT(self):
        path = urlparse(self.path).path
        if path == "/api/update":
            content_length = int(self.headers['Content-Length'])
            data = json.loads(self.rfile.read(content_length).decode('utf-8'))
            
            table_name = "fuel_logs" if data['table'] == "fuel" else "service_logs"
            field_name = data['field']
            
            allowed_fields = ["date", "odometer", "fuel_amount", "total_cost", "is_full", "service_type", "cost", "notes", "next_service_date"]
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
