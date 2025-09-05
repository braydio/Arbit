"""SQLite persistence layer with simple insert helpers."""

from __future__ import annotations

import sqlite3
from sqlite3 import Connection

from ..models import Fill, Triangle, TriangleAttempt


def init_db(db_path: str = "arbit.db") -> Connection:
    """Create a database connection and ensure required tables exist."""
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    return conn


def create_schema(conn: Connection) -> None:
    """Create database tables if they are missing."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS triangles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            leg_ab TEXT NOT NULL,
            leg_bc TEXT NOT NULL,
            leg_ac TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            price REAL NOT NULL,
            quantity REAL NOT NULL,
            fee REAL NOT NULL,
            timestamp TEXT,
            venue TEXT,
            leg TEXT,
            tif TEXT,
            order_type TEXT,
            fee_rate REAL,
            notional REAL,
            dry_run INTEGER,
            attempt_id INTEGER
        )
        """
    )
    # Attempts: per-triangle attempt (success or skip) with rich metadata
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS triangle_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_iso TEXT,
            venue TEXT,
            leg_ab TEXT,
            leg_bc TEXT,
            leg_ac TEXT,
            ok INTEGER,
            net_est REAL,
            realized_usdt REAL,
            threshold_bps REAL,
            notional_usd REAL,
            slippage_bps REAL,
            dry_run INTEGER,
            latency_ms REAL,
            skip_reasons TEXT,
            ab_bid REAL, ab_ask REAL,
            bc_bid REAL, bc_ask REAL,
            ac_bid REAL, ac_ask REAL,
            qty_base REAL
        )
        """
    )
    # Backfill migration: add new columns to fills if missing (safe no-op)
    cur.execute("PRAGMA table_info(fills)")
    cols = {r[1] for r in cur.fetchall()}
    add_cols = [
        ("venue", "TEXT"),
        ("leg", "TEXT"),
        ("tif", "TEXT"),
        ("order_type", "TEXT"),
        ("fee_rate", "REAL"),
        ("notional", "REAL"),
        ("dry_run", "INTEGER"),
        ("attempt_id", "INTEGER"),
    ]
    for name, typ in add_cols:
        if name not in cols:
            cur.execute(f"ALTER TABLE fills ADD COLUMN {name} {typ}")
    conn.commit()


def insert_triangle(conn: Connection, triangle: Triangle) -> int:
    """Insert a triangle record and return its row id."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO triangles (leg_ab, leg_bc, leg_ac) VALUES (?, ?, ?)",
        (triangle.leg_ab, triangle.leg_bc, triangle.leg_ac),
    )
    conn.commit()
    return cur.lastrowid


def insert_fill(conn: Connection, fill: Fill) -> int:
    """Insert a fill record and return its row id."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO fills (
            order_id, symbol, side, price, quantity, fee, timestamp,
            venue, leg, tif, order_type, fee_rate, notional, dry_run, attempt_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fill.order_id,
            fill.symbol,
            fill.side,
            fill.price,
            fill.quantity,
            fill.fee,
            fill.timestamp.isoformat() if fill.timestamp else None,
            fill.venue,
            fill.leg,
            fill.tif,
            fill.order_type,
            fill.fee_rate,
            fill.notional,
            int(fill.dry_run) if isinstance(fill.dry_run, bool) else None,
            fill.attempt_id,
        ),
    )
    conn.commit()
    return cur.lastrowid


def insert_attempt(conn: Connection, a: TriangleAttempt) -> int:
    """Insert a triangle attempt and return its row id."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO triangle_attempts (
            ts_iso, venue, leg_ab, leg_bc, leg_ac, ok, net_est, realized_usdt,
            threshold_bps, notional_usd, slippage_bps, dry_run, latency_ms,
            skip_reasons, ab_bid, ab_ask, bc_bid, bc_ask, ac_bid, ac_ask, qty_base
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            a.ts_iso,
            a.venue,
            a.leg_ab,
            a.leg_bc,
            a.leg_ac,
            int(a.ok),
            a.net_est,
            a.realized_usdt,
            a.threshold_bps,
            a.notional_usd,
            a.slippage_bps,
            int(a.dry_run) if isinstance(a.dry_run, bool) else None,
            a.latency_ms,
            a.skip_reasons,
            a.ab_bid,
            a.ab_ask,
            a.bc_bid,
            a.bc_ask,
            a.ac_bid,
            a.ac_ask,
            a.qty_base,
        ),
    )
    conn.commit()
    return cur.lastrowid
