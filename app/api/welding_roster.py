"""
SSE Welding Roster & Continuity Tracking Module
Updated: March 6, 2026 from Continuity_Logs3-6-26.pdf
56 qualification records
"""
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime, timedelta
import os
import json
import base64

router = APIRouter(prefix="/api/welding", tags=["welding"])

# ============================================================
# MODELS
# ============================================================

class QualificationCreate(BaseModel):
    welder_name: str
    aws_code: str = "AWS D1.1"
    qualification_type: str = "WQTR"
    procedure_id: str
    creation_date: str
    last_welded_on: str
    continuity_days: int = 180
    notes: Optional[str] = None

class QualificationUpdate(BaseModel):
    welder_name: Optional[str] = None
    aws_code: Optional[str] = None
    procedure_id: Optional[str] = None
    creation_date: Optional[str] = None
    last_welded_on: Optional[str] = None
    continuity_days: Optional[int] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None

class ActivityLogCreate(BaseModel):
    qualification_id: int
    activity_date: str
    activity_type: str = "welded"
    logged_by: str = ""
    notes: Optional[str] = None

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

def ph():
    return "%s" if USE_POSTGRES else "?"

def init_welding_tables():
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        if USE_POSTGRES:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS welder_qualifications (
                    id SERIAL PRIMARY KEY,
                    welder_name TEXT NOT NULL,
                    aws_code TEXT NOT NULL,
                    qualification_type TEXT DEFAULT 'WQTR',
                    procedure_id TEXT NOT NULL,
                    creation_date DATE,
                    last_welded_on DATE,
                    continuity_days INTEGER DEFAULT 180,
                    notes TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS welder_activity_log (
                    id SERIAL PRIMARY KEY,
                    qualification_id INTEGER REFERENCES welder_qualifications(id) ON DELETE CASCADE,
                    activity_date DATE NOT NULL,
                    activity_type TEXT NOT NULL,
                    logged_by TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS welding_procedures (
                    id SERIAL PRIMARY KEY,
                    procedure_id TEXT UNIQUE NOT NULL,
                    description TEXT,
                    aws_code TEXT,
                    pdf_data TEXT,
                    pdf_filename TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS welder_qualifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    welder_name TEXT NOT NULL,
                    aws_code TEXT NOT NULL,
                    qualification_type TEXT DEFAULT 'WQTR',
                    procedure_id TEXT NOT NULL,
                    creation_date DATE,
                    last_welded_on DATE,
                    continuity_days INTEGER DEFAULT 180,
                    notes TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS welder_activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    qualification_id INTEGER REFERENCES welder_qualifications(id) ON DELETE CASCADE,
                    activity_date DATE NOT NULL,
                    activity_type TEXT NOT NULL,
                    logged_by TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS welding_procedures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    procedure_id TEXT UNIQUE NOT NULL,
                    description TEXT,
                    aws_code TEXT,
                    pdf_data TEXT,
                    pdf_filename TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error initializing welding tables: {e}")
        raise

# ============================================================
# SEED DATA - From Continuity_Logs3-6-26.pdf (56 records)
# Format: (welder_name, aws_code, procedure_id, creation_date, last_welded_on)
# ============================================================

SEED_DATA = [
    # Row 1-10
    ("Tyler Roberts", "AWS D1.4", "SSE-AWS-D1.4-FC-001-WPS", "2025-06-09", "2024-09-12"),
    ("My Nguyen", "AWS D1.1", "SSE B-U2-GF", "2025-06-09", "2025-02-27"),
    ("Jamone Bienemy", "AWS D1.4", "SSE-AWS-D1.4-FC-001-WPS", "2025-06-09", "2024-09-12"),
    ("Ricardo Solis", "AWS D1.4", "SSE-AWS-D1.4-FC-001-WPS", "2025-06-09", "2024-09-12"),
    ("Jamone Bienemy", "AWS D1.1", "SSE B-U2-GF", "2025-06-09", "2024-02-27"),
    ("Ricardo Solis", "AWS D1.1", "SSE-012-GM-MC-WPS", "2025-06-09", "2025-04-25"),
    ("Wilson Raybon", "AWS D1.1", "SSE B-U2-GF", "2025-06-09", "2020-09-25"),
    ("Tyler Roberts", "AWS D1.1", "SSE B-U2-GF", "2025-06-09", "2024-01-01"),
    ("Jamone Bienemy", "AWS D1.1", "SSE-012-GM-MC-WPS", "2025-06-09", "2025-04-25"),
    ("Shae Beckham", "AWS D1.1", "Mislocated Hole Repair", "2025-06-25", "2025-06-25"),
    
    # Row 11-20
    ("Gage Landry", "AWS D1.1", "Mislocated Hole Repair", "2025-07-16", "2025-07-16"),
    ("Gilbert Humphries", "AWS D1.5", "D1.5 Fig 7.8 5-16 FW", "2025-08-20", "2025-08-21"),
    ("Paul Matlock", "AWS D1.5", "D1.5 Fig 7.8 5-16 FW", "2025-08-20", "2025-08-21"),
    ("Julie Mitchell", "AWS D1.5", "D1.5 Fig 7.8 5-16 FW", "2025-08-21", "2025-08-22"),
    ("Ryan Lam", "AWS D1.5", "D1.5 Fig 7.8 5-16 FW", "2025-08-26", "2025-08-26"),
    ("Charles Coleman", "AWS D1.1", "SSE-012-GM-MC-WPS", "2025-11-14", "2025-04-02"),
    ("Tharen Frederick", "AWS D1.1", "Mislocated Hole Repair", "2025-11-14", "2025-07-24"),
    ("Amy Tong", "AWS D1.1", "B-L1b-GF Metal Core", "2025-11-14", "2025-04-02"),
    ("Amy Tong", "AWS D1.1", "SSE Box Tubing", "2025-11-14", "2024-06-19"),
    ("Alan Mixon", "AWS D1.1", "SSE B-U2-GF", "2025-11-14", "2024-11-05"),
    
    # Row 21-30
    ("Richard Eubanks", "AWS D1.1", "SSE B-U2-GF", "2025-11-14", "2023-07-10"),
    ("Tyrek Lindsey", "AWS D1.1", "SSE B-U2-GF", "2025-11-14", "2023-07-25"),
    ("Amy Tong", "AWS D1.5", "D1.5 Fig 7.8 5-16 FW", "2025-11-14", "2024-07-17"),
    ("Terry Williams", "AWS D1.1", "SSE-012-GM-MC-WPS", "2025-11-14", "2025-04-02"),
    ("William Pilkin", "AWS D1.5", "SSE-FC-A709(36)-FCM-WPS", "2025-11-14", "2025-06-11"),
    ("Ricardo Solis", "AWS D1.1", "SSE B-U2-GF", "2025-11-14", "2024-02-27"),
    ("Terry Williams", "AWS D1.1", "SSE B-U2-GF", "2025-11-14", "2016-12-13"),
    ("Johnny Evans", "AWS D1.1", "SSE B-U2-GF", "2025-11-14", "2024-12-16"),
    ("Tyrek Lindsey", "AWS D1.1", "SSE-012-GM-MC-WPS", "2025-11-14", "2025-04-23"),
    ("Amy Tong", "AWS D1.1", "SSE-012-GM-MC-WPS", "2025-11-14", "2025-04-02"),
    
    # Row 31-40
    ("William Pilkin", "AWS D1.1", "SSE B-U2-GF", "2025-11-14", "2024-01-17"),
    ("Rashid Levy", "AWS D1.1", "SSE B-U2-GF", "2025-11-14", "2025-08-21"),
    ("Nicholas Adams", "AWS D1.1", "SSE B-U2-GF", "2025-11-14", "2022-08-24"),
    ("Raymond Brewer", "AWS D1.1", "SSE B-U2-GF", "2025-11-14", "2023-05-11"),
    ("Paul Williams", "AWS D1.1", "SSE B-U2-GF", "2025-11-14", "2025-06-30"),
    ("Charles Coleman", "AWS D1.1", "SSE B-U2-GF", "2025-11-14", "2024-06-11"),
    ("Amy Tong", "AWS D1.1", "SSE B-U2-GF", "2025-11-14", "2023-07-10"),
    ("William Pilkin", "AWS D1.4", "Flare Bevel S.S D1.4/D1.6", "2025-12-08", "2025-03-07"),
    ("Terry Williams", "AWS D1.4", "SSE-AWS-D1.4-FC-001-WPS", "2025-12-08", "2024-06-03"),
    ("Richard Eubanks", "AWS D1.4", "SSE D1.4-500", "2025-12-08", "2024-04-09"),
    
    # Row 41-50
    ("Tyrek Lindsey", "AWS D1.4", "SSE-AWS-D1.4-FC-001-WPS", "2025-12-08", "2024-08-27"),
    ("Charles Coleman", "AWS D1.4", "SSE-AWS-D1.4-FC-001-WPS", "2025-12-08", "2024-08-27"),
    ("Herbert Keeton", "AWS D1.4", "SSE-AWS-D1.4-FC-001-WPS", "2025-12-08", "2024-08-27"),
    ("Richard Eubanks", "AWS D1.4", "Flare Bevel S.S D1.4/D1.6", "2025-12-08", "2025-03-07"),
    ("Charles Coleman", "AWS D1.4", "SSE-AWS-D1.4-FC-001-WPS", "2025-12-08", "2024-07-19"),
    ("Amy Tong", "AWS D1.4", "SSE-AWS-D1.4-FC-001-WPS", "2025-12-09", "2024-08-27"),
    ("Brittany Knapper", "AWS D1.1", "Mislocated Hole Repair", "2026-02-02", "2025-09-29"),
    ("Alberto Alvarez", "AWS D1.1", "SSE B-U2-GF", "2026-02-02", "2026-02-02"),
    ("Chris Arceneaux", "AWS D1.5", "D1.5 Fig 7.8 5-16 FW", "2026-02-10", "2026-03-03"),
    ("Roy Stigler", "AWS D1.5", "D1.5 Fig 7.8 5-16 FW", "2026-02-10", "2026-02-10"),
    
    # Row 51-56
    ("Eric Pham", "AWS D1.5", "D1.5 Fig 7.8 5-16 FW", "2026-02-20", "2025-08-22"),
    ("Vinson Pulliam", "AWS D1.5", "D1.5 Fig 7.8 5-16 FW", "2026-02-20", "2025-08-26"),
    ("Micheal Abarca", "AWS D1.5", "D1.5 Fig 7.8 5-16 FW", "2026-02-20", "2025-08-21"),
    ("Thomas Case", "AWS D1.5", "D1.5 Fig 7.8 5-16 FW", "2026-03-03", "2026-02-17"),
    ("Charles Coleman", "AWS D1.4", "Flare Bevel S.S D1.4/D1.6", "2026-12-08", "2025-03-07"),
]

# All unique procedures for dropdown (10 procedures)
PROCEDURES = [
    {"id": "SSE-AWS-D1.4-FC-001-WPS", "description": "D1.4 Flux Core WPS", "aws_code": "AWS D1.4"},
    {"id": "SSE D1.4-500", "description": "D1.4 Standard 500", "aws_code": "AWS D1.4"},
    {"id": "Flare Bevel S.S D1.4/D1.6", "description": "Flare Bevel Stainless Steel D1.4/D1.6", "aws_code": "AWS D1.4"},
    {"id": "SSE B-U2-GF", "description": "Gas Shielded Flux Core", "aws_code": "AWS D1.1"},
    {"id": "SSE-012-GM-MC-WPS", "description": "Metal Core WPS", "aws_code": "AWS D1.1"},
    {"id": "Mislocated Hole Repair", "description": "Mislocated Hole Repair Procedure", "aws_code": "AWS D1.1"},
    {"id": "B-L1b-GF Metal Core", "description": "Metal Core L1b Gas Shielded", "aws_code": "AWS D1.1"},
    {"id": "SSE Box Tubing", "description": "Box Tubing WPS", "aws_code": "AWS D1.1"},
    {"id": "D1.5 Fig 7.8 5-16 FW", "description": "Bridge Fillet Weld 5/16 per Fig 7.8", "aws_code": "AWS D1.5"},
    {"id": "SSE-FC-A709(36)-FCM-WPS", "description": "A709 Grade 36 Flux Core Metal WPS", "aws_code": "AWS D1.5"},
]

# ============================================================
# ROUTES
# ============================================================

@router.get("/qualifications")
def get_qualifications(active_only: bool = True):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        if active_only:
            cursor.execute("SELECT * FROM welder_qualifications WHERE is_active = TRUE ORDER BY welder_name, aws_code")
        else:
            cursor.execute("SELECT * FROM welder_qualifications ORDER BY welder_name, aws_code")
        
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        
        # Calculate status for each
        today = date.today()
        for row in rows:
            if row.get('last_welded_on'):
                if isinstance(row['last_welded_on'], str):
                    last = datetime.strptime(row['last_welded_on'], '%Y-%m-%d').date()
                else:
                    last = row['last_welded_on']
                
                days_since = (today - last).days
                continuity = row.get('continuity_days', 180)
                days_remaining = continuity - days_since
                
                # Calculate expiration date
                expire_date = last + timedelta(days=continuity)
                row['continuity_expires'] = expire_date.strftime('%Y-%m-%d')
                row['days_remaining'] = days_remaining
                
                if days_since > continuity:
                    row['status'] = 'lapsed'
                    row['days_overdue'] = days_since - continuity
                elif days_since > continuity - 30:
                    row['status'] = 'expiring_soon'
                    row['days_until_lapse'] = continuity - days_since
                else:
                    row['status'] = 'current'
                    row['days_until_lapse'] = continuity - days_since
            else:
                row['status'] = 'unknown'
                row['continuity_expires'] = None
                row['days_remaining'] = None
        
        return rows
    except Exception as e:
        print(f"Qualifications error: {e}")
        return []

@router.get("/qualifications/{qual_id}")
def get_qualification(qual_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM welder_qualifications WHERE id = {ph()}", (qual_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Qualification not found")
    return dict(row)

@router.post("/qualifications")
def create_qualification(data: QualificationCreate):
    conn = get_db()
    cursor = conn.cursor()
    
    if USE_POSTGRES:
        cursor.execute("""
            INSERT INTO welder_qualifications 
            (welder_name, aws_code, qualification_type, procedure_id, creation_date, last_welded_on, continuity_days, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (data.welder_name, data.aws_code, data.qualification_type, data.procedure_id, 
              data.creation_date, data.last_welded_on, data.continuity_days, data.notes))
        row = cursor.fetchone()
    else:
        cursor.execute("""
            INSERT INTO welder_qualifications 
            (welder_name, aws_code, qualification_type, procedure_id, creation_date, last_welded_on, continuity_days, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (data.welder_name, data.aws_code, data.qualification_type, data.procedure_id, 
              data.creation_date, data.last_welded_on, data.continuity_days, data.notes))
        cursor.execute("SELECT * FROM welder_qualifications WHERE id = ?", (cursor.lastrowid,))
        row = cursor.fetchone()
    
    conn.commit()
    conn.close()
    return dict(row)

@router.put("/qualifications/{qual_id}")
def update_qualification(qual_id: int, data: QualificationUpdate):
    conn = get_db()
    cursor = conn.cursor()
    
    updates = []
    values = []
    for field, value in data.dict(exclude_unset=True).items():
        if value is not None:
            updates.append(f"{field} = {ph()}")
            values.append(value)
    
    if not updates:
        raise HTTPException(400, "No fields to update")
    
    values.append(qual_id)
    cursor.execute(f"UPDATE welder_qualifications SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = {ph()}", values)
    conn.commit()
    
    cursor.execute(f"SELECT * FROM welder_qualifications WHERE id = {ph()}", (qual_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row)

@router.delete("/qualifications/{qual_id}")
def delete_qualification(qual_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM welder_qualifications WHERE id = {ph()}", (qual_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@router.post("/qualifications/{qual_id}/log-activity")
def log_activity(qual_id: int, data: ActivityLogCreate):
    conn = get_db()
    cursor = conn.cursor()
    
    # Log the activity
    if USE_POSTGRES:
        cursor.execute("""
            INSERT INTO welder_activity_log (qualification_id, activity_date, activity_type, logged_by, notes)
            VALUES (%s, %s, %s, %s, %s)
        """, (qual_id, data.activity_date, data.activity_type, data.logged_by, data.notes))
    else:
        cursor.execute("""
            INSERT INTO welder_activity_log (qualification_id, activity_date, activity_type, logged_by, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (qual_id, data.activity_date, data.activity_type, data.logged_by, data.notes))
    
    # If it's a weld activity, update last_welded_on
    if data.activity_type == "welded":
        cursor.execute(f"UPDATE welder_qualifications SET last_welded_on = {ph()}, updated_at = CURRENT_TIMESTAMP WHERE id = {ph()}", 
                      (data.activity_date, qual_id))
    
    conn.commit()
    conn.close()
    return {"success": True}

@router.get("/qualifications/{qual_id}/activity")
def get_activity_log(qual_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM welder_activity_log WHERE qualification_id = {ph()} ORDER BY activity_date DESC", (qual_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

@router.get("/dashboard")
def get_dashboard():
    """Summary stats for welding dashboard"""
    try:
        quals = get_qualifications(active_only=True)
    except Exception as e:
        print(f"Dashboard error: {e}")
        return {
            "summary": {
                "total_qualifications": 0,
                "total_welders": 0,
                "current": 0,
                "expiring_soon": 0,
                "lapsed": 0,
                "compliance_rate": 100
            },
            "lapsed": [],
            "expiring_soon": [],
            "current": [],
            "by_welder": {}
        }
    
    current_list = [q for q in quals if q.get('status') == 'current']
    expiring_list = [q for q in quals if q.get('status') == 'expiring_soon']
    lapsed_list = [q for q in quals if q.get('status') == 'lapsed']
    
    # Get unique welders
    welders = list(set(q['welder_name'] for q in quals))
    
    # Group by welder
    by_welder = {}
    for q in quals:
        name = q['welder_name']
        if name not in by_welder:
            by_welder[name] = []
        by_welder[name].append(q)
    
    # Calculate compliance rate
    total = len(quals)
    compliant = len(current_list) + len(expiring_list)
    compliance_rate = round((compliant / total * 100) if total > 0 else 100)
    
    return {
        "summary": {
            "total_qualifications": len(quals),
            "total_welders": len(welders),
            "current": len(current_list),
            "expiring_soon": len(expiring_list),
            "lapsed": len(lapsed_list),
            "compliance_rate": compliance_rate
        },
        "lapsed": lapsed_list,
        "expiring_soon": expiring_list,
        "current": current_list,
        "by_welder": by_welder
    }

@router.get("/procedures")
def get_procedures():
    """Get all welding procedures"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, procedure_id, description, aws_code, pdf_filename, is_active FROM welding_procedures WHERE is_active = TRUE ORDER BY procedure_id")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        
        # Add has_file flag
        for row in rows:
            row['has_file'] = bool(row.get('pdf_filename'))
            row['filename'] = row.get('pdf_filename')
        
        # If no procedures in DB, return the seed list with has_file = False
        if not rows:
            return [{"procedure_id": p['id'], "description": p['description'], "aws_code": p['aws_code'], "has_file": False} for p in PROCEDURES]
        return rows
    except Exception as e:
        # Table doesn't exist yet, return seed list
        print(f"Procedures table error: {e}")
        return [{"procedure_id": p['id'], "description": p['description'], "aws_code": p['aws_code'], "has_file": False} for p in PROCEDURES]

@router.get("/procedures/{proc_id}/pdf")
def get_procedure_pdf(proc_id: int):
    """Download procedure PDF"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(f"SELECT pdf_data, pdf_filename FROM welding_procedures WHERE id = {ph()}", (proc_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or not row['pdf_data']:
        raise HTTPException(404, "PDF not found")
    
    return {
        "filename": row['pdf_filename'],
        "data": row['pdf_data']
    }

@router.post("/procedures/{procedure_id}/upload")
async def upload_procedure_pdf(procedure_id: str, file: UploadFile = File(...)):
    """Upload PDF for a procedure"""
    conn = get_db()
    cursor = conn.cursor()
    
    content = await file.read()
    b64 = base64.b64encode(content).decode('utf-8')
    
    # Check if procedure exists
    cursor.execute(f"SELECT id FROM welding_procedures WHERE procedure_id = {ph()}", (procedure_id,))
    existing = cursor.fetchone()
    
    if existing:
        cursor.execute(f"UPDATE welding_procedures SET pdf_data = {ph()}, pdf_filename = {ph()}, updated_at = CURRENT_TIMESTAMP WHERE procedure_id = {ph()}", 
                      (b64, file.filename, procedure_id))
    else:
        # Find procedure info from PROCEDURES list
        proc_info = next((p for p in PROCEDURES if p['id'] == procedure_id), None)
        desc = proc_info['description'] if proc_info else procedure_id
        aws = proc_info['aws_code'] if proc_info else "AWS D1.1"
        
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO welding_procedures (procedure_id, description, aws_code, pdf_data, pdf_filename)
                VALUES (%s, %s, %s, %s, %s)
            """, (procedure_id, desc, aws, b64, file.filename))
        else:
            cursor.execute("""
                INSERT INTO welding_procedures (procedure_id, description, aws_code, pdf_data, pdf_filename)
                VALUES (?, ?, ?, ?, ?)
            """, (procedure_id, desc, aws, b64, file.filename))
    
    conn.commit()
    conn.close()
    return {"success": True, "filename": file.filename}

@router.post("/seed")
def seed_data():
    """Load all qualification data from continuity log - March 2026 update"""
    try:
        # Ensure tables exist first
        init_welding_tables()
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Clear existing qualifications
        cursor.execute("DELETE FROM welder_qualifications")
        
        # Insert all 56 records from continuity log
        for welder, aws, proc, created, last_weld in SEED_DATA:
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO welder_qualifications 
                    (welder_name, aws_code, qualification_type, procedure_id, creation_date, last_welded_on)
                    VALUES (%s, %s, 'WQTR', %s, %s, %s)
                """, (welder, aws, proc, created, last_weld))
            else:
                cursor.execute("""
                    INSERT INTO welder_qualifications 
                    (welder_name, aws_code, qualification_type, procedure_id, creation_date, last_welded_on)
                    VALUES (?, ?, 'WQTR', ?, ?, ?)
                """, (welder, aws, proc, created, last_weld))
        
        # Also seed procedures table
        for proc in PROCEDURES:
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO welding_procedures (procedure_id, description, aws_code)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (procedure_id) DO NOTHING
                """, (proc['id'], proc['description'], proc['aws_code']))
            else:
                cursor.execute("""
                    INSERT OR IGNORE INTO welding_procedures (procedure_id, description, aws_code)
                    VALUES (?, ?, ?)
                """, (proc['id'], proc['description'], proc['aws_code']))
        
        conn.commit()
        conn.close()
        return {"success": True, "count": len(SEED_DATA), "message": f"Loaded {len(SEED_DATA)} qualification records from March 2026 continuity log"}
    except Exception as e:
        raise HTTPException(500, f"Seed failed: {str(e)}")

@router.get("/welders")
def get_unique_welders():
    """Get list of unique welder names"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT welder_name FROM welder_qualifications WHERE is_active = TRUE ORDER BY welder_name")
        rows = [r['welder_name'] if isinstance(r, dict) else r[0] for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(f"Welders error: {e}")
        return []

@router.get("/welders/{welder_name}/qualifications")
def get_welder_qualifications(welder_name: str):
    """Get all qualifications for a specific welder"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM welder_qualifications WHERE welder_name = {ph()} AND is_active = TRUE ORDER BY aws_code, procedure_id", (welder_name,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    # Calculate status
    today = date.today()
    for row in rows:
        if row.get('last_welded_on'):
            if isinstance(row['last_welded_on'], str):
                last = datetime.strptime(row['last_welded_on'], '%Y-%m-%d').date()
            else:
                last = row['last_welded_on']
            
            days_since = (today - last).days
            continuity = row.get('continuity_days', 180)
            
            if days_since > continuity:
                row['status'] = 'lapsed'
            elif days_since > continuity - 30:
                row['status'] = 'expiring_soon'
            else:
                row['status'] = 'current'
    
    return rows
