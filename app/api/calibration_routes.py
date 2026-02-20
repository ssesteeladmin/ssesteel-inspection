"""
SSE Calibration Tracking Module - API Routes
Add this file to: backend/app/api/calibration.py
Then import and include in your main.py
"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime, timedelta
from enum import Enum
import os
import json
import base64

router = APIRouter(prefix="/api/calibration", tags=["calibration"])

# ============================================================
# MODELS
# ============================================================

class InstrumentCategory(str, Enum):
    WELDING = "welding"
    MEASUREMENT = "measurement"
    TORQUE = "torque"
    PRESSURE = "pressure"
    ELECTRICAL = "electrical"
    OTHER = "other"

class CalibrationStatus(str, Enum):
    CURRENT = "current"
    DUE_SOON = "due_soon"       # Within 30 days
    OVERDUE = "overdue"
    OUT_OF_SERVICE = "out_of_service"

class InstrumentCreate(BaseModel):
    instrument_id: str           # e.g., "WM-001", "TW-003"
    name: str                    # e.g., "Miller Dynasty 400"
    category: InstrumentCategory
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    serial_number: Optional[str] = None
    location: Optional[str] = "Shop"
    calibration_vendor: Optional[str] = None
    calibration_interval_days: int = 365  # Default annual
    notes: Optional[str] = None

class InstrumentUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[InstrumentCategory] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    serial_number: Optional[str] = None
    location: Optional[str] = None
    calibration_vendor: Optional[str] = None
    calibration_interval_days: Optional[int] = None
    notes: Optional[str] = None
    active: Optional[bool] = None

class CalibrationRecordCreate(BaseModel):
    instrument_db_id: int
    calibration_date: date
    expiration_date: date
    performed_by: str
    vendor: Optional[str] = None
    certificate_number: Optional[str] = None
    result: str = "pass"          # pass, fail, adjusted
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

# Detect PostgreSQL vs SQLite based on DATABASE_URL
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
    """Return placeholder - %s for Postgres, ? for SQLite"""
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
    
    p = ph()
    s = serial_type()
    b = bool_type()
    ts = timestamp_default()
    
    # Instruments table
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
            calibration_vendor TEXT,
            calibration_interval_days INTEGER DEFAULT 365,
            notes TEXT,
            active {b},
            created_at {ts},
            updated_at {ts}
        )
    """)
    
    # Calibration records table
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS calibration_records (
            id {s} PRIMARY KEY,
            instrument_id INTEGER NOT NULL,
            calibration_date DATE NOT NULL,
            expiration_date DATE NOT NULL,
            performed_by TEXT NOT NULL,
            vendor TEXT,
            certificate_number TEXT,
            result TEXT DEFAULT 'pass',
            cost REAL,
            notes TEXT,
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
    
    # Reminder log table (tracks what's been sent)
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
    
    # Calibration certificates table (file storage)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS calibration_certificates (
            id {s} PRIMARY KEY,
            record_id INTEGER,
            instrument_db_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            file_data TEXT NOT NULL,
            content_type TEXT DEFAULT 'application/pdf',
            uploaded_by TEXT,
            uploaded_at {ts},
            FOREIGN KEY (instrument_db_id) REFERENCES calibration_instruments(id)
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
    """Convert a database row to dict (works for both sqlite and postgres)."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    return dict(row)

def calculate_status(expiration_date_str):
    """Calculate calibration status based on expiration date."""
    if expiration_date_str is None:
        return "overdue"
    
    if isinstance(expiration_date_str, date):
        exp = expiration_date_str
    else:
        exp = datetime.strptime(str(expiration_date_str), "%Y-%m-%d").date()
    
    today = date.today()
    days_remaining = (exp - today).days
    
    if days_remaining < 0:
        return "overdue"
    elif days_remaining <= 30:
        return "due_soon"
    else:
        return "current"

def get_instrument_with_status(row):
    """Enrich instrument row with calibration status info."""
    d = row_to_dict(row)
    
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    # Get latest calibration record
    cur.execute(f"""
        SELECT * FROM calibration_records 
        WHERE instrument_id = {p}
        ORDER BY calibration_date DESC LIMIT 1
    """, (d['id'],))
    
    latest = cur.fetchone()
    conn.close()
    
    if latest:
        latest = row_to_dict(latest)
        d['last_calibration_date'] = str(latest['calibration_date'])
        d['expiration_date'] = str(latest['expiration_date'])
        d['certificate_number'] = latest.get('certificate_number')
        d['calibration_vendor_last'] = latest.get('vendor')
        d['status'] = calculate_status(latest['expiration_date'])
        
        exp = datetime.strptime(str(latest['expiration_date']), "%Y-%m-%d").date()
        d['days_remaining'] = (exp - date.today()).days
    else:
        d['last_calibration_date'] = None
        d['expiration_date'] = None
        d['certificate_number'] = None
        d['calibration_vendor_last'] = None
        d['status'] = "overdue"
        d['days_remaining'] = -999
    
    return d

# ============================================================
# INSTRUMENT ENDPOINTS
# ============================================================

@router.get("/instruments")
def list_instruments(active_only: bool = True):
    """Get all calibration instruments with current status."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    if active_only:
        cur.execute(f"SELECT * FROM calibration_instruments WHERE active = true ORDER BY category, instrument_id")
    else:
        cur.execute("SELECT * FROM calibration_instruments ORDER BY category, instrument_id")
    
    rows = cur.fetchall()
    conn.close()
    
    instruments = [get_instrument_with_status(r) for r in rows]
    
    # Summary counts
    summary = {
        "total": len(instruments),
        "current": sum(1 for i in instruments if i['status'] == 'current'),
        "due_soon": sum(1 for i in instruments if i['status'] == 'due_soon'),
        "overdue": sum(1 for i in instruments if i['status'] == 'overdue'),
    }
    
    return {"instruments": instruments, "summary": summary}


@router.post("/instruments")
def create_instrument(data: InstrumentCreate):
    """Add a new instrument to track."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    try:
        cur.execute(f"""
            INSERT INTO calibration_instruments 
            (instrument_id, name, category, manufacturer, model_number, serial_number,
             location, calibration_vendor, calibration_interval_days, notes)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """, (
            data.instrument_id, data.name, data.category.value,
            data.manufacturer, data.model_number, data.serial_number,
            data.location, data.calibration_vendor,
            data.calibration_interval_days, data.notes
        ))
        conn.commit()
        
        # Get the created instrument
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
    """Get a single instrument with full details and history."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    cur.execute(f"SELECT * FROM calibration_instruments WHERE instrument_id = {p}", (instrument_id,))
    row = cur.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    instrument = get_instrument_with_status(row)
    
    # Get full calibration history
    cur.execute(f"""
        SELECT * FROM calibration_records 
        WHERE instrument_id = {p}
        ORDER BY calibration_date DESC
    """, (instrument['id'],))
    
    records = [row_to_dict(r) for r in cur.fetchall()]
    conn.close()
    
    instrument['calibration_history'] = records
    return instrument


@router.put("/instruments/{instrument_id}")
def update_instrument(instrument_id: str, data: InstrumentUpdate):
    """Update an instrument's details."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    # Build dynamic update
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
def delete_instrument(instrument_id: str, permanent: bool = False):
    """Delete an instrument. Soft-delete by default, permanent if specified."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    if permanent:
        # Get the DB id first
        cur.execute(f"SELECT id FROM calibration_instruments WHERE instrument_id = {p}", (instrument_id,))
        row = cur.fetchone()
        if row:
            db_id = row_to_dict(row)['id']
            cur.execute(f"DELETE FROM calibration_certificates WHERE instrument_db_id = {p}", (db_id,))
            cur.execute(f"DELETE FROM calibration_records WHERE instrument_id = {p}", (db_id,))
        cur.execute(f"DELETE FROM calibration_instruments WHERE instrument_id = {p}", (instrument_id,))
        conn.commit()
        conn.close()
        return {"message": f"Instrument {instrument_id} permanently deleted"}
    else:
        if USE_POSTGRES:
            cur.execute(f"UPDATE calibration_instruments SET active = false WHERE instrument_id = {p}", (instrument_id,))
        else:
            cur.execute(f"UPDATE calibration_instruments SET active = 0 WHERE instrument_id = {p}", (instrument_id,))
        conn.commit()
        conn.close()
        return {"message": f"Instrument {instrument_id} deactivated"}


# ============================================================
# CALIBRATION CERTIFICATE ENDPOINTS
# ============================================================

@router.post("/certificates/upload")
async def upload_certificate(
    instrument_db_id: int = Form(...),
    record_id: int = Form(None),
    uploaded_by: str = Form(""),
    file: UploadFile = File(...)
):
    """Upload a calibration certificate for an instrument."""
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")
    
    b64_data = base64.b64encode(content).decode('utf-8')
    
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    try:
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO calibration_certificates (record_id, instrument_db_id, filename, file_data, content_type, uploaded_by)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """, (record_id, instrument_db_id, file.filename, b64_data, file.content_type or 'application/pdf', uploaded_by))
            cert_id = cur.fetchone()['id']
        else:
            cur.execute("""
                INSERT INTO calibration_certificates (record_id, instrument_db_id, filename, file_data, content_type, uploaded_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (record_id, instrument_db_id, file.filename, b64_data, file.content_type or 'application/pdf', uploaded_by))
            cert_id = cur.lastrowid
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
    
    return {"id": cert_id, "message": f"Certificate uploaded: {file.filename}", "success": True}


@router.get("/certificates/{instrument_db_id}")
def list_certificates(instrument_db_id: int):
    """List all certificates for an instrument."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    cur.execute(f"""
        SELECT id, record_id, filename, content_type, uploaded_by, uploaded_at
        FROM calibration_certificates
        WHERE instrument_db_id = {p}
        ORDER BY uploaded_at DESC
    """, (instrument_db_id,))
    
    certs = [row_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return certs


@router.get("/certificates/download/{cert_id}")
def download_certificate(cert_id: int):
    """Download a calibration certificate file."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    cur.execute(f"SELECT filename, file_data, content_type FROM calibration_certificates WHERE id = {p}", (cert_id,))
    row = cur.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Certificate not found")
    
    row = row_to_dict(row)
    file_bytes = base64.b64decode(row['file_data'])
    
    return Response(
        content=file_bytes,
        media_type=row['content_type'] or 'application/pdf',
        headers={"Content-Disposition": f"inline; filename=\"{row['filename']}\""}
    )


@router.delete("/certificates/delete/{cert_id}")
def delete_certificate(cert_id: int):
    """Delete a certificate file."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    cur.execute(f"DELETE FROM calibration_certificates WHERE id = {p}", (cert_id,))
    conn.commit()
    conn.close()
    return {"message": "Certificate deleted"}

# ============================================================
# CALIBRATION RECORD ENDPOINTS
# ============================================================

@router.post("/records")
def create_calibration_record(data: CalibrationRecordCreate):
    """Log a new calibration event for an instrument."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    # Verify instrument exists
    cur.execute(f"SELECT id FROM calibration_instruments WHERE id = {p}", (data.instrument_db_id,))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    cur.execute(f"""
        INSERT INTO calibration_records 
        (instrument_id, calibration_date, expiration_date, performed_by,
         vendor, certificate_number, result, cost, notes)
        VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        data.instrument_db_id, str(data.calibration_date), str(data.expiration_date),
        data.performed_by, data.vendor, data.certificate_number,
        data.result, data.cost, data.notes
    ))
    
    conn.commit()
    conn.close()
    
    return {"message": "Calibration record added successfully"}


@router.get("/records/{instrument_id}")
def get_calibration_records(instrument_id: str):
    """Get all calibration records for an instrument."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    # Get instrument db id
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
# DASHBOARD / STATUS ENDPOINTS
# ============================================================

@router.get("/dashboard")
def calibration_dashboard():
    """Get complete calibration dashboard data."""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM calibration_instruments WHERE active = true ORDER BY category, instrument_id")
    rows = cur.fetchall()
    conn.close()
    
    instruments = [get_instrument_with_status(r) for r in rows]
    
    # Organize by status
    overdue = [i for i in instruments if i['status'] == 'overdue']
    due_soon = [i for i in instruments if i['status'] == 'due_soon']
    current = [i for i in instruments if i['status'] == 'current']
    
    # Organize by category
    by_category = {}
    for inst in instruments:
        cat = inst.get('category', 'other')
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(inst)
    
    # Upcoming expirations (next 90 days)
    upcoming = sorted(
        [i for i in instruments if i['days_remaining'] is not None and 0 <= i['days_remaining'] <= 90],
        key=lambda x: x['days_remaining']
    )
    
    return {
        "summary": {
            "total": len(instruments),
            "current": len(current),
            "due_soon": len(due_soon),
            "overdue": len(overdue),
            "compliance_rate": round(len(current) / max(len(instruments), 1) * 100, 1)
        },
        "overdue": overdue,
        "due_soon": due_soon,
        "current": current,
        "by_category": by_category,
        "upcoming_expirations": upcoming
    }

# ============================================================
# REMINDER RECIPIENTS
# ============================================================

@router.get("/reminders/recipients")
def list_recipients():
    """Get all reminder recipients."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM calibration_reminder_recipients WHERE active = true")
    rows = [row_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return {"recipients": rows}


@router.post("/reminders/recipients")
def add_recipient(data: ReminderRecipientCreate):
    """Add a new reminder recipient."""
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
    """Remove a reminder recipient."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    cur.execute(f"UPDATE calibration_reminder_recipients SET active = false WHERE email = {p}", (email,))
    conn.commit()
    conn.close()
    return {"message": f"Removed {email} from reminder list"}

# ============================================================
# REMINDER CHECK ENDPOINT (called by scheduler)
# ============================================================

@router.get("/reminders/check")
def check_reminders():
    """
    Check for instruments needing reminders.
    This endpoint is called by the daily scheduler task.
    Returns what notifications need to be sent.
    """
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
            # Check if we already sent this reminder today
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
    """Log that a reminder was sent (called after email is actually sent)."""
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
# AUDIT EXPORT ENDPOINT
# ============================================================

@router.get("/export")
def export_calibration_report():
    """
    Export all calibration data for audit purposes.
    Returns a clean JSON structure that can be converted to PDF/Excel.
    """
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    cur.execute("SELECT * FROM calibration_instruments WHERE active = true ORDER BY category, instrument_id")
    rows = cur.fetchall()
    
    report = {
        "report_date": str(date.today()),
        "company": "Southern Services & Equipment Inc.",
        "report_title": "AISC Calibration Compliance Report",
        "instruments": []
    }
    
    for row in rows:
        inst = get_instrument_with_status(row)
        
        # Get calibration history
        cur.execute(f"""
            SELECT calibration_date, expiration_date, performed_by, vendor, 
                   certificate_number, result 
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
            "status": inst['status'],
            "last_calibration": inst.get('last_calibration_date'),
            "expiration": inst.get('expiration_date'),
            "days_remaining": inst.get('days_remaining'),
            "vendor": inst.get('calibration_vendor'),
            "history": history
        })
    
    conn.close()
    return report
