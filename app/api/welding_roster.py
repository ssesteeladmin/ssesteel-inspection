"""
SSE Welding Roster & Continuity Tracking Module
Tracks welder qualifications per AWS D1.1/D1.4/D1.5
6-month continuity window: welders must use each qualified process 
within 6 months or qualification lapses.

Add this file to: backend/app/api/welding_roster.py
Then import and include in your main.py
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime, timedelta
from enum import Enum
import os
import json
import base64

router = APIRouter(prefix="/api/welding", tags=["welding"])

# ============================================================
# MODELS
# ============================================================

class QualificationCreate(BaseModel):
    welder_name: str
    aws_code: str = "AWS D1.1"       # AWS D1.1, AWS D1.4, AWS D1.5
    qualification_type: str = "WQTR"  # WQTR = Welder Qualification Test Record
    procedure_id: str                 # e.g., "SSE AWS-D1.4-FC-001 WPS"
    creation_date: str                # When originally qualified
    last_welded_on: str               # Most recent use of this process
    continuity_days: int = 180        # 6 months default
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
    activity_type: str = "welded"  # welded, requalified, lapsed, note
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

def serial_type():
    return "SERIAL" if USE_POSTGRES else "INTEGER"

def bool_type():
    return "BOOLEAN DEFAULT TRUE" if USE_POSTGRES else "INTEGER DEFAULT 1"

def timestamp_default():
    return "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" if USE_POSTGRES else "TEXT DEFAULT (datetime('now'))"

# ============================================================
# TABLE CREATION
# ============================================================

def init_welding_tables():
    """Create welding roster tables if they don't exist."""
    conn = get_db()
    cur = conn.cursor()
    
    s = serial_type()
    b = bool_type()
    ts = timestamp_default()
    
    # Welding qualifications table
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS welding_qualifications (
            id {s} PRIMARY KEY,
            welder_name TEXT NOT NULL,
            aws_code TEXT NOT NULL DEFAULT 'AWS D1.1',
            qualification_type TEXT NOT NULL DEFAULT 'WQTR',
            procedure_id TEXT NOT NULL,
            creation_date TEXT NOT NULL,
            last_welded_on TEXT NOT NULL,
            continuity_days INTEGER DEFAULT 180,
            notes TEXT,
            is_active {b},
            created_at {ts},
            updated_at {ts}
        )
    """)
    
    # Activity log - tracks each time continuity is updated
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS welding_activity_log (
            id {s} PRIMARY KEY,
            qualification_id INTEGER NOT NULL,
            activity_date TEXT NOT NULL,
            activity_type TEXT NOT NULL DEFAULT 'welded',
            logged_by TEXT DEFAULT '',
            notes TEXT,
            created_at {ts}
        )
    """)
    
    conn.commit()
    conn.close()
    print("Welding roster tables initialized")

