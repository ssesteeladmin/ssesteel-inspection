"""
SSE Calibration Tracking Module - API Routes
Add this file to: backend/app/api/calibration.py
Then import and include in your main.py

UPDATED to match SSE's actual calibration workbook fields
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime, timedelta
from enum import Enum
import os
import json

router = APIRouter(prefix="/api/calibration", tags=["calibration"])

# ============================================================
# MODELS
# ============================================================

class InstrumentCategory(str, Enum):
    MASTER_STANDARD = "master_standard"
    QC_GAGE = "qc_gage"
    WELDING = "welding"
    MEASUREMENT = "measurement"
    TORQUE = "torque"
    PRESSURE = "pressure"
    ELECTRICAL = "electrical"
    OTHER = "other"

class CalibrationStatus(str, Enum):
    CURRENT = "current"
    DUE_SOON = "due_soon"
    OVERDUE = "overdue"
    OUT_OF_SERVICE = "out_of_service"

class InstrumentCreate(BaseModel):
    instrument_id: str           # e.g., "WM-001", "MS-002", "QC-S1"
    name: str                    # e.g., "Welding Machine", "Master Tape 26'"
    category: InstrumentCategory
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    serial_number: Optional[str] = None
    location: Optional[str] = "Shop"
    assigned_to: Optional[str] = None          # Who has it - "Steve P", "SSE", etc.
    calibration_standard: Optional[str] = None  # What standard it's calibrated against
    accuracy_criteria: Optional[str] = None     # e.g., "+/- 1/16\"", "Zero Deviation"
    calibration_vendor: Optional[str] = None
    calibration_interval_days: int = 365
    cal_frequency_label: Optional[str] = None   # "6 Months", "12 Months", "25 Years"
    notes: Optional[str] = None

class InstrumentUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[InstrumentCategory] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    serial_number: Optional[str] = None
    location: Optional[str] = None
    assigned_to: Optional[str] = None
    calibration_standard: Optional[str] = None
    accuracy_criteria: Optional[str] = None
    calibration_vendor: Optional[str] = None
    calibration_interval_days: Optional[int] = None
    cal_frequency_label: Optional[str] = None
    notes: Optional[str] = None
    active: Optional[bool] = None

class CalibrationRecordCreate(BaseModel):
    instrument_db_id: int
    calibration_date: date
    expiration_date: date
    performed_by: str
    vendor: Optional[str] = None
    certificate_number: Optional[str] = None
    standard_used: Optional[str] = None         # "NIST Cert #12345", "Gage Blocks MS-001"
    actual_reading: Optional[str] = None        # "200.0A", "5'0\", 10'0\"..."
    acceptance_criteria: Optional[str] = None   # "+/- 0.1A", "+/- 1/16\""
    result: str = "pass"                        # pass, fail, adjusted
    cost: Optional[float] = None
    notes: Optional[str] = None

class ReminderRecipientCreate(BaseModel):
    email: str
    name: str
    notify_30_day: bool = True
    notify_14_day: bool = True
    notify_7_day: bool = True
    notify_overdue: bool = True

# ============================================================
# DATABASE SETUP
# ============================================================

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_POSTGRES = DATABASE_URL.startswith("postgresql") if DATABASE_URL else False

def get_db():
    if USE_POSTGRES:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
    else:
        import sqlite3
        conn = sqlite3.connect("inspections.db")
        conn.row_factory = sqlite3.Row
        return conn

def ph(index=None):
    return "%s" if USE_POSTGRES else "?"

def serial_type():
    return "SERIAL" if USE_POSTGRES else "INTEGER"

def bool_type():
    return "BOOLEAN DEFAULT TRUE" if USE_POSTGRES else "INTEGER DEFAULT 1"

def timestamp_default():
    return "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" if USE_POSTGRES else "TEXT DEFAULT (datetime('now'))"

# ============================================================
# TABLE CREATION
# ============================================================

def init_calibration_tables():
    """Create calibration tables if they don't exist."""
    conn = get_db()
    cur = conn.cursor()
    
    s = serial_type()
    b = bool_type()
    ts = timestamp_default()
    
    # Instruments table - matches SSE workbook fields
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS calibration_instruments (
            id {s} PRIMARY KEY,
            instrument_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'other',
            manufacturer TEXT,
            model_number TEXT,
            serial_number TEXT,
            location TEXT DEFAULT 'Shop',
            assigned_to TEXT,
            calibration_standard TEXT,
            accuracy_criteria TEXT,
            calibration_vendor TEXT,
            calibration_interval_days INTEGER DEFAULT 365,
            cal_frequency_label TEXT,
            notes TEXT,
            active {b},
            created_at {ts},
            updated_at {ts}
        )
    """)
    
    # Calibration records table - matches SSE history log
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS calibration_records (
            id {s} PRIMARY KEY,
            instrument_id INTEGER NOT NULL,
            calibration_date DATE NOT NULL,
            expiration_date DATE NOT NULL,
            performed_by TEXT NOT NULL,
            vendor TEXT,
            certificate_number TEXT,
            standard_used TEXT,
            actual_reading TEXT,
            acceptance_criteria TEXT,
            result TEXT DEFAULT 'pass',
            cost REAL,
            notes TEXT,
            created_at {ts},
            FOREIGN KEY (instrument_id) REFERENCES calibration_instruments(id)
        )
    """)
    
    # Out of tolerance log - matches SSE OOT log
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS calibration_oot_log (
            id {s} PRIMARY KEY,
            oot_id TEXT UNIQUE,
            date_found DATE NOT NULL,
            instrument_id INTEGER NOT NULL,
            discrepancy TEXT NOT NULL,
            amount_oot TEXT,
            last_valid_cal DATE,
            products_affected TEXT,
            impact_assessment TEXT,
            reinspect_required TEXT,
            action_taken TEXT,
            disposition TEXT DEFAULT 'open',
            assessed_by TEXT,
            date_closed DATE,
            created_at {ts},
            FOREIGN KEY (instrument_id) REFERENCES calibration_instruments(id)
        )
    """)
    
    # Reminder recipients table
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS calibration_reminder_recipients (
            id {s} PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            notify_30_day {b},
            notify_14_day {b},
            notify_7_day {b},
            notify_overdue {b},
            active {b},
            created_at {ts}
        )
    """)
    
    # Reminder log table
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS calibration_reminder_log (
            id {s} PRIMARY KEY,
            instrument_id INTEGER NOT NULL,
            recipient_email TEXT NOT NULL,
            reminder_type TEXT NOT NULL,
            sent_at {ts},
            FOREIGN KEY (instrument_id) REFERENCES calibration_instruments(id)
        )
    """)
    
    conn.commit()
    conn.close()
    print("Calibration tables initialized")

# Initialize on import
init_calibration_tables()

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def row_to_dict(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    return dict(row)

def calculate_status(expiration_date_str):
    if expiration_date_str is None:
        return "overdue"
    if isinstance(expiration_date_str, date):
        exp = expiration_date_str
    else:
        exp = datetime.strptime(str(expiration_date_str)[:10], "%Y-%m-%d").date()
    
    today = date.today()
    days_remaining = (exp - today).days
    
    if days_remaining < 0:
        return "overdue"
    elif days_remaining <= 30:
        return "due_soon"
    else:
        return "current"

def get_instrument_with_status(row):
    d = row_to_dict(row)
    
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    cur.execute(f"""
        SELECT * FROM calibration_records 
        WHERE instrument_id = {p}
        ORDER BY calibration_date DESC LIMIT 1
    """, (d['id'],))
    
    latest = cur.fetchone()
    conn.close()
    
    if latest:
        latest = row_to_dict(latest)
        d['last_calibration_date'] = str(latest['calibration_date'])[:10]
        d['expiration_date'] = str(latest['expiration_date'])[:10]
        d['certificate_number'] = latest.get('certificate_number')
        d['last_performed_by'] = latest.get('performed_by')
        d['last_standard_used'] = latest.get('standard_used')
        d['last_result'] = latest.get('result')
        d['status'] = calculate_status(latest['expiration_date'])
        
        exp = datetime.strptime(str(latest['expiration_date'])[:10], "%Y-%m-%d").date()
        d['days_remaining'] = (exp - date.today()).days
    else:
        d['last_calibration_date'] = None
        d['expiration_date'] = None
        d['certificate_number'] = None
        d['last_performed_by'] = None
        d['last_standard_used'] = None
        d['last_result'] = None
        d['status'] = "overdue"
        d['days_remaining'] = -999
    
    return d

# ============================================================
# INSTRUMENT ENDPOINTS
# ============================================================

@router.get("/instruments")
def list_instruments(active_only: bool = True, category: str = None):
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    query = "SELECT * FROM calibration_instruments"
    conditions = []
    params = []
    
    if active_only:
        conditions.append("active = true")
    if category and category != 'all':
        conditions.append(f"category = {p}")
        params.append(category)
    
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY category, instrument_id"
    
    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    conn.close()
    
    instruments = [get_instrument_with_status(r) for r in rows]
    
    summary = {
        "total": len(instruments),
        "current": sum(1 for i in instruments if i['status'] == 'current'),
        "due_soon": sum(1 for i in instruments if i['status'] == 'due_soon'),
        "overdue": sum(1 for i in instruments if i['status'] == 'overdue'),
    }
    
    return {"instruments": instruments, "summary": summary}


@router.post("/instruments")
def create_instrument(data: InstrumentCreate):
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    try:
        cur.execute(f"""
            INSERT INTO calibration_instruments 
            (instrument_id, name, category, manufacturer, model_number, serial_number,
             location, assigned_to, calibration_standard, accuracy_criteria,
             calibration_vendor, calibration_interval_days, cal_frequency_label, notes)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """, (
            data.instrument_id, data.name, data.category.value,
            data.manufacturer, data.model_number, data.serial_number,
            data.location, data.assigned_to, data.calibration_standard,
            data.accuracy_criteria, data.calibration_vendor,
            data.calibration_interval_days, data.cal_frequency_label, data.notes
        ))
        conn.commit()
        
        cur.execute(f"SELECT * FROM calibration_instruments WHERE instrument_id = {p}", (data.instrument_id,))
        row = cur.fetchone()
        conn.close()
        
        return get_instrument_with_status(row)
    except Exception as e:
        conn.rollback()
        conn.close()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(status_code=400, detail=f"Instrument ID '{data.instrument_id}' already exists")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/instruments/{instrument_id}")
def get_instrument(instrument_id: str):
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    cur.execute(f"SELECT * FROM calibration_instruments WHERE instrument_id = {p}", (instrument_id,))
    row = cur.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    instrument = get_instrument_with_status(row)
    
    cur.execute(f"""
        SELECT * FROM calibration_records 
        WHERE instrument_id = {p}
        ORDER BY calibration_date DESC
    """, (instrument['id'],))
    records = [row_to_dict(r) for r in cur.fetchall()]
    
    # Get OOT records
    cur.execute(f"""
        SELECT * FROM calibration_oot_log
        WHERE instrument_id = {p}
        ORDER BY date_found DESC
    """, (instrument['id'],))
    oot_records = [row_to_dict(r) for r in cur.fetchall()]
    
    conn.close()
    
    instrument['calibration_history'] = records
    instrument['oot_history'] = oot_records
    return instrument


@router.put("/instruments/{instrument_id}")
def update_instrument(instrument_id: str, data: InstrumentUpdate):
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    updates = []
    values = []
    
    for field, value in data.dict(exclude_unset=True).items():
        if value is not None:
            if field == 'category':
                value = value.value
            updates.append(f"{field} = {p}")
            values.append(value)
    
    if not updates:
        conn.close()
        raise HTTPException(status_code=400, detail="No fields to update")
    
    values.append(instrument_id)
    
    cur.execute(f"""
        UPDATE calibration_instruments 
        SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP
        WHERE instrument_id = {p}
    """, tuple(values))
    
    conn.commit()
    
    cur.execute(f"SELECT * FROM calibration_instruments WHERE instrument_id = {p}", (instrument_id,))
    row = cur.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    return get_instrument_with_status(row)


@router.delete("/instruments/{instrument_id}")
def delete_instrument(instrument_id: str):
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    cur.execute(f"UPDATE calibration_instruments SET active = false WHERE instrument_id = {p}", (instrument_id,))
    conn.commit()
    conn.close()
    return {"message": f"Instrument {instrument_id} deactivated"}

# ============================================================
# CALIBRATION RECORD ENDPOINTS
# ============================================================

@router.post("/records")
def create_calibration_record(data: CalibrationRecordCreate):
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    cur.execute(f"SELECT id FROM calibration_instruments WHERE id = {p}", (data.instrument_db_id,))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    cur.execute(f"""
        INSERT INTO calibration_records 
        (instrument_id, calibration_date, expiration_date, performed_by,
         vendor, certificate_number, standard_used, actual_reading,
         acceptance_criteria, result, cost, notes)
        VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        data.instrument_db_id, str(data.calibration_date), str(data.expiration_date),
        data.performed_by, data.vendor, data.certificate_number,
        data.standard_used, data.actual_reading, data.acceptance_criteria,
        data.result, data.cost, data.notes
    ))
    
    conn.commit()
    conn.close()
    
    return {"message": "Calibration record added successfully"}


