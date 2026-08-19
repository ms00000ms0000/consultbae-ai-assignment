# Task 4 — Data Issues Report

Found by inspecting the 3 raw CSVs directly and confirmed programmatically in
`db/merge_pipeline.py`. Each issue below states what it is, where, and what
the pipeline does about it.

---

### 1. Inconsistent phone number formats (all 3 sources)
Same real phone number appears as `9000000268`, `919000000268`,
`+91-9000000131`, `09000000287` etc. across rows/sources.
**Fix:** `norm_phone()` strips all non-digits and keeps the last 10 digits,
so all formats collapse to one canonical key used for matching.

### 2. Inconsistent email casing (source2 — gig workers)
Several emails are `UPPERCASE@EXAMPLE.COM` while the same person's email
elsewhere is lowercase (e.g. `DEEPAK.NAIR44@EXAMPLE.COM` vs
`deepak.nair44@example.com`). Case-sensitive matching would treat these as
different people.
**Fix:** `norm_email()` lowercases and strips whitespace before comparison.

### 3. Inconsistent city names / casing / trailing whitespace (all sources)
`"Noida "`, `"NOIDA"`, `"noida"` all refer to one city. Also regional
aliases: `"Gurugram"` == `"Gurgaon"`, `"Bangalore"` == `"Bengaluru"`,
`"New Delhi"` / `"Delhi NCR"` == `"Delhi"`.
**Fix:** `norm_city()` lowercases, collapses whitespace, and maps known
aliases to one canonical spelling.

### 4. Internal duplicates within source1 (Naukri applicants)
- "R. Verma" and "Rohit Verma" — identical phone, email, and city. Same
  person entered twice with a shortened name.
- "Nikhil Chopra" appears twice with the same phone, one row using an
  `alt.nikhil.chopra70@example.com` alias email.
**Fix:** these collapse automatically since the merge pipeline matches on
phone/email across ALL rows, including within a single source — not just
across sources.

### 5. Completely blank row (source2, gig workers)
One row is entirely empty (all fields `NaN`).
**Fix:** dropped before matching — `merge_pipeline.py::load_source2()`
filters `df.isnull().all(axis=1)`.

### 6. Column-shifted / corrupted row (source2, gig workers)
One row has its values shifted across the wrong columns — a skill-tag
string sits in `worker_name`, and an email sits partway into `email_id`
merged with other misplaced text (visible around "ISHA.CHOPRA95..." row).
This isn't a formatting issue, it's structurally broken — no email or name
can be trusted from it.
**Fix:** dropped rather than guessed at — a row is treated as corrupt if
`email_id` doesn't contain "@", since a real row always has a valid email
there.

### 7. Embedded duplicate header row (source3, CBNexus contacts)
The literal header line (`Name,Phone Number,City,Verified,Projects
Completed`) reappears as a data row partway through the file, likely from a
bad CSV concatenation upstream.
**Fix:** dropped by checking for the literal string `"Name"` in the Name
column.

### 8. Same name, genuinely different people (all sources)
"Arjun Mehta" appears with **two different phone numbers**
(`9000000131` and `9000000272`) across the files — these are two distinct
real people who happen to share a name, not a duplicate. Same pattern for
"Deepak Nair" (two different emails, `deepak.nair44@...` and
`deepak.nair57@...`).
**Fix:** the pipeline deliberately does NOT match on name alone — only on
normalized phone or email — so these correctly stay as separate people.
This was a conscious design decision (see README/matching-logic comment in
`merge_pipeline.py`), because name-based fuzzy matching would have wrongly
merged them.

### 9. `source3` has no email field, `source2` has no phone field
Neither source alone can be cross-referenced against the other directly —
matching between them only works transitively, through a row in `source1`
that shares a phone with one and an email with the other.
**Fix:** union-find merge logic in `merge_all()` handles this correctly:
if row A (source1) shares an email with row B (source2) and a phone with
row C (source3), all three end up in the same merged-person group even
though B and C have no direct key in common.

---

### Result
102 raw rows across the 3 files → **60 unique people** after merge
(full breakdown of which sources each person appears in is in
`docs/pipeline_issues_log.txt`, regenerated each time
`db/merge_pipeline.py` runs).