def init_procedure_table():
    """Create welding procedures table for WPS document storage."""
    conn = get_db()
    cur = conn.cursor()
    
    s = serial_type()
    ts = timestamp_default()
    
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS welding_procedures (
            id {s} PRIMARY KEY,
            procedure_id TEXT NOT NULL UNIQUE,
            aws_code TEXT NOT NULL DEFAULT 'AWS D1.1',
            description TEXT,
            filename TEXT,
            file_data TEXT,
            content_type TEXT DEFAULT 'application/pdf',
            uploaded_by TEXT,
            uploaded_at {ts}
        )
    """)
    
    conn.commit()
    conn.close()
    print("Welding procedures table initialized")

# Run on import
init_welding_tables()
init_procedure_table()


# ============================================================
# HELPER: Compute status for a qualification
# ============================================================

def compute_status(last_welded_on_str, continuity_days=180):
    """Returns (status, days_remaining, continuity_expires) for a qualification."""
    try:
        last_welded = datetime.strptime(str(last_welded_on_str)[:10], "%Y-%m-%d").date()
    except:
        return "unknown", 0, None
    
    expires = last_welded + timedelta(days=continuity_days)
    today = date.today()
    days_remaining = (expires - today).days
    
    if days_remaining < 0:
        status = "lapsed"
    elif days_remaining <= 30:
        status = "expiring_soon"
    else:
        status = "current"
    
    return status, days_remaining, expires.isoformat()


def enrich_qualification(row):
    """Add computed fields to a qualification dict."""
    d = dict(row)
    status, days_remaining, expires = compute_status(
        d.get("last_welded_on", ""),
        d.get("continuity_days", 180)
    )
    d["status"] = status
    d["days_remaining"] = days_remaining
    d["continuity_expires"] = expires
    return d


# ============================================================
# DASHBOARD
# ============================================================

@router.get("/dashboard")
async def welding_dashboard():
    """Full dashboard: summary, lapsed, expiring, current, by_welder, by_code."""
    conn = get_db()
    cur = conn.cursor()
    
    p = ph()
    active_check = "TRUE" if USE_POSTGRES else "1"
    
    cur.execute(f"SELECT * FROM welding_qualifications WHERE is_active = {active_check} ORDER BY welder_name, aws_code")
    rows = [enrich_qualification(r) for r in cur.fetchall()]
    conn.close()
    
    lapsed = [r for r in rows if r["status"] == "lapsed"]
    expiring = [r for r in rows if r["status"] == "expiring_soon"]
    current = [r for r in rows if r["status"] == "current"]
    
    # By welder
    by_welder = {}
    for r in rows:
        name = r["welder_name"]
        if name not in by_welder:
            by_welder[name] = []
        by_welder[name].append(r)
    
    # By AWS code
    by_code = {}
    for r in rows:
        code = r["aws_code"]
        if code not in by_code:
            by_code[code] = []
        by_code[code].append(r)
    
    # Unique welders
    unique_welders = list(set(r["welder_name"] for r in rows))
    
    # Compliance: % of qualifications that are current (not lapsed)
    total = len(rows)
    active_count = len(current) + len(expiring)
    compliance = round((active_count / total * 100) if total > 0 else 0, 1)
    
    return {
        "summary": {
            "total_qualifications": total,
            "total_welders": len(unique_welders),
            "current": len(current),
            "expiring_soon": len(expiring),
            "lapsed": len(lapsed),
            "compliance_rate": compliance
        },
        "lapsed": sorted(lapsed, key=lambda x: x["days_remaining"]),
        "expiring_soon": sorted(expiring, key=lambda x: x["days_remaining"]),
        "current": sorted(current, key=lambda x: x["days_remaining"]),
        "by_welder": by_welder,
        "by_code": by_code,
        "welders": sorted(unique_welders)
    }


# ============================================================
# QUALIFICATIONS CRUD
# ============================================================

@router.get("/qualifications")
async def list_qualifications(welder: Optional[str] = None, aws_code: Optional[str] = None):
    """List all qualifications with computed status."""
    conn = get_db()
    cur = conn.cursor()
    
    p = ph()
    active_check = "TRUE" if USE_POSTGRES else "1"
    
    query = f"SELECT * FROM welding_qualifications WHERE is_active = {active_check}"
    params = []
    
    if welder:
        query += f" AND welder_name = {p}"
        params.append(welder)
    if aws_code:
        query += f" AND aws_code = {p}"
        params.append(aws_code)
    
    query += " ORDER BY welder_name, aws_code, procedure_id"
    
    cur.execute(query, params)
    rows = [enrich_qualification(r) for r in cur.fetchall()]
    conn.close()
    
    return rows


@router.get("/qualifications/{qual_id}")
async def get_qualification(qual_id: int):
    """Get single qualification with activity history."""
    conn = get_db()
    cur = conn.cursor()
    
    p = ph()
    
    cur.execute(f"SELECT * FROM welding_qualifications WHERE id = {p}", (qual_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Qualification not found")
    
    qual = enrich_qualification(row)
    
    # Get activity log
    cur.execute(f"SELECT * FROM welding_activity_log WHERE qualification_id = {p} ORDER BY activity_date DESC", (qual_id,))
    qual["activity_history"] = [dict(r) for r in cur.fetchall()]
    
    conn.close()
    return qual


@router.post("/qualifications")
async def create_qualification(data: QualificationCreate):
    """Add a new welder qualification."""
    conn = get_db()
    cur = conn.cursor()
    
    p = ph()
    
    try:
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO welding_qualifications 
                (welder_name, aws_code, qualification_type, procedure_id, creation_date, last_welded_on, continuity_days, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (data.welder_name, data.aws_code, data.qualification_type, data.procedure_id,
                  data.creation_date, data.last_welded_on, data.continuity_days, data.notes))
            result = cur.fetchone()
            new_id = result["id"]
        else:
            cur.execute("""
                INSERT INTO welding_qualifications 
                (welder_name, aws_code, qualification_type, procedure_id, creation_date, last_welded_on, continuity_days, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (data.welder_name, data.aws_code, data.qualification_type, data.procedure_id,
                  data.creation_date, data.last_welded_on, data.continuity_days, data.notes))
            new_id = cur.lastrowid
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
    
    return {"id": new_id, "message": "Qualification added"}


