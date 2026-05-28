# ============================================================
# MyTimes 6-File System — Data Utilities
# ============================================================
import io
import numpy as np
import pandas as pd
import streamlit as st
from config_styles import SEMESTER_WEEKS, DEFAULT_MIN, DEFAULT_MAX, SCORE_PREF, SCORE_NOT_PREF, COMPENSATION_POINTS


def clean_text(x):
    if pd.isna(x):
        return ""
    x = str(x).strip().upper()
    if x in ["NAN", "NONE", "-", ""]:
        return ""
    return x


def clean_name(x):
    if pd.isna(x):
        return ""
    return str(x).strip()


def standardize_status(x):
    x = clean_text(x)
    if x in ["", "BUKA", "OPEN", "AKTIF", "ACTIVE"]:
        return "BUKA"
    if x in ["BARU", "BAHARU", "NEW"]:
        return "BARU"
    if x in ["TUTUP", "CLOSE", "CLOSED", "BATAL", "CANCEL", "CANCELLED"]:
        return "TUTUP"
    return x


def yes_no(x):
    x = clean_text(x)
    return "YA" if x in ["YA", "YES", "Y", "TRUE", "1"] else "TIDAK"


def read_file(uploaded_file, expected_sheet=None):
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file, encoding="utf-8-sig")
    xl = pd.ExcelFile(uploaded_file)
    if expected_sheet and expected_sheet in xl.sheet_names:
        return pd.read_excel(uploaded_file, sheet_name=expected_sheet)
    return pd.read_excel(uploaded_file, sheet_name=xl.sheet_names[0])


def to_excel_bytes(dfs):
    with io.BytesIO() as buffer:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            for name, df in dfs.items():
                safe = name[:31]
                if df is None:
                    df = pd.DataFrame()
                df.to_excel(writer, index=False, sheet_name=safe)
        return buffer.getvalue()


def prepare_class_data(file_classes):
    df = read_file(file_classes, expected_sheet="Jadual_Kelas").copy()
    required = ["kod_kursus", "kelas_baru", "ks"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"Fail Jadual Kelas tiada column wajib: {missing}")
        st.stop()

    df["kod_kursus"] = df["kod_kursus"].map(clean_text)
    df["kelas_baru"] = df["kelas_baru"].astype(str).str.strip()
    df["ks"] = pd.to_numeric(df["ks"], errors="coerce").fillna(0).astype(int)

    defaults = {
        "status_kelas": "BUKA",
        "saiz_kelas": 0,
        "campuran_group": "",
        "perincian": "",
        "pensyarah_asal": "",
        "lock_agihan": "TIDAK",
        "share_allowed": "TIDAK",
        "minggu_mula_kelas": 1,
        "minggu_akhir_kelas": SEMESTER_WEEKS,
    }
    for col, val in defaults.items():
        if col not in df.columns:
            df[col] = val

    df["status_kelas"] = df["status_kelas"].map(standardize_status)
    df["share_allowed"] = df["share_allowed"].map(yes_no)
    df["lock_agihan"] = df["lock_agihan"].map(yes_no)
    df["saiz_kelas"] = pd.to_numeric(df["saiz_kelas"], errors="coerce").fillna(0).astype(int)
    df["minggu_mula_kelas"] = pd.to_numeric(df["minggu_mula_kelas"], errors="coerce").fillna(1).astype(int).clip(1, SEMESTER_WEEKS)
    df["minggu_akhir_kelas"] = pd.to_numeric(df["minggu_akhir_kelas"], errors="coerce").fillna(SEMESTER_WEEKS).astype(int).clip(1, SEMESTER_WEEKS)

    df = df[(df["kod_kursus"] != "") & (df["kelas_baru"] != "") & (df["ks"] > 0)].copy()
    df["kelas_id"] = df["kod_kursus"] + "-" + df["kelas_baru"].astype(str)
    df = df.drop_duplicates(subset=["kelas_id"], keep="last").copy()
    return df


