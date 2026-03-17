"""
SSE Equipment Inspection System
"""
import os
import json
from datetime import datetime, date
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path

# Database setup
DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_POSTGRES = DATABASE_URL.startswith("postgresql") if DATABASE_URL else False

if USE_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def get_db():
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        try:
            yield conn
        finally:
            conn.close()

    def get_db_connection():
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
else:
    import sqlite3
    DB_PATH = "inspections.db"

    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def get_db_connection():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def init_database():
    conn = get_db_connection()
    cursor = conn.cursor()

    if USE_POSTGRES:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS equipment (
                id SERIAL PRIMARY KEY,
                equipment_id VARCHAR(50) UNIQUE NOT NULL,
                equipment_type VARCHAR(50) NOT NULL,
                category VARCHAR(50) DEFAULT 'field',
                make VARCHAR(100),
                model VARCHAR(100),
                serial_number VARCHAR(100),
                capacity VARCHAR(50),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inspections (
                id SERIAL PRIMARY KEY,
                equipment_id INTEGER REFERENCES equipment(id),
                inspection_type VARCHAR(20) NOT NULL,
                inspection_date DATE NOT NULL,
                inspector_name VARCHAR(100) NOT NULL,
                hour_meter_reading INTEGER,
                overall_status VARCHAR(20) NOT NULL,
                general_comments TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inspection_items (
                id SERIAL PRIMARY KEY,
                inspection_id INTEGER REFERENCES inspections(id) ON DELETE CASCADE,
                category VARCHAR(100) NOT NULL,
                item_name VARCHAR(200) NOT NULL,
                status VARCHAR(20) NOT NULL,
                comments TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inspection_item_photos (
                id SERIAL PRIMARY KEY,
                item_id INTEGER REFERENCES inspection_items(id) ON DELETE CASCADE,
                filename VARCHAR(255) NOT NULL,
                mime_type VARCHAR(100) NOT NULL,
                photo_data TEXT NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS work_tickets (
                id SERIAL PRIMARY KEY,
                equipment_id INTEGER REFERENCES equipment(id),
                inspection_id INTEGER REFERENCES inspections(id),
                title VARCHAR(200) NOT NULL,
                description TEXT,
                priority VARCHAR(20) DEFAULT 'normal',
                status VARCHAR(20) DEFAULT 'open',
                assigned_to VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                completed_by VARCHAR(100),
                completion_notes TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS work_ticket_photos (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER REFERENCES work_tickets(id) ON DELETE CASCADE,
                filename VARCHAR(255) NOT NULL,
                mime_type VARCHAR(100) NOT NULL,
                photo_data TEXT NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS work_ticket_logs (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER REFERENCES work_tickets(id) ON DELETE CASCADE,
                status VARCHAR(20),
                note TEXT NOT NULL,
                created_by VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Safe migrations for existing databases
        cursor.execute("ALTER TABLE work_tickets ADD COLUMN IF NOT EXISTS completion_notes TEXT")

    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS equipment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id VARCHAR(50) UNIQUE NOT NULL,
                equipment_type VARCHAR(50) NOT NULL,
                category VARCHAR(50) DEFAULT 'field',
                make VARCHAR(100),
                model VARCHAR(100),
                serial_number VARCHAR(100),
                capacity VARCHAR(50),
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inspections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id INTEGER REFERENCES equipment(id),
                inspection_type VARCHAR(20) NOT NULL,
                inspection_date DATE NOT NULL,
                inspector_name VARCHAR(100) NOT NULL,
                hour_meter_reading INTEGER,
                overall_status VARCHAR(20) NOT NULL,
                general_comments TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inspection_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inspection_id INTEGER REFERENCES inspections(id) ON DELETE CASCADE,
                category VARCHAR(100) NOT NULL,
                item_name VARCHAR(200) NOT NULL,
                status VARCHAR(20) NOT NULL,
                comments TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inspection_item_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER REFERENCES inspection_items(id) ON DELETE CASCADE,
                filename VARCHAR(255) NOT NULL,
                mime_type VARCHAR(100) NOT NULL,
                photo_data TEXT NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS work_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id INTEGER REFERENCES equipment(id),
                inspection_id INTEGER REFERENCES inspections(id),
                title VARCHAR(200) NOT NULL,
                description TEXT,
                priority VARCHAR(20) DEFAULT 'normal',
                status VARCHAR(20) DEFAULT 'open',
                assigned_to VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                completed_by VARCHAR(100),
                completion_notes TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS work_ticket_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER REFERENCES work_tickets(id) ON DELETE CASCADE,
                filename VARCHAR(255) NOT NULL,
                mime_type VARCHAR(100) NOT NULL,
                photo_data TEXT NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS work_ticket_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER REFERENCES work_tickets(id) ON DELETE CASCADE,
                status VARCHAR(20),
                note TEXT NOT NULL,
                created_by VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Safe migration for existing SQLite databases
        try:
            cursor.execute("ALTER TABLE work_tickets ADD COLUMN completion_notes TEXT")
        except Exception:
            pass

    conn.commit()
    conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    print("Database initialized")
    yield


app = FastAPI(
    title="SSE Equipment Inspection System",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"

# =============================================================================
# CALIBRATION MODULE
# =============================================================================
from app.api.calibration import router as calibration_router
app.include_router(calibration_router)

# WELDING MODULE
from app.api.welding_roster import router as welding_router, init_welding_tables
app.include_router(welding_router)


# =============================================================================
# Pydantic Models
# =============================================================================

class EquipmentCreate(BaseModel):
    equipment_id: str
    equipment_type: str
    category: str = "field"
    make: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    capacity: Optional[str] = None

class EquipmentUpdate(BaseModel):
    equipment_id: Optional[str] = None
    equipment_type: Optional[str] = None
    category: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    capacity: Optional[str] = None
    is_active: Optional[bool] = None

class InspectionItemPhotoCreate(BaseModel):
    filename: str
    photo_data: str
    mime_type: str

class InspectionItemCreate(BaseModel):
    category: str
    item_name: str
    status: str  # ok, needs_attention, needs_service, out_of_service, na
    comments: Optional[str] = None
    photos: List[InspectionItemPhotoCreate] = []

class InspectionCreate(BaseModel):
    equipment_id: int
    inspection_type: str
    inspection_date: str
    inspector_name: str
    hour_meter_reading: Optional[int] = None
    overall_status: str
    general_comments: Optional[str] = None
    items: List[InspectionItemCreate] = []

class WorkTicketCreate(BaseModel):
    equipment_id: int
    inspection_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    priority: str = "normal"
    assigned_to: Optional[str] = None

class WorkTicketUpdate(BaseModel):
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    priority: Optional[str] = None
    completed_by: Optional[str] = None
    completion_notes: Optional[str] = None

class WorkTicketPhotoCreate(BaseModel):
    filename: str
    photo_data: str
    mime_type: str

class WorkTicketLogCreate(BaseModel):
    note: str
    created_by: str
    status: Optional[str] = None  # if provided, also updates ticket status


# =============================================================================
# Equipment Endpoints
# =============================================================================

@app.get("/api/equipment")
async def get_equipment(category: Optional[str] = None, active_only: bool = True):
    conn = get_db_connection()
    cursor = conn.cursor()

    active_filter = ("is_active = TRUE" if USE_POSTGRES else "is_active = 1") if active_only else "1=1"

    if category and category != 'all':
        if USE_POSTGRES:
            cursor.execute(f"SELECT * FROM equipment WHERE category = %s AND {active_filter} ORDER BY equipment_id", (category,))
        else:
            cursor.execute(f"SELECT * FROM equipment WHERE category = ? AND {active_filter} ORDER BY equipment_id", (category,))
    else:
        cursor.execute(f"SELECT * FROM equipment WHERE {active_filter} ORDER BY equipment_id")

    equipment = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return equipment

@app.post("/api/equipment")
async def create_equipment(equip: EquipmentCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO equipment (equipment_id, equipment_type, category, make, model, serial_number, capacity)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (equip.equipment_id, equip.equipment_type, equip.category,
                  equip.make, equip.model, equip.serial_number, equip.capacity))
            equip_id = cursor.fetchone()['id']
        else:
            cursor.execute("""
                INSERT INTO equipment (equipment_id, equipment_type, category, make, model, serial_number, capacity)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (equip.equipment_id, equip.equipment_type, equip.category,
                  equip.make, equip.model, equip.serial_number, equip.capacity))
            equip_id = cursor.lastrowid
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
    return {"id": equip_id, "message": "Equipment created"}

@app.put("/api/equipment/{equip_id}")
async def update_equipment(equip_id: int, updates: EquipmentUpdate):
    conn = get_db_connection()
    cursor = conn.cursor()
    update_fields = {k: v for k, v in updates.dict().items() if v is not None}
    for field, value in update_fields.items():
        if USE_POSTGRES:
            cursor.execute(f"UPDATE equipment SET {field} = %s WHERE id = %s", (value, equip_id))
        else:
            cursor.execute(f"UPDATE equipment SET {field} = ? WHERE id = ?", (value, equip_id))
    conn.commit()
    conn.close()
    return {"message": "Equipment updated"}

@app.delete("/api/equipment/{equip_id}")
async def delete_equipment(equip_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    if USE_POSTGRES:
        cursor.execute("UPDATE equipment SET is_active = FALSE WHERE id = %s", (equip_id,))
    else:
        cursor.execute("UPDATE equipment SET is_active = 0 WHERE id = ?", (equip_id,))
    conn.commit()
    conn.close()
    return {"message": "Equipment deactivated"}

@app.post("/api/equipment/seed")
async def seed_equipment():
    conn = get_db_connection()
    cursor = conn.cursor()
    if USE_POSTGRES:
        cursor.execute("SELECT COUNT(*) as cnt FROM equipment WHERE is_active = TRUE")
    else:
        cursor.execute("SELECT COUNT(*) as cnt FROM equipment WHERE is_active = 1")
    count = dict(cursor.fetchone()).get("cnt", 0)
    if count > 0:
        conn.close()
        return {"message": f"Database already has {count} equipment records. Seed skipped.", "seeded": False}

    seed_data = [
        ("BIG-RED", "telehandler", "field", "Taylor", "33K Forklift", None, "33,000 lbs"),
        ("BLUE-GENIE", "telehandler", "field", "Genie", "Telehandler", None, None),
        ("GREEN-JLG", "telehandler", "field", "JLG", "Telehandler", None, None),
        ("ORANGE-GENIE", "telehandler", "field", "Genie", "Telehandler", None, None),
        ("CAT-12K", "telehandler", "field", "Caterpillar", "12K Telehandler", None, "12,000 lbs"),
        ("PIRANHA-01", "piranha-laser", "shop", "Piranha", "6kW Fiber Laser (IPG source, dual pallet shuttle, chiller, assist gas, gantry, dust collector)", None, "6kW"),
        ("PYTHON-BL-01", "python-beam", "shop", "Python X", "Beam Line (300A Hypertherm, 100ft infeed w/ 4 cross transfers, 40ft outfeed, hydraulic clamping)", None, None),
        ("PYTHON-PT-01", "python-plasma", "shop", "Python X", "Plasma Table 10x25 (300A Hypertherm, articulating bevel head, THC, fume extraction)", None, None),
        ("EMI-TC-01", "emi-cutting", "shop", "EMI", "TPC2464 Tube Cutter", None, None),
        ("MILLER-01", "welder", "shop", "Miller", "Millermatic 350P MIG Welder", None, None),
        ("PRESS-01", "press-brake", "shop", "Standard", "350T Hydraulic Press Brake (CNC back gauge, hydraulic clamping, light curtains)", None, "350 Ton"),
        ("ROUNDO-01", "plate-roller", "shop", "Roundo", "Plate Roller (hydraulic top roll, 3-roll config, drop end mechanism)", None, None),
    ]
    inserted = 0
    for (eid, etype, cat, make, model, sn, cap) in seed_data:
        try:
            if USE_POSTGRES:
                cursor.execute("INSERT INTO equipment (equipment_id, equipment_type, category, make, model, serial_number, capacity) VALUES (%s,%s,%s,%s,%s,%s,%s)", (eid, etype, cat, make, model, sn, cap))
            else:
                cursor.execute("INSERT INTO equipment (equipment_id, equipment_type, category, make, model, serial_number, capacity) VALUES (?,?,?,?,?,?,?)", (eid, etype, cat, make, model, sn, cap))
            inserted += 1
        except Exception as e:
            print(f"Seed error for {eid}: {e}")
    conn.commit()
    conn.close()
    return {"message": f"Seeded {inserted} equipment records for SSE", "seeded": True, "count": inserted}


# =============================================================================
# Inspection Endpoints
# =============================================================================

@app.get("/api/inspections")
async def get_inspections(equipment_id: Optional[int] = None, inspection_type: Optional[str] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
        SELECT i.*, e.equipment_id as equipment_code, e.equipment_type, e.make, e.model
        FROM inspections i JOIN equipment e ON i.equipment_id = e.id WHERE 1=1
    """
    params = []
    if equipment_id:
        query += " AND i.equipment_id = %s" if USE_POSTGRES else " AND i.equipment_id = ?"
        params.append(equipment_id)
    if inspection_type:
        query += " AND i.inspection_type = %s" if USE_POSTGRES else " AND i.inspection_type = ?"
        params.append(inspection_type)
    query += " ORDER BY i.inspection_date DESC, i.created_at DESC"
    cursor.execute(query, params)
    inspections = [dict(row) for row in cursor.fetchall()]
    for insp in inspections:
        if USE_POSTGRES:
            cursor.execute("SELECT * FROM inspection_items WHERE inspection_id = %s", (insp['id'],))
        else:
            cursor.execute("SELECT * FROM inspection_items WHERE inspection_id = ?", (insp['id'],))
        insp['items'] = [dict(item) for item in cursor.fetchall()]
    conn.close()
    return inspections


@app.post("/api/inspections")
async def create_inspection(inspection: InspectionCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    TICKET_STATUSES = {'needs_attention', 'needs_service', 'out_of_service'}
    try:
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO inspections (equipment_id, inspection_type, inspection_date, inspector_name,
                    hour_meter_reading, overall_status, general_comments)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (inspection.equipment_id, inspection.inspection_type, inspection.inspection_date,
                  inspection.inspector_name, inspection.hour_meter_reading,
                  inspection.overall_status, inspection.general_comments))
            inspection_id = cursor.fetchone()['id']
        else:
            cursor.execute("""
                INSERT INTO inspections (equipment_id, inspection_type, inspection_date, inspector_name,
                    hour_meter_reading, overall_status, general_comments)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (inspection.equipment_id, inspection.inspection_type, inspection.inspection_date,
                  inspection.inspector_name, inspection.hour_meter_reading,
                  inspection.overall_status, inspection.general_comments))
            inspection_id = cursor.lastrowid

        work_ticket_ids = []
        for item in inspection.items:
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO inspection_items (inspection_id, category, item_name, status, comments)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id
                """, (inspection_id, item.category, item.item_name, item.status, item.comments))
                item_id = cursor.fetchone()['id']
            else:
                cursor.execute("""
                    INSERT INTO inspection_items (inspection_id, category, item_name, status, comments)
                    VALUES (?, ?, ?, ?, ?)
                """, (inspection_id, item.category, item.item_name, item.status, item.comments))
                item_id = cursor.lastrowid

            for photo in item.photos:
                if USE_POSTGRES:
                    cursor.execute("INSERT INTO inspection_item_photos (item_id, filename, mime_type, photo_data) VALUES (%s,%s,%s,%s)",
                                   (item_id, photo.filename, photo.mime_type, photo.photo_data))
                else:
                    cursor.execute("INSERT INTO inspection_item_photos (item_id, filename, mime_type, photo_data) VALUES (?,?,?,?)",
                                   (item_id, photo.filename, photo.mime_type, photo.photo_data))

            if item.status in TICKET_STATUSES:
                is_high = (item.status == 'out_of_service' or inspection.overall_status == 'out_of_service')
                priority = 'high' if is_high else 'normal'
                status_label = {'needs_attention': 'Needs Attention', 'needs_service': 'Needs Service', 'out_of_service': 'OUT OF SERVICE'}.get(item.status, item.status)
                title = f"{item.item_name} — {status_label}"
                description = item.comments or f"Found during {inspection.inspection_type} inspection"
                if USE_POSTGRES:
                    cursor.execute("INSERT INTO work_tickets (equipment_id, inspection_id, title, description, priority) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                                   (inspection.equipment_id, inspection_id, title, description, priority))
                    work_ticket_ids.append(cursor.fetchone()['id'])
                else:
                    cursor.execute("INSERT INTO work_tickets (equipment_id, inspection_id, title, description, priority) VALUES (?,?,?,?,?)",
                                   (inspection.equipment_id, inspection_id, title, description, priority))
                    work_ticket_ids.append(cursor.lastrowid)

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

    return {"id": inspection_id, "message": "Inspection created", "work_tickets_created": len(work_ticket_ids), "work_ticket_ids": work_ticket_ids}


@app.get("/api/inspections/{inspection_id}")
async def get_inspection(inspection_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    if USE_POSTGRES:
        cursor.execute("""
            SELECT i.*, e.equipment_id as equipment_code, e.equipment_type, e.make, e.model
            FROM inspections i JOIN equipment e ON i.equipment_id = e.id WHERE i.id = %s
        """, (inspection_id,))
    else:
        cursor.execute("""
            SELECT i.*, e.equipment_id as equipment_code, e.equipment_type, e.make, e.model
            FROM inspections i JOIN equipment e ON i.equipment_id = e.id WHERE i.id = ?
        """, (inspection_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Inspection not found")
    inspection = dict(row)
    if USE_POSTGRES:
        cursor.execute("SELECT * FROM inspection_items WHERE inspection_id = %s ORDER BY id", (inspection_id,))
    else:
        cursor.execute("SELECT * FROM inspection_items WHERE inspection_id = ? ORDER BY id", (inspection_id,))
    items = [dict(item) for item in cursor.fetchall()]
    for item in items:
        if USE_POSTGRES:
            cursor.execute("SELECT * FROM inspection_item_photos WHERE item_id = %s ORDER BY uploaded_at", (item['id'],))
        else:
            cursor.execute("SELECT * FROM inspection_item_photos WHERE item_id = ? ORDER BY uploaded_at", (item['id'],))
        item['photos'] = [dict(p) for p in cursor.fetchall()]
    inspection['items'] = items
    conn.close()
    return inspection


@app.delete("/api/inspections/{inspection_id}")
async def delete_inspection(inspection_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    if USE_POSTGRES:
        cursor.execute("DELETE FROM inspection_items WHERE inspection_id = %s", (inspection_id,))
        cursor.execute("DELETE FROM inspections WHERE id = %s", (inspection_id,))
    else:
        cursor.execute("DELETE FROM inspection_items WHERE inspection_id = ?", (inspection_id,))
        cursor.execute("DELETE FROM inspections WHERE id = ?", (inspection_id,))
    conn.commit()
    conn.close()
    return {"message": "Inspection deleted"}


# =============================================================================
# Work Ticket Endpoints
# =============================================================================

@app.get("/api/work-tickets")
async def get_work_tickets(status: Optional[str] = None, equipment_id: Optional[int] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
        SELECT wt.*, e.equipment_id as equipment_code, e.equipment_type, e.make, e.model
        FROM work_tickets wt JOIN equipment e ON wt.equipment_id = e.id WHERE 1=1
    """
    params = []
    if status and status != 'all':
        query += " AND wt.status = %s" if USE_POSTGRES else " AND wt.status = ?"
        params.append(status)
    if equipment_id:
        query += " AND wt.equipment_id = %s" if USE_POSTGRES else " AND wt.equipment_id = ?"
        params.append(equipment_id)
    query += " ORDER BY CASE wt.priority WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, wt.created_at DESC"
    cursor.execute(query, params)
    tickets = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return tickets


@app.post("/api/work-tickets")
async def create_work_ticket(ticket: WorkTicketCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    if USE_POSTGRES:
        cursor.execute("INSERT INTO work_tickets (equipment_id, inspection_id, title, description, priority, assigned_to) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                       (ticket.equipment_id, ticket.inspection_id, ticket.title, ticket.description, ticket.priority, ticket.assigned_to))
        ticket_id = cursor.fetchone()['id']
    else:
        cursor.execute("INSERT INTO work_tickets (equipment_id, inspection_id, title, description, priority, assigned_to) VALUES (?,?,?,?,?,?)",
                       (ticket.equipment_id, ticket.inspection_id, ticket.title, ticket.description, ticket.priority, ticket.assigned_to))
        ticket_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": ticket_id, "message": "Work ticket created"}


@app.put("/api/work-tickets/{ticket_id}")
async def update_work_ticket(ticket_id: int, updates: WorkTicketUpdate):
    conn = get_db_connection()
    cursor = conn.cursor()
    if updates.status == 'completed':
        if USE_POSTGRES:
            cursor.execute("""
                UPDATE work_tickets SET status=%s, completed_at=CURRENT_TIMESTAMP, completed_by=%s, completion_notes=%s WHERE id=%s
            """, (updates.status, updates.completed_by, updates.completion_notes, ticket_id))
        else:
            cursor.execute("""
                UPDATE work_tickets SET status=?, completed_at=CURRENT_TIMESTAMP, completed_by=?, completion_notes=? WHERE id=?
            """, (updates.status, updates.completed_by, updates.completion_notes, ticket_id))
    else:
        update_fields = {k: v for k, v in updates.dict().items() if v is not None}
        for field, value in update_fields.items():
            if USE_POSTGRES:
                cursor.execute(f"UPDATE work_tickets SET {field} = %s WHERE id = %s", (value, ticket_id))
            else:
                cursor.execute(f"UPDATE work_tickets SET {field} = ? WHERE id = ?", (value, ticket_id))
    conn.commit()
    conn.close()
    return {"message": "Work ticket updated"}


@app.delete("/api/work-tickets/{ticket_id}")
async def delete_work_ticket(ticket_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    if USE_POSTGRES:
        cursor.execute("DELETE FROM work_tickets WHERE id = %s", (ticket_id,))
    else:
        cursor.execute("DELETE FROM work_tickets WHERE id = ?", (ticket_id,))
    conn.commit()
    conn.close()
    return {"message": "Work ticket deleted"}


# =============================================================================
# Work Ticket Log Endpoints
# =============================================================================

@app.get("/api/work-tickets/{ticket_id}/logs")
async def get_ticket_logs(ticket_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    if USE_POSTGRES:
        cursor.execute(
            "SELECT * FROM work_ticket_logs WHERE ticket_id = %s ORDER BY created_at ASC",
            (ticket_id,)
        )
    else:
        cursor.execute(
            "SELECT * FROM work_ticket_logs WHERE ticket_id = ? ORDER BY created_at ASC",
            (ticket_id,)
        )
    logs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return logs


@app.post("/api/work-tickets/{ticket_id}/logs")
async def add_ticket_log(ticket_id: int, log: WorkTicketLogCreate):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify ticket exists
    if USE_POSTGRES:
        cursor.execute("SELECT id, status FROM work_tickets WHERE id = %s", (ticket_id,))
    else:
        cursor.execute("SELECT id, status FROM work_tickets WHERE id = ?", (ticket_id,))
    ticket = cursor.fetchone()
    if not ticket:
        conn.close()
        raise HTTPException(status_code=404, detail="Work ticket not found")

    try:
        # If a new status is provided, update the ticket status
        if log.status and log.status != dict(ticket)['status']:
            if log.status == 'completed':
                if USE_POSTGRES:
                    cursor.execute(
                        "UPDATE work_tickets SET status=%s, completed_at=CURRENT_TIMESTAMP, completed_by=%s WHERE id=%s",
                        (log.status, log.created_by, ticket_id)
                    )
                else:
                    cursor.execute(
                        "UPDATE work_tickets SET status=?, completed_at=CURRENT_TIMESTAMP, completed_by=? WHERE id=?",
                        (log.status, log.created_by, ticket_id)
                    )
            else:
                if USE_POSTGRES:
                    cursor.execute("UPDATE work_tickets SET status=%s WHERE id=%s", (log.status, ticket_id))
                else:
                    cursor.execute("UPDATE work_tickets SET status=? WHERE id=?", (log.status, ticket_id))

        # Insert log entry
        if USE_POSTGRES:
            cursor.execute(
                "INSERT INTO work_ticket_logs (ticket_id, status, note, created_by) VALUES (%s,%s,%s,%s) RETURNING id",
                (ticket_id, log.status, log.note, log.created_by)
            )
            log_id = cursor.fetchone()['id']
        else:
            cursor.execute(
                "INSERT INTO work_ticket_logs (ticket_id, status, note, created_by) VALUES (?,?,?,?)",
                (ticket_id, log.status, log.note, log.created_by)
            )
            log_id = cursor.lastrowid

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

    return {"id": log_id, "message": "Log entry added"}

@app.get("/api/work-tickets/{ticket_id}/photos")
async def get_ticket_photos(ticket_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    if USE_POSTGRES:
        cursor.execute("SELECT id, ticket_id, filename, mime_type, photo_data, uploaded_at FROM work_ticket_photos WHERE ticket_id = %s ORDER BY uploaded_at ASC", (ticket_id,))
    else:
        cursor.execute("SELECT id, ticket_id, filename, mime_type, photo_data, uploaded_at FROM work_ticket_photos WHERE ticket_id = ? ORDER BY uploaded_at ASC", (ticket_id,))
    photos = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return photos


@app.post("/api/work-tickets/{ticket_id}/photos")
async def add_ticket_photo(ticket_id: int, photo: WorkTicketPhotoCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    if USE_POSTGRES:
        cursor.execute("SELECT id FROM work_tickets WHERE id = %s", (ticket_id,))
    else:
        cursor.execute("SELECT id FROM work_tickets WHERE id = ?", (ticket_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Work ticket not found")
    try:
        if USE_POSTGRES:
            cursor.execute("INSERT INTO work_ticket_photos (ticket_id, filename, mime_type, photo_data) VALUES (%s,%s,%s,%s) RETURNING id",
                           (ticket_id, photo.filename, photo.mime_type, photo.photo_data))
            photo_id = cursor.fetchone()['id']
        else:
            cursor.execute("INSERT INTO work_ticket_photos (ticket_id, filename, mime_type, photo_data) VALUES (?,?,?,?)",
                           (ticket_id, photo.filename, photo.mime_type, photo.photo_data))
            photo_id = cursor.lastrowid
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
    return {"id": photo_id, "message": "Photo uploaded successfully"}


@app.delete("/api/work-tickets/{ticket_id}/photos/{photo_id}")
async def delete_ticket_photo(ticket_id: int, photo_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    if USE_POSTGRES:
        cursor.execute("DELETE FROM work_ticket_photos WHERE id = %s AND ticket_id = %s", (photo_id, ticket_id))
    else:
        cursor.execute("DELETE FROM work_ticket_photos WHERE id = ? AND ticket_id = ?", (photo_id, ticket_id))
    conn.commit()
    conn.close()
    return {"message": "Photo deleted"}


# =============================================================================
# Dashboard / Stats
# =============================================================================

@app.get("/api/dashboard")
async def get_dashboard():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT category, COUNT(*) as count FROM equipment WHERE is_active = TRUE GROUP BY category" if USE_POSTGRES
                   else "SELECT category, COUNT(*) as count FROM equipment WHERE is_active = 1 GROUP BY category")
    equipment_by_category = {row['category']: row['count'] for row in cursor.fetchall()}
    cursor.execute("SELECT COUNT(*) as count FROM work_tickets WHERE status = 'open'")
    result = cursor.fetchone()
    open_tickets = result['count'] if USE_POSTGRES else result[0]
    cursor.execute("SELECT COUNT(*) as count FROM work_tickets WHERE status = 'open' AND priority = 'high'")
    result = cursor.fetchone()
    high_priority = result['count'] if USE_POSTGRES else result[0]
    cursor.execute("""
        SELECT i.*, e.equipment_id as equipment_code, e.equipment_type
        FROM inspections i JOIN equipment e ON i.equipment_id = e.id
        ORDER BY i.created_at DESC LIMIT 5
    """)
    recent_inspections = [dict(row) for row in cursor.fetchall()]
    cursor.execute("""
        SELECT e.*, (SELECT MAX(inspection_date) FROM inspections WHERE equipment_id = e.id) as last_inspection
        FROM equipment e WHERE e.is_active = TRUE ORDER BY last_inspection ASC NULLS FIRST LIMIT 10
    """ if USE_POSTGRES else """
        SELECT e.*, (SELECT MAX(inspection_date) FROM inspections WHERE equipment_id = e.id) as last_inspection
        FROM equipment e WHERE e.is_active = 1 ORDER BY last_inspection ASC LIMIT 10
    """)
    equipment_status = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"equipment_by_category": equipment_by_category, "open_work_tickets": open_tickets,
            "high_priority_tickets": high_priority, "recent_inspections": recent_inspections, "equipment_status": equipment_status}


# =============================================================================
# Static Files / SPA
# =============================================================================

@app.get("/api/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/")
async def root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "SSE Equipment Inspection System", "version": "1.0.0", "docs": "/docs"}

@app.get("/{path:path}")
async def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=404)
    file = STATIC_DIR / path
    if file.exists() and file.is_file():
        return FileResponse(file)
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "SSE Equipment Inspection System", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
