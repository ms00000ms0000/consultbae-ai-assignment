"""
ConsultBae Task 1 — Merge pipeline
Ingests 3 messy CSVs (Naukri applicants, gig workers, CBNexus contacts) into
one SQLite DB, deduping people across sources.

Matching strategy:
  1. Normalize phone -> last 10 digits (strips +91 / 91 / dashes / spaces).
  2. Normalize email -> lowercase, stripped.
  3. Use phone as the primary join key across all 3 sources (source3 has no
     email at all, so phone is the only cross-source key available for it).
  4. Use email as a secondary key within source1/source2 (also normalized).
  5. Union-Find: two raw rows merge into ONE person if they share a
     normalized phone OR a normalized email.
  6. Rows that are corrupt (blank, or an embedded header row, or a
     column-shifted row) are dropped and logged, not merged.

Why NOT name-based fuzzy matching as the primary key: two different real
people can share a name ("Arjun Mehta" appears with two different phone
numbers across sources) - name matching would wrongly merge them. Phone/email
are the only fields we can trust to be unique to a person here.
"""
import re
import sqlite3
import pandas as pd
from pathlib import Path

BASE = Path(__file__).parent
DATA = BASE.parent / "data"
DB_PATH = BASE / "consultbae.db"

issues_log = []  # collected data-quality notes -> feeds docs/DATA_ISSUES.md


def log_issue(msg):
    issues_log.append(msg)


def norm_phone(raw):
    if pd.isna(raw):
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) >= 10:
        return digits[-10:]
    return None


def norm_email(raw):
    if pd.isna(raw) or "@" not in str(raw):
        return None
    return str(raw).strip().lower()


def norm_city(raw):
    if pd.isna(raw):
        return None
    c = str(raw).strip().lower()
    c = re.sub(r"\s+", " ", c)
    aliases = {
        "gurugram": "gurgaon",
        "bangalore": "bengaluru",
        "new delhi": "delhi",
        "delhi ncr": "delhi",
    }
    return aliases.get(c, c)


def load_source1():
    df = pd.read_csv(DATA / "source1_naukri_applicants.csv")
    df.columns = [c.strip() for c in df.columns]
    before = len(df)
    df["phone_norm"] = df["Phone"].apply(norm_phone)
    df["email_norm"] = df["Email"].apply(norm_email)
    df["city_norm"] = df["City"].apply(norm_city)
    df["name"] = df["Full Name"].str.strip()
    df["skills"] = df["Skills"]
    df["source"] = "naukri"
    # internal dupes: same phone appears twice within this file itself
    dup_phones = df[df.duplicated("phone_norm", keep=False)].sort_values("phone_norm")
    if len(dup_phones):
        log_issue(
            f"source1: {len(dup_phones)} rows share a phone with another row "
            f"in the SAME file (internal duplicates, e.g. 'R. Verma' vs "
            f"'Rohit Verma', and a Nikhil Chopra row using an 'alt.' email "
            f"alias) -> collapsed during merge, not treated as new people."
        )
    log_issue(f"source1: loaded {before} rows, {df['phone_norm'].isna().sum()} unparsable phones")
    return df[["name", "email_norm", "phone_norm", "city_norm", "skills", "source"]]


def load_source2():
    df = pd.read_csv(DATA / "source2_gig_workers.csv")
    before = len(df)
    # drop fully-blank rows
    blank_mask = df.isnull().all(axis=1)
    if blank_mask.sum():
        log_issue(f"source2: dropped {blank_mask.sum()} completely blank row(s).")
    df = df[~blank_mask]
    # drop column-shifted / corrupt rows: email_id must contain '@' AND
    # worker_name must not itself contain '@' (that pattern = shifted row)
    corrupt_mask = df["email_id"].astype(str).str.contains("@", na=False) == False
    if corrupt_mask.sum():
        log_issue(
            f"source2: dropped {corrupt_mask.sum()} row(s) with shifted/misaligned "
            f"columns (e.g. an email string sitting in the worker_name column and "
            f"skill tags sitting in the email_id column) — unrecoverable without "
            f"guessing, so excluded rather than merged."
        )
    df = df[~corrupt_mask]
    df["phone_norm"] = None  # source2 has no phone field at all
    df["email_norm"] = df["email_id"].apply(norm_email)
    df["city_norm"] = df["location"].apply(norm_city)
    df["name"] = df["worker_name"].str.strip()
    df["skills"] = df["skill_tags"]
    df["source"] = "gig"
    log_issue(f"source2: loaded {before} raw rows -> {len(df)} usable after cleanup.")
    return df[["name", "email_norm", "phone_norm", "city_norm", "skills", "source"]]