def prepare_lecturer_data(file_lect):
    raw = read_file(file_lect, expected_sheet="Pensyarah").copy()
    required = ["Nama Pensyarah", "Peranan", "Minimum KS", "Maksimum KS"]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        st.error(f"Fail Pensyarah tiada column wajib: {missing}")
        st.stop()

    df = raw.rename(columns={
        "Nama Pensyarah": "nama",
        "Peranan": "peranan",
        "Minimum KS": "min_ks",
        "Maksimum KS": "max_ks",
    }).copy()

    df["nama"] = df["nama"].map(clean_name)
    df["peranan"] = df["peranan"].astype(str).str.strip()
    df["min_ks"] = pd.to_numeric(df["min_ks"], errors="coerce").fillna(DEFAULT_MIN).astype(int)
    df["max_ks"] = pd.to_numeric(df["max_ks"], errors="coerce").fillna(DEFAULT_MAX).astype(int)
    df.loc[df["min_ks"] > df["max_ks"], "min_ks"] = df["max_ks"]

    for i in range(1, 6):
        col = f"Pilihan {i}"
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].map(clean_text)

    if "status" not in df.columns:
        df["status"] = "AKTIF"
    df["status"] = df["status"].map(clean_text).replace({"": "AKTIF"})

    if "minggu_mula_available" not in df.columns:
        df["minggu_mula_available"] = 1
    if "minggu_akhir_available" not in df.columns:
        df["minggu_akhir_available"] = SEMESTER_WEEKS

    df["minggu_mula_available"] = pd.to_numeric(df["minggu_mula_available"], errors="coerce").fillna(1).astype(int).clip(1, SEMESTER_WEEKS)
    df["minggu_akhir_available"] = pd.to_numeric(df["minggu_akhir_available"], errors="coerce").fillna(SEMESTER_WEEKS).astype(int).clip(1, SEMESTER_WEEKS)

    cuti_mask = df["status"].isin(["CUTI", "TIDAK_AKTIF", "SABBATICAL", "CUTI_BERSALIN"])
    df["active"] = ~cuti_mask

    # Optional carry-forward priority from previous semester.
    # If the uploaded lecturer file contains this column, MyTimes will use it
    # to give higher priority to lecturers who did not receive preferred subjects previously.
    if "compensation_points" not in df.columns:
        df["compensation_points"] = 0
    df["compensation_points"] = pd.to_numeric(df["compensation_points"], errors="coerce").fillna(0).astype(int).clip(0, 30)

    df = df[df["nama"] != ""].drop_duplicates(subset=["nama"], keep="first").copy()
    return df


def build_preference_score(dfl):
    pref = {}
    for _, row in dfl.iterrows():
        lname = row["nama"]
        for i in range(1, 6):
            subj = clean_text(row.get(f"Pilihan {i}", ""))
            if subj:
                pref[(lname, subj)] = SCORE_PREF[i]
    return pref


def get_pref_score(lname, subject, pref):
    return int(pref.get((lname, subject), SCORE_NOT_PREF))


def get_pref_label(lname, subject, dfl):
    row = dfl[dfl["nama"] == lname]
    if row.empty:
        return "Tidak diketahui"
    row = row.iloc[0]
    for i in range(1, 6):
        if clean_text(row.get(f"Pilihan {i}", "")) == subject:
            return f"Pilihan {i}"
    return "Bukan pilihan"


def is_available_for_class(lect_row, class_row):
    return max(int(lect_row["minggu_mula_available"]), int(class_row["minggu_mula_kelas"])) <= min(
        int(lect_row["minggu_akhir_available"]), int(class_row["minggu_akhir_kelas"])
    )


def get_compensation_points(preference_label):
    """Return carry-forward points for next semester based on current allocation satisfaction."""
    label = str(preference_label).strip()
    label = label.replace("Pilihan", "Choice").replace("Bukan pilihan", "Not Preferred")
    return int(COMPENSATION_POINTS.get(label, 0))


def get_preference_reason(preference_label, total_ks=None, min_ks=None, max_ks=None):
    """Human-readable reason for allocation, especially when not first choice."""
    label = str(preference_label).strip()
    if label in ["Pilihan 1", "Choice 1"]:
        return "First preference matched."
    if label in ["Pilihan 2", "Choice 2", "Pilihan 3", "Choice 3", "Pilihan 4", "Choice 4", "Pilihan 5", "Choice 5"]:
        return "Assigned to available preference because higher preference was constrained by class availability, lecturer load, or fairness limits."
    if label in ["Bukan pilihan", "Not Preferred"]:
        if total_ks is not None and min_ks is not None and total_ks < min_ks:
            return "Assigned for workload balancing because the lecturer was below minimum KS and preferred subjects were not feasible."
        if total_ks is not None and max_ks is not None and total_ks >= max_ks:
            return "Assigned due to operational requirement while keeping workload within allowed KS limit."
        return "Assigned due to workload balancing or no feasible preferred-subject allocation under current constraints."
    return "Allocation generated by MyTimes optimization constraints."