@router.put("/qualifications/{qual_id}")
async def update_qualification(qual_id: int, data: QualificationUpdate):
    """Update a qualification record."""
    conn = get_db()
    cur = conn.cursor()
    
    p = ph()
    
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields:
        conn.close()
        return {"message": "No changes"}
    
    for field, value in fields.items():
        cur.execute(f"UPDATE welding_qualifications SET {field} = {p} WHERE id = {p}", (value, qual_id))
    
    # Update timestamp
    if USE_POSTGRES:
        cur.execute(f"UPDATE welding_qualifications SET updated_at = CURRENT_TIMESTAMP WHERE id = {p}", (qual_id,))
    
    conn.commit()
    conn.close()
    return {"message": "Qualification updated"}


@router.delete("/qualifications/{qual_id}")
async def deactivate_qualification(qual_id: int):
    """Soft-delete a qualification."""
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    
    if USE_POSTGRES:
        cur.execute(f"UPDATE welding_qualifications SET is_active = FALSE WHERE id = {p}", (qual_id,))
    else:
        cur.execute(f"UPDATE welding_qualifications SET is_active = 0 WHERE id = {p}", (qual_id,))
    
    conn.commit()
    conn.close()
    return {"message": "Qualification deactivated"}


# ============================================================
# LOG WELDING ACTIVITY (update continuity)
# ============================================================