@router.get("/records/{instrument_id}")
def get_calibration_records(instrument_id: str):
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    cur.execute(f"SELECT id FROM calibration_instruments WHERE instrument_id = {p}", (instrument_id,))
    inst = cur.fetchone()
    if not inst:
        conn.close()
        raise HTTPException(status_code=404, detail="Instrument not found")
    inst = row_to_dict(inst)
    
    cur.execute(f"""
        SELECT * FROM calibration_records 
        WHERE instrument_id = {p}
        ORDER BY calibration_date DESC
    """, (inst['id'],))
    records = [row_to_dict(r) for r in cur.fetchall()]
    conn.close()
    
    return {"records": records}

# ============================================================
# OUT OF TOLERANCE ENDPOINTS
# ============================================================

class OOTCreate(BaseModel):
    instrument_db_id: int
    date_found: date
    discrepancy: str
    amount_oot: Optional[str] = None
    last_valid_cal: Optional[date] = None
    products_affected: Optional[str] = None
    impact_assessment: Optional[str] = None
    reinspect_required: Optional[str] = None
    action_taken: Optional[str] = None
    assessed_by: Optional[str] = None

@router.post("/oot")
def create_oot_record(data: OOTCreate):
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    # Generate OOT ID
    year = data.date_found.year
    cur.execute(f"SELECT COUNT(*) as cnt FROM calibration_oot_log WHERE oot_id LIKE {p}", (f"OOT-{year}-%",))
    count = row_to_dict(cur.fetchone())['cnt']
    oot_id = f"OOT-{year}-{count + 1:03d}"
    
    cur.execute(f"""
        INSERT INTO calibration_oot_log
        (oot_id, date_found, instrument_id, discrepancy, amount_oot, last_valid_cal,
         products_affected, impact_assessment, reinspect_required, action_taken, assessed_by)
        VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        oot_id, str(data.date_found), data.instrument_db_id, data.discrepancy,
        data.amount_oot, str(data.last_valid_cal) if data.last_valid_cal else None,
        data.products_affected, data.impact_assessment, data.reinspect_required,
        data.action_taken, data.assessed_by
    ))
    conn.commit()
    conn.close()
    
    return {"message": f"OOT record {oot_id} created", "oot_id": oot_id}


@router.get("/oot")
def list_oot_records(status: str = None):
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    if status:
        cur.execute(f"SELECT o.*, i.instrument_id as equip_id, i.name as equip_name FROM calibration_oot_log o JOIN calibration_instruments i ON o.instrument_id = i.id WHERE o.disposition = {p} ORDER BY o.date_found DESC", (status,))
    else:
        cur.execute("SELECT o.*, i.instrument_id as equip_id, i.name as equip_name FROM calibration_oot_log o JOIN calibration_instruments i ON o.instrument_id = i.id ORDER BY o.date_found DESC")
    
    records = [row_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return {"records": records}


@router.put("/oot/{oot_id}/close")
def close_oot_record(oot_id: str, disposition: str = "closed", date_closed: str = None):
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    close_date = date_closed or str(date.today())
    cur.execute(f"UPDATE calibration_oot_log SET disposition = {p}, date_closed = {p} WHERE oot_id = {p}", 
                (disposition, close_date, oot_id))
    conn.commit()
    conn.close()
    return {"message": f"OOT {oot_id} closed"}

# ============================================================
# DASHBOARD ENDPOINT
# ============================================================

@router.get("/dashboard")
def calibration_dashboard():
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM calibration_instruments WHERE active = true ORDER BY category, instrument_id")
    rows = cur.fetchall()
    
    instruments = [get_instrument_with_status(r) for r in rows]
    
    overdue = [i for i in instruments if i['status'] == 'overdue']
    due_soon = [i for i in instruments if i['status'] == 'due_soon']
    current = [i for i in instruments if i['status'] == 'current']
    
    by_category = {}
    for inst in instruments:
        cat = inst.get('category', 'other')
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(inst)
    
    # By assigned person
    by_person = {}
    for inst in instruments:
        person = inst.get('assigned_to', 'Unassigned') or 'Unassigned'
        if person not in by_person:
            by_person[person] = []
        by_person[person].append(inst)
    
    upcoming = sorted(
        [i for i in instruments if i['days_remaining'] is not None and 0 <= i['days_remaining'] <= 90],
        key=lambda x: x['days_remaining']
    )
    
    # Open OOT records
    cur.execute("SELECT COUNT(*) as cnt FROM calibration_oot_log WHERE disposition = 'open'")
    open_oot = row_to_dict(cur.fetchone())['cnt']
    
    conn.close()
    
    return {
        "summary": {
            "total": len(instruments),
            "current": len(current),
            "due_soon": len(due_soon),
            "overdue": len(overdue),
            "open_oot": open_oot,
            "compliance_rate": round(len(current) / max(len(instruments), 1) * 100, 1)
        },
        "overdue": overdue,
        "due_soon": due_soon,
        "current": current,
        "by_category": by_category,
        "by_person": by_person,
        "upcoming_expirations": upcoming
    }

# ============================================================
# REMINDER RECIPIENTS
# ============================================================

@router.get("/reminders/recipients")
def list_recipients():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM calibration_reminder_recipients WHERE active = true")
    rows = [row_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return {"recipients": rows}


@router.post("/reminders/recipients")
def add_recipient(data: ReminderRecipientCreate):
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    try:
        cur.execute(f"""
            INSERT INTO calibration_reminder_recipients 
            (email, name, notify_30_day, notify_14_day, notify_7_day, notify_overdue)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p})
        """, (
            data.email, data.name, data.notify_30_day,
            data.notify_14_day, data.notify_7_day, data.notify_overdue
        ))
        conn.commit()
        conn.close()
        return {"message": f"Added {data.name} ({data.email}) to reminder list"}
    except Exception as e:
        conn.rollback()
        conn.close()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(status_code=400, detail="Email already registered")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/reminders/recipients/{email}")
def remove_recipient(email: str):
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    cur.execute(f"UPDATE calibration_reminder_recipients SET active = false WHERE email = {p}", (email,))
    conn.commit()
    conn.close()
    return {"message": f"Removed {email} from reminder list"}

# ============================================================
# REMINDER CHECK ENDPOINT
# ============================================================

@router.get("/reminders/check")
def check_reminders():
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    cur.execute("SELECT * FROM calibration_instruments WHERE active = true")
    instruments = [get_instrument_with_status(row_to_dict(r)) for r in cur.fetchall()]
    
    cur.execute("SELECT * FROM calibration_reminder_recipients WHERE active = true")
    recipients = [row_to_dict(r) for r in cur.fetchall()]
    
    notifications = []
    today = date.today()
    
    for inst in instruments:
        days = inst.get('days_remaining', -999)
        
        reminder_type = None
        if days < 0:
            reminder_type = "overdue"
        elif days <= 7:
            reminder_type = "7_day"
        elif days <= 14:
            reminder_type = "14_day"
        elif days <= 30:
            reminder_type = "30_day"
        
        if reminder_type:
            cur.execute(f"""
                SELECT id FROM calibration_reminder_log 
                WHERE instrument_id = {p} AND reminder_type = {p}
                AND DATE(sent_at) = {p}
            """, (inst['id'], reminder_type, str(today)))
            
            already_sent = cur.fetchone()
            
            if not already_sent:
                for recip in recipients:
                    should_notify = False
                    if reminder_type == "overdue" and recip.get('notify_overdue'):
                        should_notify = True
                    elif reminder_type == "7_day" and recip.get('notify_7_day'):
                        should_notify = True
                    elif reminder_type == "14_day" and recip.get('notify_14_day'):
                        should_notify = True
                    elif reminder_type == "30_day" and recip.get('notify_30_day'):
                        should_notify = True
                    
                    if should_notify:
                        notifications.append({
                            "instrument": inst['instrument_id'],
                            "instrument_name": inst['name'],
                            "assigned_to": inst.get('assigned_to'),
                            "days_remaining": days,
                            "expiration_date": inst.get('expiration_date'),
                            "reminder_type": reminder_type,
                            "recipient_name": recip['name'],
                            "recipient_email": recip['email']
                        })
    
    conn.close()
    
    return {
        "date": str(today),
        "notifications_needed": len(notifications),
        "notifications": notifications
    }


@router.post("/reminders/log")
def log_reminder_sent(instrument_id: int, reminder_type: str, recipient_email: str):
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    cur.execute(f"""
        INSERT INTO calibration_reminder_log (instrument_id, recipient_email, reminder_type)
        VALUES ({p}, {p}, {p})
    """, (instrument_id, recipient_email, reminder_type))
    conn.commit()
    conn.close()
    return {"message": "Reminder logged"}

# ============================================================
# SEED DATA ENDPOINT - Load SSE's existing instruments
# ============================================================

@router.post("/seed")
def seed_sse_data():
    """
    One-time endpoint to load all of SSE's existing calibration data.
    Call this once after initial deployment to populate the database.
    """
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    # Check if data already exists
    cur.execute("SELECT COUNT(*) as cnt FROM calibration_instruments")
    existing = row_to_dict(cur.fetchone())['cnt']
    if existing > 0:
        conn.close()
        return {"message": f"Database already has {existing} instruments. Skipping seed.", "seeded": False}
    
    # =========================================
    # MASTER STANDARDS
    # =========================================
    master_standards = [
        ("MS-001", "Gage Blocks Set", "Starrett", None, "8826", "QC Office", "QC Manager",
         "NIST Traceable", "ASME B89.1.9-2002", "Outsourced", 9131, "25 Years", "Primary standard",
         "2010-12-15", "2035-12-16"),
        ("MS-002", "Master Tape 26'", "Starrett", None, "17507723", "QC Office", "QC Manager",
         "NIST Traceable", "+/- 1/16\"", "Outsourced", 365, "12 Months", "Calibrates shop tapes",
         "2025-02-21", "2026-02-21"),
        ("MS-003", "Master Fillet Gage", "V-WAC", None, "2396", "QC Office", "QC Manager",
         "Gage Blocks MS-001", "+/- 1/32\"", "Blair M", 365, "12 Months", "Calibrates shop fillet gages",
         "2025-02-21", "2026-02-21"),
        ("MS-004", "Master V-Wac Gage", "V-WAC", None, "5823", "QC Office", "QC Manager",
         "Gage Blocks MS-001", "+/- 1/32\"", "Blair M", 365, "12 Months", "Calibrates shop V-Wac",
         "2025-02-21", "2026-02-21"),
        ("MS-005", "Master Framing Square", "Stanley", None, "sq7732", "QC Office", "QC Manager",
         "Master Tape MS-002", "3-4-5 Rule", "Blair M", 365, "12 Months", "Calibrates shop squares",
         "2025-02-21", "2026-02-21"),
        ("MS-006", "IR Thermometer", "Fluke", None, "72617", "QC Office", "QC Manager",
         "NIST Traceable", "Per Mfg Spec", "Outsourced", 365, "12 Months", "Preheat verification",
         "2025-02-21", "2026-02-21"),
        ("MS-007", "Clamp Meter", "Fluke", None, "B87A915100249", "QC Office", "QC Manager",
         "NIST Traceable", "Per Mfg Spec", "Outsourced", 365, "12 Months", "Welder amp verification",
         "2025-02-21", "2026-02-21"),
        ("MS-008", "PosiTector DFT Gage", "DeFelsko", None, "814724", "QC Office", "QC Manager",
         "NIST Traceable", "Per Mfg Spec", "Outsourced", 365, "12 Months", "Coating thickness",
         "2025-02-21", "2026-02-21"),
    ]
    
    # =========================================
    # QC GAGES - Steve P
    # =========================================
    qc_steve = [
        ("QC-S1", "Tape Measure", "DeWalt", None, "S1-TAPE", "Shop", "Steve P",
         "Master MS-002", "+/- 1/16\"", "Blair M", 183, "6 Months", None,
         "2025-11-24", "2026-05-24"),
        ("QC-S2", "Weld Fillet Gage", "V-WAC", None, "S2-FG", "Shop", "Steve P",
         "Master MS-003", "Zero Deviation", "Blair M", 365, "12 Months", None,
         "2025-02-15", "2026-02-15"),
        ("QC-S3", "V-Wac Gage", "V-WAC", None, "S3-VW", "Shop", "Steve P",
         "Master MS-004", "Zero Deviation", "Blair M", 365, "12 Months", None,
         "2025-02-15", "2026-02-15"),
        ("QC-S4", "Framing Square", "Empire", None, "S4-SQ", "Shop", "Steve P",
         "Master MS-002", "3-4-5 Rule", "Blair M", 183, "6 Months", None,
         "2025-08-07", "2026-02-07"),
    ]
    
    # =========================================
    # QC GAGES - Chad J
    # =========================================
    qc_chad = [
        ("QC-CJ1", "Tape Measure", "DeWalt", None, "CJ1-TAPE", "Shop", "Chad J",
         "Master MS-002", "+/- 1/16\"", "Blair M", 183, "6 Months", None,
         "2025-11-24", "2026-05-24"),
        ("QC-CJ2", "Weld Fillet Gage", "V-WAC", None, "CJ2-FG", "Shop", "Chad J",
         "Master MS-003", "Zero Deviation", "Blair M", 365, "12 Months", None,
         "2025-07-08", "2026-07-08"),
        ("QC-CJ3", "V-Wac Gage", "V-WAC", None, "CJ3-VW", "Shop", "Chad J",
         "Master MS-004", "Zero Deviation", "Blair M", 365, "12 Months", None,
         "2025-02-15", "2026-02-15"),
        ("QC-CJ4", "Framing Square", "Empire", None, "CJ4-SQ", "Shop", "Chad J",
         "Master MS-002", "3-4-5 Rule", "Steven P", 183, "6 Months", None,
         "2026-01-16", "2026-06-16"),
    ]
    
    # =========================================
    # QC GAGES - Shawn M
    # =========================================
    qc_shawn = [
        ("QC-SM1", "Tape Measure", "DeWalt", None, "SM1-TAPE", "Shop", "Shawn M",
         "Master MS-002", "+/- 1/16\"", "Blair M", 183, "6 Months", None,
         "2025-11-24", "2026-05-24"),
        ("QC-SM2", "Weld Fillet Gage", "V-WAC", None, "SM2-FG", "Shop", "Shawn M",
         "Master MS-003", "Zero Deviation", "Blair M", 365, "12 Months", None,
         "2025-02-15", "2026-02-15"),
        ("QC-SM3", "V-Wac Gage", "V-WAC", None, "SM3-VW", "Shop", "Shawn M",
         "Master MS-004", "Zero Deviation", "Blair M", 365, "12 Months", None,
         "2025-02-15", "2026-02-15"),
        ("QC-SM4", "Framing Square", "Empire", None, "SM4-SQ", "Shop", "Shawn M",
         "Master MS-002", "3-4-5 Rule", "Blair M", 183, "6 Months", None,
         "2025-08-07", "2026-02-07"),
    ]
    
    # =========================================
    # QC GAGES - Chris A
    # =========================================
    qc_chris = [
        ("QC-CA1", "Tape Measure", "DeWalt", None, "CA1-TAPE", "Shop", "Chris A.",
         "Master MS-002", "+/- 1/16\"", "Blair M", 183, "6 Months", None,
         "2025-11-24", "2026-05-24"),
        ("QC-CA2", "Weld Fillet Gage", "V-WAC", None, "CA2-FG", "Shop", "Chris A.",
         "Master MS-003", "Zero Deviation", "Blair M", 365, "12 Months", None,
         "2025-02-15", "2026-02-15"),
        ("QC-CA3", "V-Wac Gage", "V-WAC", None, "CA3-VW", "Shop", "Chris A.",
         "Master MS-004", "Zero Deviation", "Blair M", 365, "12 Months", None,
         "2025-02-15", "2026-02-15"),
        ("QC-CA4", "Framing Square", "Empire", None, "CA4-SQ", "Shop", "Chris A.",
         "Master MS-002", "3-4-5 Rule", "Blair M", 183, "6 Months", None,
         "2025-08-15", "2026-02-15"),
    ]
    
    # =========================================
    # WELDING MACHINES
    # =========================================
    welders = [
        ("WM-001", "NC463062N"), ("WM-002", "U1230405112"), ("WM-003", "NE040051N"),
        ("WM-004", "NA410086N"), ("WM-005", "MG193015N"), ("WM-006", "MH103031N"),
        ("WM-007", "MG193013N"), ("WM-008", "MH153089N"), ("WM-009", "MH083078N"),
        ("WM-010", "MH153090N"), ("WM-011", "MH193043N"), ("WM-012", "MA251021N"),
        ("WM-013", "MG193014N"), ("WM-014", "NA410161N"), ("WM-015", "NE453081N"),
        ("WM-016", "NE453079N"), ("WM-017", "ND163101N"), ("WM-018", "NE443012N"),
    ]
    
    inserted = 0
    
    # Insert Master Standards
    for ms in master_standards:
        (eid, name, mfg, model, serial, loc, assigned, standard, accuracy,
         vendor, interval, freq_label, notes, last_cal, next_due) = ms
        
        cur.execute(f"""
            INSERT INTO calibration_instruments
            (instrument_id, name, category, manufacturer, serial_number, location,
             assigned_to, calibration_standard, accuracy_criteria, calibration_vendor,
             calibration_interval_days, cal_frequency_label, notes)
            VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
        """, (eid, name, "master_standard", mfg, serial, loc, assigned,
              standard, accuracy, vendor, interval, freq_label, notes))
        
        # Get the id
        cur.execute(f"SELECT id FROM calibration_instruments WHERE instrument_id = {p}", (eid,))
        inst_id = row_to_dict(cur.fetchone())['id']
        
        # Insert calibration record
        cur.execute(f"""
            INSERT INTO calibration_records
            (instrument_id, calibration_date, expiration_date, performed_by, vendor, result)
            VALUES ({p},{p},{p},{p},{p},{p})
        """, (inst_id, last_cal, next_due, vendor, vendor, "pass"))
        
        inserted += 1
    
    # Insert QC Gages
    for group in [qc_steve, qc_chad, qc_shawn, qc_chris]:
        for item in group:
            (eid, name, mfg, model, serial, loc, assigned, standard, accuracy,
             vendor, interval, freq_label, notes, last_cal, next_due) = item
            
            cur.execute(f"""
                INSERT INTO calibration_instruments
                (instrument_id, name, category, manufacturer, serial_number, location,
                 assigned_to, calibration_standard, accuracy_criteria, calibration_vendor,
                 calibration_interval_days, cal_frequency_label, notes)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
            """, (eid, name, "qc_gage", mfg, serial, loc, assigned,
                  standard, accuracy, vendor, interval, freq_label, notes))
            
            cur.execute(f"SELECT id FROM calibration_instruments WHERE instrument_id = {p}", (eid,))
            inst_id = row_to_dict(cur.fetchone())['id']
            
            cur.execute(f"""
                INSERT INTO calibration_records
                (instrument_id, calibration_date, expiration_date, performed_by, 
                 standard_used, result)
                VALUES ({p},{p},{p},{p},{p},{p})
            """, (inst_id, last_cal, next_due, vendor, standard, "pass"))
            
            inserted += 1
    
    # Insert Welding Machines
    for wm_id, serial in welders:
        cur.execute(f"""
            INSERT INTO calibration_instruments
            (instrument_id, name, category, manufacturer, serial_number, location,
             assigned_to, calibration_standard, accuracy_criteria, calibration_vendor,
             calibration_interval_days, cal_frequency_label, notes)
            VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
        """, (wm_id, "Welding Machine", "welding", "Miller/Lincoln", serial,
              "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", "Outsourced",
              365, "12 Months", None))
        
        cur.execute(f"SELECT id FROM calibration_instruments WHERE instrument_id = {p}", (wm_id,))
        inst_id = row_to_dict(cur.fetchone())['id']
        
        cur.execute(f"""
            INSERT INTO calibration_records
            (instrument_id, calibration_date, expiration_date, performed_by,
             vendor, actual_reading, acceptance_criteria, result)
            VALUES ({p},{p},{p},{p},{p},{p},{p},{p})
        """, (inst_id, "2025-06-02", "2026-06-02", "Outsourced",
              "Outsourced", "200.0A at 200A set", "+/- 0.1A", "pass"))
        
        inserted += 1
    
    conn.commit()
    conn.close()
    
    return {
        "message": f"Successfully seeded {inserted} instruments with calibration records",
        "seeded": True,
        "count": inserted
    }

# ============================================================
# AUDIT EXPORT
# ============================================================

@router.get("/export")
def export_calibration_report():
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    cur.execute("SELECT * FROM calibration_instruments WHERE active = true ORDER BY category, instrument_id")
    rows = cur.fetchall()
    
    report = {
        "report_date": str(date.today()),
        "company": "Southern Services & Equipment Inc.",
        "address": "321 Bayou Road, St. Bernard, LA 70085",
        "report_title": "AISC Calibration Compliance Report",
        "instruments": []
    }
    
    for row in rows:
        inst = get_instrument_with_status(row)
        
        cur.execute(f"""
            SELECT calibration_date, expiration_date, performed_by, vendor, 
                   certificate_number, standard_used, actual_reading, 
                   acceptance_criteria, result 
            FROM calibration_records 
            WHERE instrument_id = {p}
            ORDER BY calibration_date DESC
        """, (inst['id'],))
        
        history = [row_to_dict(r) for r in cur.fetchall()]
        
        report["instruments"].append({
            "id": inst['instrument_id'],
            "name": inst['name'],
            "category": inst['category'],
            "serial_number": inst.get('serial_number'),
            "assigned_to": inst.get('assigned_to'),
            "calibration_standard": inst.get('calibration_standard'),
            "accuracy_criteria": inst.get('accuracy_criteria'),
            "status": inst['status'],
            "last_calibration": inst.get('last_calibration_date'),
            "expiration": inst.get('expiration_date'),
            "days_remaining": inst.get('days_remaining'),
            "vendor": inst.get('calibration_vendor'),
            "history": history
        })
    
    conn.close()
    return report

@router.post("/seed-v2")
def seed_calibration_v2():
    """Wipe all calibration data and reseed from the improved workbook."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    # ── Step 1: Add missing columns if they don't exist ──
    new_columns = [
        ("assigned_to", "TEXT"),
        ("calibration_standard", "TEXT"),
        ("accuracy_criteria", "TEXT"),
        ("calibrated_by", "TEXT"),
    ]
    for col_name, col_type in new_columns:
        try:
            cur.execute(f"ALTER TABLE calibration_instruments ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except Exception:
            conn.rollback()
    
    # Add OOT table
    s = serial_type()
    ts = timestamp_default()
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS calibration_oot_log (
            id {s} PRIMARY KEY,
            oot_id TEXT UNIQUE NOT NULL,
            date_found TEXT,
            equipment_id TEXT,
            description TEXT,
            discrepancy TEXT,
            amount_oot TEXT,
            last_valid_cal TEXT,
            products_affected TEXT,
            impact_assessment TEXT,
            reinspect_required TEXT,
            action_taken TEXT,
            disposition TEXT DEFAULT 'Open',
            assessed_by TEXT,
            date_closed TEXT,
            created_at {ts}
        )
    """)
    conn.commit()
    
    # ── Step 2: Wipe existing data ──
    for tbl in ["calibration_certificates", "calibration_records", "calibration_instruments"]:
        try:
            cur.execute(f"DELETE FROM {tbl}")
            conn.commit()
        except Exception:
            conn.rollback()
    try:
        cur.execute("DELETE FROM calibration_oot_log")
    except Exception:
        conn.rollback()
    conn.commit()
    
    # ── Step 3: Seed all 42 instruments ──
    instruments = [
        # Master Standards
        ("MS-001", "Gage Blocks Set", "measurement", "Starrett", "8826", "QC Office", "QC Manager", "NIST Traceable", "ASME B89.1.9-2002", 9125, "Primary standard", "Outsourced"),
        ("MS-002", "Master Tape 35'", "measurement", "Starrett", "25428355", "QC Office", "QC Manager", "NIST Traceable", "+/- 1/16\"", 365, "Calibrates shop tapes", "Outsourced"),
        ("MS-003", "Master Fillet Gage", "measurement", "Atema", "27930", "QC Office", "QC Manager", "Gage Blocks MS-001", "+/- 1/32\"", 365, "Calibrates shop fillet gages", "Blair M"),
        ("MS-004", "Master V-Wac Gage", "measurement", "Atema", "25454", "QC Office", "QC Manager", "Gage Blocks MS-001", "+/- 1/32\"", 365, "Calibrates shop V-Wac", "Blair M"),
        ("MS-005", "Master Framing Square", "measurement", "Stanley", "sq7732", "QC Office", "QC Manager", "Master Tape MS-002", "3-4-5 Rule", 365, "Calibrates shop squares", "Blair M"),
        ("MS-006", "IR Thermometer", "measurement", "Fluke", "72617", "QC Office", "QC Manager", "NIST Traceable", "Per Mfg Spec", 365, "Preheat verification", "Outsourced"),
        ("MS-007", "Clamp Meter", "electrical", "Fluke", "B87A915100249", "QC Office", "QC Manager", "NIST Traceable", "Per Mfg Spec", 365, "Welder amp verification", "Outsourced"),
        ("MS-008", "PosiTector DFT Gage", "measurement", "DeFelsko", "814724", "QC Office", "QC Manager", "NIST Traceable", "Per Mfg Spec", 365, "Coating thickness", "Outsourced"),
        # QC Gages - Steve P
        ("QC-S1", "Tape Measure", "measurement", "DeWalt", "S1-TAPE", "Shop", "Steve P", "Master MS-002", "+/- 1/16\"", 182, None, "Blair M"),
        ("QC-S2", "Weld Fillet Gage", "measurement", "V-WAC", "S2-FG", "Shop", "Steve P", "Master MS-003", "Zero Deviation", 365, None, "Blair M"),
        ("QC-S3", "V-Wac Gage", "measurement", "V-WAC", "S3-VW", "Shop", "Steve P", "Master MS-004", "Zero Deviation", 365, None, "Blair M"),
        ("QC-S4", "Framing Square", "measurement", "Empire", "S4-SQ", "Shop", "Steve P", "Master MS-002", "3-4-5 Rule", 182, None, "Blair M"),
        # QC Gages - Chad J
        ("QC-CJ1", "Tape Measure", "measurement", "DeWalt", "CJ1-TAPE", "Shop", "Chad J", "Master MS-002", "+/- 1/16\"", 182, None, "Blair M"),
        ("QC-CJ2", "Weld Fillet Gage", "measurement", "V-WAC", "CJ2-FG", "Shop", "Chad J", "Master MS-003", "Zero Deviation", 365, None, "Blair M"),
        ("QC-CJ3", "V-Wac Gage", "measurement", "V-WAC", "CJ3-VW", "Shop", "Chad J", "Master MS-004", "Zero Deviation", 365, None, "Blair M"),
        ("QC-CJ4", "Framing Square", "measurement", "Empire", "CJ4-SQ", "Shop", "Chad J", "Master MS-002", "3-4-5 Rule", 182, None, "Steven P"),
        # QC Gages - Shawn M
        ("QC-SM1", "Tape Measure", "measurement", "DeWalt", "SM1-TAPE", "Shop", "Shawn M", "Master MS-002", "+/- 1/16\"", 182, None, "Blair M"),
        ("QC-SM2", "Weld Fillet Gage", "measurement", "V-WAC", "SM2-FG", "Shop", "Shawn M", "Master MS-003", "Zero Deviation", 365, None, "Blair M"),
        ("QC-SM3", "V-Wac Gage", "measurement", "V-WAC", "SM3-VW", "Shop", "Shawn M", "Master MS-004", "Zero Deviation", 365, None, "Blair M"),
        ("QC-SM4", "Framing Square", "measurement", "Empire", "SM4-SQ", "Shop", "Shawn M", "Master MS-002", "3-4-5 Rule", 182, None, "Blair M"),
        # QC Gages - Chris A.
        ("QC-CA1", "Tape Measure", "measurement", "DeWalt", "CA1-TAPE", "Shop", "Chris A.", "Master MS-002", "+/- 1/16\"", 182, None, "Blair M"),
        ("QC-CA2", "Weld Fillet Gage", "measurement", "V-WAC", "CA2-FG", "Shop", "Chris A.", "Master MS-003", "Zero Deviation", 365, None, "Blair M"),
        ("QC-CA3", "V-Wac Gage", "measurement", "V-WAC", "CA3-VW", "Shop", "Chris A.", "Master MS-004", "Zero Deviation", 365, None, "Blair M"),
        ("QC-CA4", "Framing Square", "measurement", "Empire", "CA4-SQ", "Shop", "Chris A.", "Master MS-002", "3-4-5 Rule", 182, None, "Blair M"),
        # Welding Machines
        ("WM-001", "Welding Machine", "welding", "Miller", "NC463062N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 2/22/2026", "Outsourced"),
        ("WM-002", "Welding Machine", "welding", "Lincoln", "U1230405112", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 2/22/2026", "Outsourced"),
        ("WM-003", "Welding Machine", "welding", "Miller", "NE040051N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-004", "Welding Machine", "welding", "Miller", "NA410086N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-005", "Welding Machine", "welding", "Miller", "MG193015N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-006", "Welding Machine", "welding", "Miller", "MH103031N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-007", "Welding Machine", "welding", "Miller", "MG193013N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-008", "Welding Machine", "welding", "Miller", "MH153089N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-009", "Welding Machine", "welding", "Miller", "MH083078N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-010", "Welding Machine", "welding", "Miller", "MH153090N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-011", "Welding Machine", "welding", "Miller", "MH193043N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-012", "Welding Machine", "welding", "Miller", "MA251021N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-013", "Welding Machine", "welding", "Miller", "MG193014N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-014", "Welding Machine", "welding", "Miller", "NA410161N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-015", "Welding Machine", "welding", "Miller", "NE453081N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-016", "Welding Machine", "welding", "Miller", "NE453079N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-017", "Welding Machine", "welding", "Miller", "ND163101N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
        ("WM-018", "Welding Machine", "welding", "Miller", "NE443012N", "Shop Floor", "SSE", "NIST/Mfg Spec", "+/- 0.1A", 365, "90 day due 3/22/2026", "Outsourced"),
    ]
    
    instrument_map = {}  # instrument_id -> db id
    for (iid, name, cat, mfg, sn, loc, assigned, standard, accuracy, interval, notes, cal_by) in instruments:
        cur.execute(f"""
            INSERT INTO calibration_instruments 
            (instrument_id, name, category, manufacturer, serial_number, location,
             assigned_to, calibration_standard, accuracy_criteria, 
             calibration_interval_days, notes, calibrated_by, active)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, true)
        """, (iid, name, cat, mfg, sn, loc, assigned, standard, accuracy, interval, notes, cal_by))
        
        # Get the ID back
        cur.execute(f"SELECT id FROM calibration_instruments WHERE instrument_id = {p}", (iid,))
        row = cur.fetchone()
        instrument_map[iid] = row_to_dict(row)['id']
    
    conn.commit()
    
    # ── Step 4: Seed calibration history records ──
    cal_records = [
        # (cal_event_id, equip_id, cal_date, next_due, standard_used, reading, criteria, result, cal_by, cert_comments)
        ("CAL-2025-001", "MS-002", "2026-02-04", "2027-02-04", "NIST Cert #12345", "Exact match at all intervals", "+/- 1/16\"", "pass", "IIW", "Cert #CAL-2025-0221"),
        ("CAL-2025-002", "MS-003", "2025-02-21", "2026-02-21", "Gage Blocks MS-001", "All leaves match within 1/64\"", "+/- 1/32\"", "pass", "Atema", "Internal cal"),
        ("CAL-2025-003", "MS-004", "2025-02-21", "2026-02-21", "Gage Blocks MS-001", "Zero=0.000\", all sizes match", "+/- 1/32\"", "pass", "Atema", "Internal cal"),
        ("CAL-2025-004", "MS-006", "2026-02-04", "2027-02-04", "NIST Cert #12346", "212F reading=212F actual", "Per Mfg Spec", "pass", "IIW", "Cert #IR-2025-0221"),
        ("CAL-2025-005", "QC-S1", "2025-11-24", "2026-05-24", "Master MS-002", "5'=5', 10'=10', 15'=15', 20'=20'", "+/- 1/16\"", "pass", "Blair M", None),
        ("CAL-2025-006", "QC-S2", "2026-02-15", "2027-02-15", "Master MS-003", "All leaves match master", "Zero Deviation", "pass", "Blair M", None),
        ("CAL-2025-007", "QC-S3", "2026-02-15", "2027-02-15", "Master MS-004", "Zero=0, all sizes match", "Zero Deviation", "pass", "Blair M", None),
        ("CAL-2025-008", "QC-S4", "2026-02-19", "2026-08-19", "Master MS-002", "9-12-15 check = 15.000\"", "3-4-5 exact", "pass", "Blair M", None),
        # Additional cal records for tapes
        ("CAL-2025-009", "QC-CJ1", "2025-11-24", "2026-05-24", "Master MS-002", "5'=5', 10'=10', 15'=15', 20'=20'", "+/- 1/16\"", "pass", "Blair M", None),
        ("CAL-2025-010", "QC-SM1", "2025-11-24", "2026-05-24", "Master MS-002", "5'=5', 10'=10', 15'=15', 20'=20'", "+/- 1/16\"", "pass", "Blair M", None),
        ("CAL-2025-011", "QC-CA1", "2025-11-24", "2026-05-24", "Master MS-002", "5'=5', 10'=10', 15'=15', 20'=20'", "+/- 1/16\"", "pass", "Blair M", None),
        # Fillet gages
        ("CAL-2025-012", "QC-CJ2", "2025-07-08", "2026-07-08", "Master MS-003", "All leaves match master", "Zero Deviation", "pass", "Blair M", None),
        ("CAL-2025-013", "QC-CJ3", "2026-02-15", "2027-02-15", "Master MS-004", "Zero=0, all sizes match", "Zero Deviation", "pass", "Blair M", None),
        ("CAL-2025-014", "QC-SM2", "2026-02-15", "2027-02-15", "Master MS-003", "All leaves match master", "Zero Deviation", "pass", "Blair M", None),
        ("CAL-2025-015", "QC-SM3", "2026-02-15", "2027-02-15", "Master MS-004", "Zero=0, all sizes match", "Zero Deviation", "pass", "Blair M", None),
        ("CAL-2025-016", "QC-SM4", "2026-02-15", "2026-08-15", "Master MS-002", "9-12-15 check = 15.000\"", "3-4-5 exact", "pass", "Blair M", None),
        ("CAL-2025-017", "QC-CA2", "2026-02-15", "2027-02-15", "Master MS-003", "All leaves match master", "Zero Deviation", "pass", "Blair M", None),
        ("CAL-2025-018", "QC-CA3", "2026-02-15", "2027-02-15", "Master MS-004", "Zero=0, all sizes match", "Zero Deviation", "pass", "Blair M", None),
        ("CAL-2025-019", "QC-CA4", "2026-02-15", "2026-08-15", "Master MS-002", "9-12-15 check = 15.000\"", "3-4-5 exact", "pass", "Blair M", None),
        ("CAL-2025-020", "QC-CJ4", "2026-01-16", "2026-07-16", "Master MS-002", "9-12-15 check = 15.000\"", "3-4-5 exact", "pass", "Steven P", None),
        # MS-001 Gage Blocks
        ("CAL-2010-001", "MS-001", "2010-12-15", "2035-12-16", "NIST Traceable", "Full set verified", "ASME B89.1.9-2002", "pass", "Outsourced", "Primary standard - 25yr interval"),
        # MS-005 Master Square
        ("CAL-2025-021", "MS-005", "2026-02-20", "2027-02-20", "Master Tape MS-002", "3-4-5 Rule verified", "3-4-5 Rule", "pass", "Blair M", None),
        # MS-007 Clamp Meter
        ("CAL-2025-022", "MS-007", "2026-02-04", "2027-02-04", "NIST Traceable", "Per Mfg Spec", "Per Mfg Spec", "pass", "Outsourced", "Welder amp verification"),
        # MS-008 DFT Gage
        ("CAL-2025-023", "MS-008", "2026-02-04", "2027-02-04", "NIST Traceable", "Per Mfg Spec", "Per Mfg Spec", "pass", "Outsourced", "Coating thickness"),
        # Welding machines - all calibrated 12/22/2025
        ("CAL-2025-WM01", "WM-001", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 200.0A, Variance 0.0A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM02", "WM-002", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 198.0A, Variance -2.0A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM03", "WM-003", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 200.5A, Variance 0.5A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM04", "WM-004", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 199.5A, Variance -0.5A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM05", "WM-005", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 200.5A, Variance 0.5A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM06", "WM-006", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 200.0A, Variance 0.0A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM07", "WM-007", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 200.0A, Variance 0.0A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM08", "WM-008", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 201.0A, Variance 1.0A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM09", "WM-009", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 200.0A, Variance 0.0A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM10", "WM-010", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 200.0A, Variance 0.0A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM11", "WM-011", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 200.5A, Variance 0.5A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM12", "WM-012", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 200.0A, Variance 0.0A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM13", "WM-013", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 199.0A, Variance -1.0A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM14", "WM-014", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 200.5A, Variance 0.5A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM15", "WM-015", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 200.0A, Variance 0.0A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM16", "WM-016", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 200.0A, Variance 0.0A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM17", "WM-017", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 199.5A, Variance -0.5A", "+/- 0.1A", "pass", "Outsourced", None),
        ("CAL-2025-WM18", "WM-018", "2025-12-22", "2026-12-22", "Fluke Clamp Meter", "Set 200A, Measured 200.0A, Variance 0.0A", "+/- 0.1A", "pass", "Outsourced", None),
    ]
    
    records_inserted = 0
    for (cal_id, equip_id, cal_date, next_due, standard, reading, criteria, result, cal_by, cert) in cal_records:
        db_id = instrument_map.get(equip_id)
        if not db_id:
            continue
        notes_text = f"{standard} | {reading}" if reading else standard
        if cert:
            notes_text += f" | {cert}"
        cur.execute(f"""
            INSERT INTO calibration_records 
            (instrument_id, calibration_date, expiration_date, performed_by, vendor, certificate_number, result, notes)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """, (db_id, cal_date, next_due, cal_by, standard, cal_id, result, notes_text))
        records_inserted += 1
    
    conn.commit()
    
    # ── Step 5: Seed OOT log ──
    try:
        cur.execute(f"""
            INSERT INTO calibration_oot_log 
            (oot_id, date_found, equipment_id, description, discrepancy, amount_oot, 
             last_valid_cal, products_affected, impact_assessment, reinspect_required,
             action_taken, disposition, assessed_by, date_closed)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """, (
            "OOT-2025-001", "2025-01-15", "QC-XX1", "Tape Measure", 
            "Hook loose", "1/8\" play", "2024-07-15",
            "Jobs 25-001 to 25-005", "Low risk-welds reinspected, no issues",
            "Yes-Done", "Tape replaced", "Closed", "Blair M", "2025-01-16"
        ))
        conn.commit()
    except Exception as e:
        print(f"OOT seed error: {e}")
        conn.rollback()
    
    conn.close()
    
    return {
        "message": "Calibration data wiped and reseeded",
        "instruments": len(instruments),
        "calibration_records": records_inserted,
        "oot_records": 1
    }


# ── OOT Log Endpoints ──

@router.get("/oot-log")
def get_oot_log():
    """Get all out-of-tolerance records."""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM calibration_oot_log ORDER BY date_found DESC")
        rows = cur.fetchall()
        conn.close()
        return [row_to_dict(r) for r in rows]
    except Exception:
        conn.close()
        return []

@router.post("/oot-log")
def create_oot_record(data: dict):
    """Create a new OOT record."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    try:
        cur.execute(f"""
            INSERT INTO calibration_oot_log 
            (oot_id, date_found, equipment_id, description, discrepancy, amount_oot,
             last_valid_cal, products_affected, impact_assessment, reinspect_required,
             action_taken, disposition, assessed_by, date_closed)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """, (
            data.get('oot_id', ''), data.get('date_found', ''), data.get('equipment_id', ''),
            data.get('description', ''), data.get('discrepancy', ''), data.get('amount_oot', ''),
            data.get('last_valid_cal', ''), data.get('products_affected', ''),
            data.get('impact_assessment', ''), data.get('reinspect_required', ''),
            data.get('action_taken', ''), data.get('disposition', 'Open'),
            data.get('assessed_by', ''), data.get('date_closed', '')
        ))
        conn.commit()
        conn.close()
        return {"message": "OOT record created"}
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/oot-log/{oot_db_id}")
def update_oot_record(oot_db_id: int, data: dict):
    """Update an OOT record."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    allowed = ['date_found', 'equipment_id', 'description', 'discrepancy', 'amount_oot',
               'last_valid_cal', 'products_affected', 'impact_assessment', 'reinspect_required',
               'action_taken', 'disposition', 'assessed_by', 'date_closed']
    updates = []
    values = []
    for field in allowed:
        if field in data:
            updates.append(f"{field} = {p}")
            values.append(data[field])
    if not updates:
        conn.close()
        return {"message": "No fields to update"}
    values.append(oot_db_id)
    cur.execute(f"UPDATE calibration_oot_log SET {', '.join(updates)} WHERE id = {p}", tuple(values))
    conn.commit()
    conn.close()
    return {"message": "OOT record updated"}

@router.delete("/oot-log/{oot_db_id}")
def delete_oot_record(oot_db_id: int):
    """Delete an OOT record."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    cur.execute(f"DELETE FROM calibration_oot_log WHERE id = {p}", (oot_db_id,))
    conn.commit()
    conn.close()
    return {"message": "OOT record deleted"}