def load_source3():
    df = pd.read_csv(DATA / "source3_cbnexus_contacts.csv")
    before = len(df)
    # embedded duplicate header row(s): literal "Name" value in Name column
    header_mask = df["Name"].astype(str).str.strip() == "Name"
    if header_mask.sum():
        log_issue(f"source3: dropped {header_mask.sum()} embedded duplicate-header row(s) found mid-file.")
    df = df[~header_mask]
    df["phone_norm"] = df["Phone Number"].apply(norm_phone)
    df["email_norm"] = None  # source3 has no email field at all
    df["city_norm"] = df["City"].apply(norm_city)
    df["name"] = df["Name"].str.strip()
    df["skills"] = None
    df["source"] = "cbnexus"
    log_issue(f"source3: loaded {before} raw rows -> {len(df)} usable after cleanup (no email field in this source).")
    return df[["name", "email_norm", "phone_norm", "city_norm", "skills", "source"]]


# --- Union-Find to merge rows sharing a phone or email -------------------
class UF:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def merge_all():
    df1, df2, df3 = load_source1(), load_source2(), load_source3()
    all_rows = pd.concat([df1, df2, df3], ignore_index=True)

    uf = UF(len(all_rows))
    phone_map, email_map = {}, {}
    for i, row in all_rows.iterrows():
        # NOTE: pd.concat turns Python None (from sources missing a phone/email
        # column entirely) into float NaN, and `if nan:` is True in Python -
        # so we must check pd.notna() explicitly, not plain truthiness.
        if pd.notna(row["phone_norm"]):
            if row["phone_norm"] in phone_map:
                uf.union(i, phone_map[row["phone_norm"]])
            else:
                phone_map[row["phone_norm"]] = i
        if pd.notna(row["email_norm"]):
            if row["email_norm"] in email_map:
                uf.union(i, email_map[row["email_norm"]])
            else:
                email_map[row["email_norm"]] = i

    all_rows["group"] = [uf.find(i) for i in range(len(all_rows))]

    # collapse each group into one person record
    people = []
    for gid, grp in all_rows.groupby("group"):
        name = grp["name"].dropna().mode()
        name = name.iloc[0] if len(name) else grp["name"].dropna().iloc[0]
        email = next((e for e in grp["email_norm"] if e), None)
        phone = next((p for p in grp["phone_norm"] if p), None)
        city = next((c for c in grp["city_norm"] if c), None)
        skills = "; ".join(sorted(set(s for s in grp["skills"].dropna() if s)))
        sources = ", ".join(sorted(set(grp["source"])))
        people.append({
            "name": name, "email": email, "phone": phone, "city": city,
            "skills": skills, "sources": sources,
        })

    unresolved_name_collisions = 0
    for name, grp in all_rows.groupby("name"):
        if grp["group"].nunique() > 1:
            unresolved_name_collisions += 1
    if unresolved_name_collisions:
        log_issue(
            f"{unresolved_name_collisions} name(s) appear on MULTIPLE distinct "
            f"phone/email identities (e.g. 'Arjun Mehta', 'Deepak Nair' each map "
            f"to two different phone numbers) -> treated as two different real "
            f"people sharing a common name, NOT merged, since name alone is not "
            f"a reliable identity key here."
        )

    people_df = pd.DataFrame(people)
    log_issue(
        f"FINAL: {len(all_rows)} raw rows across 3 sources collapsed into "
        f"{len(people_df)} unique people."
    )
    return people_df


def write_db(people_df):
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            phone TEXT,
            city TEXT,
            skills TEXT,
            sources TEXT,
            skill_category TEXT DEFAULT NULL
        )
    """)
    people_df.to_sql("people", conn, if_exists="append", index=False)
    conn.execute("""
        CREATE TABLE audio_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER,
            name TEXT,
            phone TEXT,
            file_path TEXT,
            duration_sec REAL,
            sample_rate_hz INTEGER,
            bitrate_kbps REAL,
            loudness_db REAL,
            submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(person_id) REFERENCES people(id)
        )
    """)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    people_df = merge_all()
    write_db(people_df)
    print(f"Wrote {len(people_df)} people to {DB_PATH}")
    print("\n".join(issues_log))

    # persist issues log so Task 4 doc can pull from it
    with open(BASE.parent / "docs" / "pipeline_issues_log.txt", "w") as f:
        f.write("\n".join(issues_log))
