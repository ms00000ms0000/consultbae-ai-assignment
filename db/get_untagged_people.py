"""
Called by n8n's Execute Command node.
Prints JSON array of people who still need a skill_category, so n8n can
loop over them and call Gemini for each.
"""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "consultbae.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, name, skills FROM people "
        "WHERE skills IS NOT NULL AND skills != '' AND skill_category IS NULL"
    ).fetchall()
    conn.close()
    print(json.dumps([dict(r) for r in rows]))


if __name__ == "__main__":
    main()
