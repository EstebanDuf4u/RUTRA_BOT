# db.py
import os
import mysql.connector
from mysql.connector import Error


def get_db():
    """
    Connexion MySQL (MariaDB OK).
    Variables d'environnement attendues :
      DB_HOST, DB_USER, DB_PASS, DB_NAME
    """
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", ""),
        database=os.getenv("DB_NAME", "bot_rutra_db"),
        charset="utf8mb4",
        autocommit=False,
    )


def db_exec(query: str, params: tuple = ()):
    """
    Execute une requête (INSERT/UPDATE/DELETE).
    """
    db = None
    cur = None
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute(query, params)
        db.commit()
    finally:
        if cur:
            cur.close()
        if db:
            db.close()


def db_fetchall(query: str, params: tuple = ()):
    """
    Execute un SELECT et retourne fetchall().
    """
    db = None
    cur = None
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute(query, params)
        return cur.fetchall()
    finally:
        if cur:
            cur.close()
        if db:
            db.close()


def db_fetchone(query: str, params: tuple = ()):
    """
    Execute un SELECT et retourne fetchone().
    """
    db = None
    cur = None
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute(query, params)
        return cur.fetchone()
    finally:
        if cur:
            cur.close()
        if db:
            db.close()
