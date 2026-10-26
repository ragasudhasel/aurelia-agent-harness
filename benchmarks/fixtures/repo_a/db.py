"""Database access module with intentional SQL injection vulnerability."""

import sqlite3

class UserRepository:
    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path)
        self._init_db()

    def _init_db(self):
        cursor = self.conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, role TEXT)")
        cursor.execute("INSERT INTO users (username, role) VALUES ('admin', 'superuser')")
        self.conn.commit()

    def find_user_by_name(self, username: str) -> list:
        cursor = self.conn.cursor()
        # SECURITY VULNERABILITY: Raw string interpolation enables SQL injection!
        query = f"SELECT * FROM users WHERE username = '{username}'"
        cursor.execute(query)
        return cursor.fetchall()
