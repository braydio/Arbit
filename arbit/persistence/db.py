"""SQLite persistence layer with simple insert helpers."""

from __future__ import annotations

import sqlite3
from sqlite3 import Connection

from ..models import Fill, Triangle


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
            timestamp TEXT
        )
        """
    )
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
            order_id, symbol, side, price, quantity, fee, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fill.order_id,
            fill.symbol,
            fill.side,
            fill.price,
            fill.quantity,
            fill.fee,
            fill.timestamp.isoformat() if fill.timestamp else None,
        ),
    )
    conn.commit()
    return cur.lastrowid

