"""
Called by n8n's Execute Command node with two CLI args: person id, category.
Updates that person's skill_category in the DB.

Usage: python update_skill_category.py <id> <category>
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "consultbae.db"


def main():
    person_id = sys.argv[1]
    category = sys.argv[2]
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE people SET skill_category = ? WHERE id = ?",
        (category, person_id),
    )
    conn.commit()
    conn.close()
    print(f"updated id={person_id} -> {category}")


if __name__ == "__main__":
    main()