@router.post("/qualifications/{qual_id}/log-activity")
async def log_welding_activity(qual_id: int, data: ActivityLogCreate):
    """Log welding activity — updates the last_welded_on date for continuity."""
    conn = get_db()
    cur = conn.cursor()
    
    p = ph()
    
    # Verify qualification exists
    cur.execute(f"SELECT * FROM welding_qualifications WHERE id = {p}", (qual_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Qualification not found")
    
    try:
        # Log the activity
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO welding_activity_log 
                (qualification_id, activity_date, activity_type, logged_by, notes)
                VALUES (%s, %s, %s, %s, %s)
            """, (qual_id, data.activity_date, data.activity_type, data.logged_by, data.notes))
        else:
            cur.execute("""
                INSERT INTO welding_activity_log 
                (qualification_id, activity_date, activity_type, logged_by, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (qual_id, data.activity_date, data.activity_type, data.logged_by, data.notes))
        
        # If welded or requalified, update last_welded_on
        if data.activity_type in ("welded", "requalified"):
            cur.execute(f"UPDATE welding_qualifications SET last_welded_on = {p} WHERE id = {p}",
                       (data.activity_date, qual_id))
            if USE_POSTGRES:
                cur.execute(f"UPDATE welding_qualifications SET updated_at = CURRENT_TIMESTAMP WHERE id = {p}", (qual_id,))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
    
    return {"message": "Activity logged", "qualification_id": qual_id}


# ============================================================
# BULK UPDATE: Log welding for a welder across all their qualifications
# ============================================================

@router.post("/welders/{welder_name}/log-all")
async def log_all_for_welder(welder_name: str, activity_date: str = None, logged_by: str = ""):
    """Update continuity for ALL qualifications of a welder at once."""
    if not activity_date:
        activity_date = date.today().isoformat()
    
    conn = get_db()
    cur = conn.cursor()
    p = ph()
    active_check = "TRUE" if USE_POSTGRES else "1"
    
    cur.execute(f"SELECT id FROM welding_qualifications WHERE welder_name = {p} AND is_active = {active_check}", (welder_name,))
    qual_ids = [dict(r)["id"] for r in cur.fetchall()]
    
    for qid in qual_ids:
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO welding_activity_log (qualification_id, activity_date, activity_type, logged_by, notes)
                VALUES (%s, %s, 'welded', %s, 'Bulk update')
            """, (qid, activity_date, logged_by))
            cur.execute("UPDATE welding_qualifications SET last_welded_on = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                       (activity_date, qid))
        else:
            cur.execute("""
                INSERT INTO welding_activity_log (qualification_id, activity_date, activity_type, logged_by, notes)
                VALUES (?, ?, 'welded', ?, 'Bulk update')
            """, (qid, activity_date, logged_by))
            cur.execute("UPDATE welding_qualifications SET last_welded_on = ? WHERE id = ?",
                       (activity_date, qid))
    
    conn.commit()
    conn.close()
    
    return {"message": f"Updated {len(qual_ids)} qualifications for {welder_name}", "count": len(qual_ids)}


# ============================================================
# EXPORT
# ============================================================

@router.get("/export")
async def export_welding():
    """Export all welding data as JSON."""
    conn = get_db()
    cur = conn.cursor()
    
    active_check = "TRUE" if USE_POSTGRES else "1"
    
    cur.execute(f"SELECT * FROM welding_qualifications WHERE is_active = {active_check} ORDER BY welder_name, aws_code")
    quals = [enrich_qualification(r) for r in cur.fetchall()]
    
    cur.execute("SELECT * FROM welding_activity_log ORDER BY activity_date DESC")
    activities = [dict(r) for r in cur.fetchall()]
    
    conn.close()
    
    return {
        "export_date": date.today().isoformat(),
        "company": "Southern Services & Equipment Inc.",
        "document": "Welding Qualification Continuity Log",
        "qualifications": quals,
        "activity_log": activities
    }


# ============================================================
# SEED DATA — SSE Continuity Log
# ============================================================

@router.post("/seed")
async def seed_welding_data():
    """One-time seed of SSE welding continuity log data."""
    conn = get_db()
    cur = conn.cursor()
    
    p = ph()
    active_check = "TRUE" if USE_POSTGRES else "1"
    
    # Check if already seeded
    cur.execute(f"SELECT COUNT(*) as cnt FROM welding_qualifications WHERE is_active = {active_check}")
    row = cur.fetchone()
    count = dict(row).get("cnt", 0) if USE_POSTGRES else row[0]
    
    if count > 0:
        conn.close()
        return {"message": f"Database already has {count} qualifications. Seed skipped.", "seeded": False}
    
    # SSE Continuity Log data from spreadsheet
    # Format: (welder_name, aws_code, qual_type, procedure_id, creation_date, last_welded_on)
    seed_data = [
        # === AWS D1.4 WQTR qualifications ===
        ("Tyler Roberts", "AWS D1.4", "WQTR", "SSE AWS-D1.4-FC-001 WPS", "2024-09-12", "2025-06-09"),
        ("Charles Coleman", "AWS D1.4", "WQTR", "SSE AWS-D1.4-FC-001 WPS", "2024-07-19", "2025-06-09"),
        ("William Pitkin", "AWS D1.4", "WQTR", "Flare Bevel S.S D1.4/D1.6", "2025-03-07", "2025-06-09"),
        ("My Nguyen", "AWS D1.4", "WQTR", "SSE B-U2-GF", "2025-02-27", "2025-06-09"),
        ("Herbert Keaton", "AWS D1.4", "WQTR", "SSE AWS-D1.4-FC-001 WPS", "2024-08-27", "2025-06-09"),
        ("Jamone Bienemy", "AWS D1.4", "WQTR", "SSE AWS-D1.4-FC-001 WPS", "2024-09-12", "2025-06-09"),
        ("Ricardo Solis", "AWS D1.4", "WQTR", "SSE AWS-D1.4-FC-001 WPS", "2024-08-27", "2025-06-09"),
        ("Amy Tong", "AWS D1.4", "WQTR", "SSE AWS-D1.4-FC-001 WPS", "2024-08-27", "2025-06-09"),
        ("Charles Coleman", "AWS D1.4", "WQTR", "Flare Bevel S.S D1.4/D1.6", "2025-03-07", "2025-06-09"),
        ("Richard Eubanks", "AWS D1.4", "WQTR", "Flare Bevel S.S D1.4/D1.6", "2025-03-07", "2025-06-09"),
        ("Wilson Raybon", "AWS D1.4", "WQTR", "SSE B-U2-GF", "2024-09-25", "2025-06-09"),
        ("Terry Williams", "AWS D1.4", "WQTR", "SSE AWS-D1.4-FC-001 WPS", "2024-06-03", "2025-06-09"),
        ("Tyrek Lindsey", "AWS D1.4", "WQTR", "SSE AWS-D1.4-FC-001 WPS", "2024-08-27", "2025-06-09"),
        ("Shae Beckham", "AWS D1.4", "WQTR", "SSE-003 FCAW WPS", "2025-06-25", "2025-06-25"),
        ("Terry Williams", "AWS D1.4", "WQTR", "SSE B-U2-GF", "2016-12-13", "2025-11-14"),
        ("Ricardo Solis", "AWS D1.4", "WQTR", "SSE B-U2-GF", "2025-02-27", "2025-11-14"),
        
        # === AWS D1.1 WQTR qualifications ===
        ("Jamone Bienemy", "AWS D1.1", "WQTR", "SSE B-U2-GF", "2025-02-27", "2025-06-09"),
        ("Richard Eubanks", "AWS D1.1", "WQTR", "SSE D1.4-500", "2024-04-09", "2025-06-09"),
        ("Tyler Roberts", "AWS D1.1", "WQTR", "SSE B-U2-GF", "2024-01-11", "2025-06-09"),
        ("Ricardo Solis", "AWS D1.1", "WQTR", "SSE-012-GM-MC-WPS", "2025-04-25", "2025-06-09"),
        ("Jamone Bienemy", "AWS D1.1", "WQTR", "SSE-012-GM-MC-WPS", "2025-04-25", "2025-06-09"),
        ("Gagel Landry", "AWS D1.1", "WQTR", "SSE-003 FCAW WPS", "2025-07-16", "2025-07-16"),
        ("Raymond Brewer", "AWS D1.1", "WQTR", "SSE B-U2-GF", "2023-09-11", "2025-11-14"),
        ("Tharon Frederick", "AWS D1.1", "WQTR", "SSE-003 FCAW WPS", "2025-07-24", "2025-11-14"),
        ("Charles Coleman", "AWS D1.1", "WQTR", "SSE-012-GM-MC-WPS", "2025-04-02", "2025-11-14"),
        ("Charles Coleman", "AWS D1.1", "WQTR", "SSE B-U2-GF", "2025-06-01", "2025-11-14"),
        ("Amy Tong", "AWS D1.1", "WQTR", "B-L1b-GF Metal core", "2025-04-02", "2025-11-14"),
        ("Amy Tong", "AWS D1.1", "WQTR", "SSE Box Tubing", "2024-06-19", "2025-11-14"),
        ("Amy Tong", "AWS D1.1", "WQTR", "SSE B-U2-GF", "2024-11-05", "2025-11-14"),
        ("Alan Mixon", "AWS D1.1", "WQTR", "SSE B-U2-GF", "2024-11-05", "2025-11-14"),
        ("Nicholas Adams", "AWS D1.1", "WQTR", "SSE B-U2-GF", "2022-08-24", "2025-11-14"),
        ("Richard Eubanks", "AWS D1.1", "WQTR", "SSE B-U2-GF", "2023-07-10", "2025-11-14"),
        ("Tyrek Lindsey", "AWS D1.1", "WQTR", "SSE B-U2-GF", "2023-07-25", "2025-11-14"),
        ("William Pitkin", "AWS D1.1", "WQTR", "SSE B-U2-GF", "2024-01-17", "2025-11-14"),
        ("Johnny Evans", "AWS D1.1", "WQTR", "SSE B-U2-GF", "2024-12-16", "2025-11-14"),
        ("Rashied Levy", "AWS D1.1", "WQTR", "SSE B-U2-GF", "2025-08-21", "2025-11-14"),
        ("Amy Tong", "AWS D1.1", "WQTR", "D1.5 Fig 7.8 5/16\" FW", "2024-07-17", "2025-11-14"),
        ("Tyrek Lindsey", "AWS D1.1", "WQTR", "SSE-012-GM-MC-WPS", "2025-04-23", "2025-11-14"),
        ("Paul Williams", "AWS D1.1", "WQTR", "SSE B-U2-GF", "2025-06-30", "2025-11-14"),
        ("Amy Tong", "AWS D1.1", "WQTR", "SSE-012-GM-MC-WPS", "2025-04-02", "2025-11-14"),
        ("Alberto Alvarez", "AWS D1.1", "WQTR", "SSE B-U2-GF", "2026-02-02", "2026-02-02"),
        
        # === AWS D1.5 WQTR qualifications ===
        ("Michael Abarca", "AWS D1.5", "WQTR", "D1.5 Fig 7.8 5/16\" FW", "2025-08-21", "2025-08-21"),
        ("Gilbert Humphries", "AWS D1.5", "WQTR", "D1.5 Fig 7.8 5/16\" FW", "2025-08-21", "2025-08-21"),
        ("Paul Madlock", "AWS D1.5", "WQTR", "D1.5 Fig 7.8 5/16\" FW", "2025-08-21", "2025-08-21"),
        ("Eric Pham", "AWS D1.5", "WQTR", "D1.5 Fig 7.8 5/16\" FW", "2025-08-22", "2025-08-22"),
        ("Julie Mitchell", "AWS D1.5", "WQTR", "D1.5 Fig 7.8 5/16\" FW", "2025-08-22", "2025-08-22"),
        ("Vinson Pulliam", "AWS D1.5", "WQTR", "D1.5 Fig 7.8 5/16\" FW", "2025-08-26", "2025-08-26"),
        ("Ryan Lam", "AWS D1.5", "WQTR", "D1.5 Fig 7.8 5/16\" FW", "2025-08-26", "2025-08-26"),
        ("Brittany Knapper", "AWS D1.5", "WQTR", "SSE-003 FCAW WPS", "2025-09-29", "2025-09-29"),
        ("Terry Williams", "AWS D1.5", "WQTR", "SSE-012-GM-MC-WPS", "2025-04-02", "2025-11-14"),
        ("William Pitkin", "AWS D1.5", "WQTR", "SSE FC-A70/G5 FCAW WPS", "2025-06-11", "2025-11-14"),
    ]
    
    inserted = 0
    for (wname, acode, qtype, proc, cdate, lwelded) in seed_data:
        try:
            if USE_POSTGRES:
                cur.execute("""
                    INSERT INTO welding_qualifications 
                    (welder_name, aws_code, qualification_type, procedure_id, creation_date, last_welded_on, continuity_days)
                    VALUES (%s, %s, %s, %s, %s, %s, 180)
                """, (wname, acode, qtype, proc, cdate, lwelded))
            else:
                cur.execute("""
                    INSERT INTO welding_qualifications 
                    (welder_name, aws_code, qualification_type, procedure_id, creation_date, last_welded_on, continuity_days)
                    VALUES (?, ?, ?, ?, ?, ?, 180)
                """, (wname, acode, qtype, proc, cdate, lwelded))
            inserted += 1
        except Exception as e:
            print(f"Seed error for {wname}/{proc}: {e}")
    
    conn.commit()
    conn.close()
    
    return {
        "message": f"Seeded {inserted} welding qualifications from SSE Continuity Log",
        "seeded": True,
        "count": inserted
    }


# ============================================================
# WELDING PROCEDURES (WPS Document Management)
# ============================================================

SSE_PROCEDURES = [
    {"procedure_id": "SSE-003 FCAW WPS", "aws_code": "AWS D1.1", "description": "FCAW Welding Procedure Specification"},
    {"procedure_id": "SSE-012-GM-MC-WPS", "aws_code": "AWS D1.1", "description": "GMAW/Metal Core WPS"},
    {"procedure_id": "SSE B-U2-GF", "aws_code": "AWS D1.1", "description": "B-U2-GF Groove Weld WPS"},
    {"procedure_id": "B-L1b-GF Metal core", "aws_code": "AWS D1.1", "description": "B-L1b-GF Metal Core WPS"},
    {"procedure_id": "SSE Box Tubing", "aws_code": "AWS D1.1", "description": "Box Tubing Weld Procedure"},
    {"procedure_id": "SSE AWS-D1.4-FC-001 WPS", "aws_code": "AWS D1.4", "description": "D1.4 FCAW Reinforcing Steel WPS"},
    {"procedure_id": "SSE D1.4-500", "aws_code": "AWS D1.4", "description": "D1.4 500-series WPS"},
    {"procedure_id": "Flare Bevel S.S D1.4/D1.6", "aws_code": "AWS D1.4", "description": "Flare Bevel Stainless Steel WPS"},
    {"procedure_id": "SSE FC-A70/G5 FCAW WPS", "aws_code": "AWS D1.5", "description": "FC-A70/G5 FCAW Bridge WPS"},
    {"procedure_id": "D1.5 Fig 7.8 5/16", "aws_code": "AWS D1.5", "description": "D1.5 Figure 7.8 Fillet Weld WPS"},
]


@router.get("/procedures")
async def get_procedures():
    """Get all procedures with upload status."""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT id, procedure_id, aws_code, description, filename, uploaded_by, uploaded_at FROM welding_procedures")
    uploaded = {row['procedure_id']: dict(row) for row in cur.fetchall()}
    conn.close()
    
    # Merge master list with uploaded data
    result = []
    for proc in SSE_PROCEDURES:
        entry = {**proc, "has_file": False, "filename": None, "uploaded_by": None, "uploaded_at": None, "db_id": None}
        if proc["procedure_id"] in uploaded:
            up = uploaded[proc["procedure_id"]]
            entry["has_file"] = True
            entry["filename"] = up["filename"]
            entry["uploaded_by"] = up["uploaded_by"]
            entry["uploaded_at"] = up["uploaded_at"]
            entry["db_id"] = up["id"]
        result.append(entry)
    
    return result


@router.post("/procedures/upload")
async def upload_procedure(
    procedure_id: str = Form(...),
    uploaded_by: str = Form(""),
    file: UploadFile = File(...)
):
    """Upload a WPS PDF for a procedure."""
    # Validate procedure exists in master list
    valid_ids = [p["procedure_id"] for p in SSE_PROCEDURES]
    if procedure_id not in valid_ids:
        raise HTTPException(status_code=400, detail=f"Unknown procedure: {procedure_id}")
    
    # Read file and encode as base64
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")
    
    b64_data = base64.b64encode(content).decode('utf-8')
    aws_code = next(p["aws_code"] for p in SSE_PROCEDURES if p["procedure_id"] == procedure_id)
    description = next(p["description"] for p in SSE_PROCEDURES if p["procedure_id"] == procedure_id)
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        if USE_POSTGRES:
            # Upsert - update if exists, insert if not
            cur.execute("""
                INSERT INTO welding_procedures (procedure_id, aws_code, description, filename, file_data, content_type, uploaded_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (procedure_id) DO UPDATE SET 
                    filename = EXCLUDED.filename, 
                    file_data = EXCLUDED.file_data,
                    content_type = EXCLUDED.content_type,
                    uploaded_by = EXCLUDED.uploaded_by,
                    uploaded_at = CURRENT_TIMESTAMP
            """, (procedure_id, aws_code, description, file.filename, b64_data, file.content_type or 'application/pdf', uploaded_by))
        else:
            cur.execute(f"DELETE FROM welding_procedures WHERE procedure_id = ?", (procedure_id,))
            cur.execute("""
                INSERT INTO welding_procedures (procedure_id, aws_code, description, filename, file_data, content_type, uploaded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (procedure_id, aws_code, description, file.filename, b64_data, file.content_type or 'application/pdf', uploaded_by))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
    
    return {"message": f"Uploaded {file.filename} for {procedure_id}", "success": True}


@router.get("/procedures/{procedure_id}/download")
async def download_procedure(procedure_id: str):
    """Download a WPS PDF."""
    conn = get_db()
    cur = conn.cursor()
    
    if USE_POSTGRES:
        cur.execute("SELECT filename, file_data, content_type FROM welding_procedures WHERE procedure_id = %s", (procedure_id,))
    else:
        cur.execute("SELECT filename, file_data, content_type FROM welding_procedures WHERE procedure_id = ?", (procedure_id,))
    
    row = cur.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Procedure document not found")
    
    row = dict(row)
    file_bytes = base64.b64decode(row['file_data'])
    
    return Response(
        content=file_bytes,
        media_type=row['content_type'] or 'application/pdf',
        headers={"Content-Disposition": f"inline; filename=\"{row['filename']}\""}
    )


@router.delete("/procedures/{procedure_id}/file")
async def delete_procedure_file(procedure_id: str):
    """Remove uploaded file for a procedure."""
    conn = get_db()
    cur = conn.cursor()
    
    if USE_POSTGRES:
        cur.execute("DELETE FROM welding_procedures WHERE procedure_id = %s", (procedure_id,))
    else:
        cur.execute("DELETE FROM welding_procedures WHERE procedure_id = ?", (procedure_id,))
    
    conn.commit()
    conn.close()
    return {"message": f"Removed file for {procedure_id}"}
