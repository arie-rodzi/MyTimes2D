# ============================================================
# MyTimes 6-File System — Main App
# pip install streamlit pandas numpy openpyxl pulp plotly
# streamlit run app.py
# ============================================================
import pandas as pd
import streamlit as st
import time

try:
    import plotly.express as px
except Exception:
    px = None

from config_styles import SEMESTER_WEEKS
from ui_components import apply_page_config, hero, section, metric_card, soft_card_html
from data_utils import prepare_class_data, prepare_lecturer_data, build_preference_score, to_excel_bytes, clean_text, standardize_status
from optimizer import solve_allocation, build_outputs
from emergency_engine import ensure_emergency_log, compute_emergency_reallocation


def _parse_week_text(text):
    """Parse week text like '4-14' or '7' into list of integers."""
    if pd.isna(text) or str(text).strip() == "":
        return []
    text = str(text).strip()
    if "-" in text:
        a, b = text.split("-", 1)
        try:
            a, b = int(float(a)), int(float(b))
            return list(range(min(a, b), max(a, b) + 1))
        except Exception:
            return []
    try:
        return [int(float(text))]
    except Exception:
        return []


def build_weekly_lecturer_analysis(df_assign, df_summary, emergency_log=None, semester_code=""):
    """Create a week-by-week workload view.

    This is the fairer workload basis:
    average_semester_load = (Week_mula + ... + Week_akhir) / jumlah_minggu_available
    """
    week_cols = [f"Week_{i}_KS" for i in range(1, SEMESTER_WEEKS + 1)]
    if df_summary is None or df_summary.empty:
        return pd.DataFrame(), pd.DataFrame()

    base_cols = ["pensyarah", "peranan", "jumlah_KS", "minimum_KS", "maksimum_KS", "status_load"]
    base_cols = [c for c in base_cols if c in df_summary.columns]
    weekly = df_summary[base_cols].copy()
    weekly.insert(0, "semester_code", semester_code)
    for c in week_cols:
        weekly[c] = 0.0

    def add_load(lecturer, weeks, ks):
        lecturer = str(lecturer).strip()
        if not lecturer or lecturer.upper().startswith("NO "):
            return
        mask = weekly["pensyarah"] == lecturer
        if not mask.any():
            return
        for w in weeks:
            try:
                w = int(w)
            except Exception:
                continue
            if 1 <= w <= SEMESTER_WEEKS:
                weekly.loc[mask, f"Week_{w}_KS"] += float(ks)

    def sub_load(lecturer, weeks, ks):
        lecturer = str(lecturer).strip()
        if not lecturer or lecturer.upper().startswith("NO "):
            return
        mask = weekly["pensyarah"] == lecturer
        if not mask.any():
            return
        for w in weeks:
            try:
                w = int(w)
            except Exception:
                continue
            if 1 <= w <= SEMESTER_WEEKS:
                weekly.loc[mask, f"Week_{w}_KS"] -= float(ks)

    event_rows = []

    # Base allocation across class weeks.
    if df_assign is not None and not df_assign.empty:
        for _, r in df_assign.iterrows():
            weeks = list(range(int(r.get("minggu_mula_kelas", 1)), int(r.get("minggu_akhir_kelas", SEMESTER_WEEKS)) + 1))
            primary = r.get("pensyarah_utama", "")
            ks = float(r.get("KS", 0))
            add_load(primary, weeks, ks)

            # Temporary cover for late entry lecturer
            cover = str(r.get("pensyarah_cover_sementara", "")).strip()
            if cover:
                cover_weeks = _parse_week_text(r.get("minggu_cover_sementara", ""))
                if cover_weeks:
                    sub_load(primary, cover_weeks, ks)
                    add_load(cover, cover_weeks, ks)

                    week_text = r.get("minggu_cover_sementara", "")
                    event_rows.append({
                        "semester_code": semester_code,
                        "event_category": "Temporary Cover",
                        "lecturer": cover,
                        "event_role": "Temporary cover lecturer",
                        "affected_lecturer": primary,
                        "subject_code": r.get("kod_kursus", ""),
                        "class_group": r.get("kelas_baru", ""),
                        "weeks": week_text,
                        "KS_change": ks,
                        "reason": "Original lecturer starts after the class begins.",
                        "note": f"{cover} covers {primary} for Week {week_text}; {primary} resumes after the temporary cover period.",
                    })
                    event_rows.append({
                        "semester_code": semester_code,
                        "event_category": "Temporary Cover",
                        "lecturer": primary,
                        "event_role": "Original lecturer returns",
                        "affected_lecturer": cover,
                        "subject_code": r.get("kod_kursus", ""),
                        "class_group": r.get("kelas_baru", ""),
                        "weeks": week_text,
                        "KS_change": -ks,
                        "reason": "Load removed from original lecturer during early temporary cover weeks.",
                        "note": f"{primary} is not counted for Week {week_text} because {cover} covers the class temporarily.",
                    })

    # Emergency replacement log
    if emergency_log is not None and not emergency_log.empty:
        elog = emergency_log.copy()
        if "status" in elog.columns:
            elog = elog[elog["status"] == "OK"].copy()

        if not elog.empty:
            unique_original = elog.drop_duplicates(subset=["case_no", "class_id", "replacement_week"])
            for _, r in unique_original.iterrows():
                weeks = _parse_week_text(r.get("replacement_week", ""))
                sub_load(r.get("emergency_lecturer", ""), weeks, float(r.get("subject_KS", 0)))

            for _, r in elog.iterrows():
                weeks = _parse_week_text(r.get("replacement_week", ""))
                add_load(r.get("replacement_lecturer", ""), weeks, float(r.get("KS_added_full_class", 0)))
                event_rows.append({
                    "semester_code": semester_code,
                    "event_category": "Emergency Replacement",
                    "lecturer": r.get("replacement_lecturer", ""),
                    "event_role": "Emergency replacement lecturer",
                    "affected_lecturer": r.get("emergency_lecturer", ""),
                    "subject_code": r.get("subject_code", ""),
                    "class_group": r.get("class_group", ""),
                    "weeks": r.get("replacement_week", ""),
                    "KS_change": float(r.get("KS_added_full_class", 0)),
                    "reason": r.get("emergency_reason", ""),
                    "note": f"{r.get('replacement_lecturer','')} covers {r.get('emergency_lecturer','')} for Week {r.get('replacement_week','')} ({r.get('split_group','')}).",
                })
                event_rows.append({
                    "semester_code": semester_code,
                    "event_category": "Emergency Replacement",
                    "lecturer": r.get("emergency_lecturer", ""),
                    "event_role": "Emergency unavailable lecturer",
                    "affected_lecturer": r.get("replacement_lecturer", ""),
                    "subject_code": r.get("subject_code", ""),
                    "class_group": r.get("class_group", ""),
                    "weeks": r.get("replacement_week", ""),
                    "KS_change": -float(r.get("subject_KS", 0)),
                    "reason": r.get("emergency_reason", ""),
                    "note": f"{r.get('emergency_lecturer','')} unavailable for Week {r.get('replacement_week','')}; covered by {r.get('replacement_lecturer','')}.",
                })

    for c in week_cols:
        weekly[c] = weekly[c].round(2).clip(lower=0)

    # ------------------------------------------------------------
    # FIX LOGIK: Pengiraan Purata Mengikut Minggu Available Sahaja
    # ------------------------------------------------------------
    def hitung_purata_dinamik(row):
        nama_p = row.get("pensyarah")
        beban_mingguan = [float(row.get(f"Week_{i}_KS", 0)) for i in range(1, SEMESTER_WEEKS + 1)]
        
        # Cari profil pensyarah di dalam df_summary
        match_summary = df_summary[df_summary["pensyarah"] == nama_p]
        
        if not match_summary.empty:
            mula = int(match_summary.iloc[0].get("minggu_mula_available", 1))
            akhir = int(match_summary.iloc[0].get("minggu_akhir_available", SEMESTER_WEEKS))
            status_p = str(match_summary.iloc[0].get("status_pensyarah", "")).upper()
            
            # Jika pensyarah bercuti sepanjang semester, purata adalah 0
            if status_p in ["CUTI", "TIDAK_AKTIF"] or mula > akhir:
                return 0.0
            
            # Ambil senarai beban kerja pada minggu yang dia available sahaja
            minggu_aktif_beban = beban_mingguan[mula - 1 : akhir]
            
            if len(minggu_aktif_beban) > 0:
                return round(sum(minggu_aktif_beban) / len(minggu_aktif_beban), 2)
        
        # Fallback sekiranya lajur tiada, bahagi rata dengan total semester weeks (14)
        return round(sum(beban_mingguan) / SEMESTER_WEEKS, 2)

    # Kemas kini lajur dengan data dinamik yang betul
    weekly["average_semester_load"] = weekly.apply(hitung_purata_dinamik, axis=1)
    weekly["peak_weekly_load"] = weekly[week_cols].max(axis=1).round(2)
    weekly["minimum_weekly_load"] = weekly[week_cols].min(axis=1).round(2)
    weekly["weekly_load_range"] = weekly["minimum_weekly_load"].astype(str) + " - " + weekly["peak_weekly_load"].astype(str)

    def overload_weeks(row):
        max_ks = float(row.get("maksimum_KS", 999))
        weeks = []
        for i in range(1, SEMESTER_WEEKS + 1):
            if float(row.get(f"Week_{i}_KS", 0)) > max_ks:
                weeks.append(str(i))
        return ", ".join(weeks)

    weekly["temporary_overload_weeks"] = weekly.apply(overload_weeks, axis=1)
    weekly["average_load_status"] = weekly.apply(
        lambda r: "OVERLOAD_AVERAGE" if float(r["average_semester_load"]) > float(r.get("maksimum_KS", 999))
        else ("UNDERLOAD_AVERAGE" if float(r["average_semester_load"]) < float(r.get("minimum_KS", 0)) else "FAIR_AVERAGE"),
        axis=1
    )
    weekly["fairness_basis"] = "Average of available teaching weeks"

    event_df = pd.DataFrame(event_rows)
    if not event_df.empty:
        notes = event_df.groupby("lecturer")["note"].apply(lambda x: " | ".join(x.astype(str).drop_duplicates())).reset_index()
        weekly = weekly.merge(notes, left_on="pensyarah", right_on="lecturer", how="left").drop(columns=["lecturer"], errors="ignore")
        weekly = weekly.rename(columns={"note": "semester_timeline_note"})
    else:
        weekly["semester_timeline_note"] = "No emergency or temporary replacement recorded."

    weekly["semester_timeline_note"] = weekly["semester_timeline_note"].fillna("No emergency or temporary replacement recorded.")

    return weekly, event_df


apply_page_config()
hero()
ensure_emergency_log(st.session_state)

# Sidebar navigation note
with st.sidebar:
    st.markdown("### MyTimes")
    st.markdown("Fair KS distribution, emergency log, and manual fine tuning.")
    st.markdown("---")
    st.markdown("**Workflow**")
    st.markdown("1. Upload files\n2. Validate data\n3. Manage classes\n4. Run fair allocation\n5. Emergency reallocation\n6. Manual fine tuning\n7. Dashboard & export")

# ============================================================
# 1. Upload Files
# ============================================================
section("1. Upload Files", "Upload Class Schedule and Lecturer files. The system uses KS terminology throughout.")
u1, u2 = st.columns(2)
with u1:
    file_classes = st.file_uploader("Upload Class Schedule", type=["xlsx", "csv"])
with u2:
    file_lect = st.file_uploader("Upload Lecturer File", type=["xlsx", "csv"])

semester_options = ["20241", "20242", "20251", "20252", "20261", "20262", "20271", "20272"]
semester_code = st.selectbox(
    "Semester Code",
    semester_options,
    index=semester_options.index("20261"),
    help="UiTM semester code format: 20241, 20242, 20251, 20252, 20261, 20262 and so on."
)
st.session_state["semester_code"] = semester_code

if file_classes is None or file_lect is None:
    soft_card_html(
        """
        <b>Required Class Schedule Format</b><br>
        kod_kursus, kelas_baru, ks<br><br>
        <b>Required Lecturer File Format</b><br>
        Nama Lecturers, Peranan, Minimum KS, Maksimum KS, Pilihan 1 hingga Pilihan 5<br><br>
        <span class="badge">Emergency Log will be active after Fair KS Allocation is run.</span>
        """
    )
    st.stop()

# ============================================================
# Load Data
# ============================================================
if "loaded_class_file" not in st.session_state:
    st.session_state.loaded_class_file = ""

if "class_df" not in st.session_state or st.session_state.loaded_class_file != file_classes.name:
    st.session_state.class_df = prepare_class_data(file_classes)
    st.session_state.loaded_class_file = file_classes.name
    # New upload resets derived result, but not mandatory old emergency log
    for key in ["df_assign", "df_summary", "df_temp_cover", "df_unassigned", "df_status", "target_ks"]:
        st.session_state.pop(key, None)
    st.session_state["emergency_log"] = pd.DataFrame()

dfl = prepare_lecturer_data(file_lect)

# ============================================================
# 2. Data Validation
# ============================================================
section("2. Data Validation", "Validate KS capacity, active classes, closed classes, and active lecturers before running the optimizer.")
df_all = st.session_state.class_df.copy()
df_all["status_kelas"] = df_all["status_kelas"].map(standardize_status)
df_active = df_all[df_all["status_kelas"].isin(["BUKA", "BARU"])].copy()
df_closed = df_all[df_all["status_kelas"] == "TUTUP"].copy()

v1, v2, v3, v4, v5 = st.columns(5)
with v1:
    metric_card("Active Classes", len(df_active), "BUKA + BARU")
with v2:
    metric_card("Closed Classes", len(df_closed), "Not allocated")
with v3:
    metric_card("Total KS", int(df_active["ks"].sum()), "Active KS")
with v4:
    metric_card("Active Lecturers", int(dfl["active"].sum()), "Available to teach")
with v5:
    avg_ks = round(int(df_active["ks"].sum()) / max(int(dfl["active"].sum()), 1), 2)
    metric_card("Average KS", avg_ks, "Fairness reference")

cap_max = int(dfl.loc[dfl["active"], "max_ks"].sum())
cap_min = int(dfl.loc[dfl["active"], "min_ks"].sum())
if cap_max < int(df_active["ks"].sum()):
    st.error("Maximum active lecturer capacity is insufficient to cover all active KS.")
elif cap_min > int(df_active["ks"].sum()):
    st.warning("The total minimum KS requirement is higher than active class KS. The model may be infeasible.")
else:
    st.success("Capacity check looks reasonable.")

with st.expander("View uploaded data", expanded=False):
    t1, t2, t3 = st.tabs(["Active Classes", "Closed Classes", "Lecturers"])
    with t1:
        st.dataframe(df_active, use_container_width=True, height=340)
    with t2:
        st.dataframe(df_closed, use_container_width=True, height=340)
    with t3:
        st.dataframe(dfl, use_container_width=True, height=340)

# ============================================================
# 3. Class Manager
# ============================================================
section("3. Class Manager", "Edit, add, or close classes before running Fair KS Allocation.")
manager_tabs = st.tabs(["📋 Edit Class Schedule", "➕ Add Class", "🗑️ Close Class"])

with manager_tabs[0]:
    edited = st.data_editor(
        st.session_state.class_df,
        use_container_width=True,
        height=420,
        num_rows="dynamic",
        column_config={
            "status_kelas": st.column_config.SelectboxColumn("status_kelas", options=["BUKA", "BARU", "TUTUP"], required=True),
            "share_allowed": st.column_config.SelectboxColumn("share_allowed", options=["TIDAK", "YA"], required=True),
        },
    )
    if st.button("💾 Save Class Schedule Changes", use_container_width=True):
        edited = edited.copy()
        edited["kod_kursus"] = edited["kod_kursus"].map(clean_text)
        edited["kelas_baru"] = edited["kelas_baru"].astype(str).str.strip()
        edited["status_kelas"] = edited["status_kelas"].map(standardize_status)
        edited["ks"] = pd.to_numeric(edited["ks"], errors="coerce").fillna(0).astype(int)
        edited["kelas_id"] = edited["kod_kursus"] + "-" + edited["kelas_baru"].astype(str)
        edited = edited.drop_duplicates(subset=["kelas_id"], keep="last").copy()
        st.session_state.class_df = edited
        for key in ["df_assign", "df_summary", "df_temp_cover", "df_unassigned", "df_status", "target_ks"]:
            st.session_state.pop(key, None)
        st.session_state["emergency_log"] = pd.DataFrame()
        st.success("Changes saved. Please rerun Fair KS Allocation.")
        st.rerun()

with manager_tabs[1]:
    c1, c2, c3 = st.columns(3)
    with c1:
        new_subject = st.text_input("Course Code", placeholder="Contoh: MAT112")
        new_class = st.text_input("Group / Class", placeholder="Contoh: A1")
    with c2:
        new_ks = st.number_input("KS", 1, 10, 3, 1)
        new_size = st.number_input("Class Size", 0, 500, 0, 1)
    with c3:
        new_start = st.number_input("Class Start Week", 1, SEMESTER_WEEKS, 1, 1)
        new_end = st.number_input("Class End Week", 1, SEMESTER_WEEKS, SEMESTER_WEEKS, 1)
    new_note = st.text_input("Notes", placeholder="Example: additional class / new class")
    if st.button("➕ Add Class Baru", use_container_width=True):
        if clean_text(new_subject) == "" or new_class.strip() == "":
            st.error("Course Code dan group/kelas wajib diisi.")
        else:
            new_row = {
                "kelas_id": clean_text(new_subject) + "-" + new_class.strip(),
                "kod_kursus": clean_text(new_subject),
                "kelas_baru": new_class.strip(),
                "status_kelas": "BARU",
                "ks": int(new_ks),
                "saiz_kelas": int(new_size),
                "campuran_group": "",
                "perincian": new_note,
                "pensyarah_asal": "",
                "lock_agihan": "TIDAK",
                "share_allowed": "TIDAK",
                "minggu_mula_kelas": int(new_start),
                "minggu_akhir_kelas": int(new_end),
            }
            updated = pd.concat([st.session_state.class_df, pd.DataFrame([new_row])], ignore_index=True)
            updated["kelas_id"] = updated["kod_kursus"].map(clean_text) + "-" + updated["kelas_baru"].astype(str).str.strip()
            updated = updated.drop_duplicates(subset=["kelas_id"], keep="last").copy()
            st.session_state.class_df = updated
            for key in ["df_assign", "df_summary", "df_temp_cover", "df_unassigned", "df_status", "target_ks"]:
                st.session_state.pop(key, None)
            st.session_state["emergency_log"] = pd.DataFrame()
            st.success(f"Class {new_row['kelas_id']} successfully added. Please rerun allocation.")
            st.rerun()

with manager_tabs[2]:
    close_mode = st.radio("Closure Option", ["Close one class", "Close all classes for one subject"], horizontal=True)
    if close_mode == "Close one class":
        class_ids = sorted(st.session_state.class_df["kelas_id"].dropna().unique().tolist())
        selected_class = st.selectbox("Select Class", class_ids)
        if st.button("🗑️ Close Class Ini", use_container_width=True):
            st.session_state.class_df.loc[st.session_state.class_df["kelas_id"] == selected_class, "status_kelas"] = "TUTUP"
            for key in ["df_assign", "df_summary", "df_temp_cover", "df_unassigned", "df_status", "target_ks"]:
                st.session_state.pop(key, None)
            st.session_state["emergency_log"] = pd.DataFrame()
            st.success(f"{selected_class} have been closed. Please rerun allocation.")
            st.rerun()
    else:
        subjects = sorted(st.session_state.class_df["kod_kursus"].dropna().unique().tolist())
        selected_subject = st.selectbox("Select Subject", subjects)
        if st.button("🗑️ Close All Classes for This Subject", use_container_width=True):
            st.session_state.class_df.loc[st.session_state.class_df["kod_kursus"] == selected_subject, "status_kelas"] = "TUTUP"
            for key in ["df_assign", "df_summary", "df_temp_cover", "df_unassigned", "df_status", "target_ks"]:
                st.session_state.pop(key, None)
            st.session_state["emergency_log"] = pd.DataFrame()
            st.success(f"Semua kelas {selected_subject} ditutup. Sila run semula allocation.")
            st.rerun()

# Refresh active data after class manager
st.session_state.class_df["status_kelas"] = st.session_state.class_df["status_kelas"].map(standardize_status)
df_all = st.session_state.class_df.copy()
df_active = df_all[df_all["status_kelas"].isin(["BUKA", "BARU"])].copy()
df_closed = df_all[df_all["status_kelas"] == "TUTUP"].copy()

# ============================================================
# 4. Fair Allocation
# ============================================================
section("4. Run MyTimes Fair Allocation", "Run optimization and generate fair lecturer-subject allocation.")
if st.button("🚀 Run Fair KS Allocation", use_container_width=True):
    start_time = time.time()
    pref = build_preference_score(dfl)
    solver_status, assigned_df, target_ks = solve_allocation(df_active, dfl, pref)

    if solver_status == "Optimal":
        st.success("Optimization Status: Optimal")
    else:
        st.warning(f"Optimization Status: {solver_status}")

    df_assign, df_summary, df_temp_cover, df_unassigned, df_status = build_outputs(
        df_active, df_closed, dfl, pref, assigned_df, target_ks
    )

    st.session_state["df_assign"] = df_assign
    st.session_state["df_summary"] = df_summary
    st.session_state["df_temp_cover"] = df_temp_cover
    st.session_state["df_unassigned"] = df_unassigned
    st.session_state["df_status"] = df_status
    st.session_state["target_ks"] = target_ks
    st.session_state["emergency_log"] = pd.DataFrame()
    runtime = round(time.time()-start_time,2)
    st.session_state["runtime_seconds"] = runtime
    st.success(f"Allocation saved. System target average: {target_ks} KS in {runtime} sec.")

if "df_assign" not in st.session_state:
    st.info("Run MyTimes Fair Allocation to activate dashboard.")
    st.stop()

# Pull saved result
df_assign = st.session_state["df_assign"]
df_summary = st.session_state["df_summary"]
df_temp_cover = st.session_state["df_temp_cover"]
df_unassigned = st.session_state["df_unassigned"]
df_status = st.session_state["df_status"]
target_ks = st.session_state.get("target_ks")


# Subject Analytics
with st.expander("Subject Analytics", expanded=False):
    subj = df_active.groupby("kod_kursus").agg(
        total_classes=("kelas_id","count"),
        total_students=("saiz_kelas","sum"),
        total_ks=("ks","sum")
    ).reset_index()
    assigned_subj = df_assign.groupby("kod_kursus").agg(
        assigned_classes=("kelas_id","count"),
        assigned_lecturers=("pensyarah_utama","nunique"),
        avg_preference_score=("preference_score","mean")
    ).reset_index() if not df_assign.empty else pd.DataFrame()
    if not assigned_subj.empty:
        subj = subj.merge(assigned_subj, on="kod_kursus", how="left")
    st.dataframe(subj,use_container_width=True)

# ============================================================
# 5. Emergency Reallocation
# ============================================================
section("5. Emergency Reallocation", "Enter the lecturer, affected weeks, and mandatory manual emergency reason. Multiple emergency cases can be appended into the Emergency Log.")

em1, em2, em3 = st.columns([2, 1, 1])
with em1:
    emergency_lecturer = st.selectbox("Select Emergency Lecturer", sorted(df_summary["pensyarah"].tolist()))
with em2:
    emergency_start_week = st.number_input("Start Week", 1, SEMESTER_WEEKS, 5, 1)
with em3:
    emergency_end_week = st.number_input("End Week", 1, SEMESTER_WEEKS, 10, 1)

em4, em5 = st.columns([1, 2])
with em4:
    emergency_type = st.selectbox(
        "Emergency Type",
        [
            "Temporary class replacement",
            "Lecturer unavailable",
            "Medical / leave case",
            "Late appointment / reporting duty",
            "Operational adjustment",
            "Shared teaching / split coverage",
        ]
    )
    allow_split_replacement = st.checkbox(
        "Allow split coverage by 2 lecturers",
        value=True,
        help="If no one can take the full KS, MyTimes can split one emergency class between two lecturers, e.g. 4 KS = 2 KS + 2 KS."
    )
with em5:
    emergency_reason = st.text_area(
        "Emergency Reason (manual input required)",
        placeholder="Example: Medical leave / maternity leave / timetable clash / shared teaching / lecturer reports late / additional class opened",
        height=90,
        help="This reason is typed manually by AJK and will be saved in the Emergency Log and exported file."
    )

b1, b2 = st.columns([2, 1])
with b1:
    run_emergency = st.button("🚨 Run Emergency Reallocation", use_container_width=True)
with b2:
    clear_emergency = st.button("🧹 Clear Emergency Log", use_container_width=True)

if clear_emergency:
    st.session_state["emergency_log"] = pd.DataFrame()
    st.success("Emergency Log cleared.")
    st.rerun()

if run_emergency:
    if emergency_end_week < emergency_start_week:
        st.error("End Week cannot be earlier than Start Week.")
    elif not str(emergency_reason).strip():
        st.error("Please fill in Emergency Reason before running emergency reallocation.")
    else:
        emergency_reason = str(emergency_reason).strip()
        new_emergency = compute_emergency_reallocation(
            df_assign=df_assign,
            df_summary=df_summary,
            emergency_log=st.session_state.get("emergency_log", pd.DataFrame()),
            emergency_lecturer=emergency_lecturer,
            start_week=emergency_start_week,
            end_week=emergency_end_week,
            emergency_reason=emergency_reason,
            emergency_type=emergency_type,
            allow_split_replacement=allow_split_replacement,
        )
        if new_emergency.empty:
            st.info("No classes overlap with the emergency period, or the lecturer has no assigned classes.")
        else:
            st.session_state["emergency_log"] = pd.concat(
                [st.session_state.get("emergency_log", pd.DataFrame()), new_emergency],
                ignore_index=True,
            )
            st.success("Emergency case added to Emergency Log.")
            st.dataframe(new_emergency, use_container_width=True, height=260)

emergency_log = st.session_state.get("emergency_log", pd.DataFrame())
if emergency_log is not None and not emergency_log.empty:
    st.markdown("### Emergency Log")
    st.caption("Emergency Reason is editable here, so AJK can correct or add the manual reason directly in the system before export.")
    disabled_cols = [c for c in emergency_log.columns if c != "emergency_reason"]
    edited_emergency_log = st.data_editor(
        emergency_log,
        use_container_width=True,
        height=360,
        disabled=disabled_cols,
        column_config={
            "emergency_reason": st.column_config.TextColumn(
                "Emergency Reason (manual)",
                help="Manual reason typed by AJK. This field is editable in the system.",
                required=True,
            )
        },
        key="emergency_log_editor",
    )
    st.session_state["emergency_log"] = edited_emergency_log
else:
    st.info("No emergency case recorded yet.")

weekly_analysis, semester_event_log = build_weekly_lecturer_analysis(
    df_assign=df_assign,
    df_summary=df_summary,
    emergency_log=st.session_state.get("emergency_log", pd.DataFrame()),
    semester_code=st.session_state.get("semester_code", ""),
)

# Enhanced lecturer summary that explains the whole semester, including emergency/temporary coverage.
df_summary_enhanced = df_summary.copy()
if not weekly_analysis.empty:
    cols_to_add = ["pensyarah", "weekly_load_range", "minimum_weekly_load", "peak_weekly_load", "average_semester_load", "average_load_status", "temporary_overload_weeks", "fairness_basis", "semester_timeline_note"]
    df_summary_enhanced = df_summary_enhanced.merge(weekly_analysis[cols_to_add], on="pensyarah", how="left")
else:
    df_summary_enhanced["weekly_load_range"] = ""
    df_summary_enhanced["semester_timeline_note"] = ""

# ============================================================
# 6. Manual Fine Tuning
# ============================================================
section("6. Manual Fine Tuning", "Optional human adjustment after the optimizer. Reduce KS from one lecturer and assign/share it to another lecturer without rerunning the main allocation.")

if "manual_tuning_log" not in st.session_state:
    st.session_state["manual_tuning_log"] = pd.DataFrame(columns=[
        "case_no", "source_lecturer", "receiver_lecturer", "kelas_id", "kod_kursus",
        "KS_adjusted", "source_KS_before", "receiver_KS_before",
        "source_KS_after", "receiver_KS_after", "note"
    ])

manual_log = st.session_state.get("manual_tuning_log", pd.DataFrame())

base_summary_for_manual = df_summary.copy()
if manual_log is not None and not manual_log.empty:
    outgoing = manual_log.groupby("source_lecturer")["KS_adjusted"].sum().reset_index().rename(columns={"source_lecturer": "pensyarah", "KS_adjusted": "manual_KS_out"})
    incoming = manual_log.groupby("receiver_lecturer")["KS_adjusted"].sum().reset_index().rename(columns={"receiver_lecturer": "pensyarah", "KS_adjusted": "manual_KS_in"})
    base_summary_for_manual = base_summary_for_manual.merge(outgoing, on="pensyarah", how="left").merge(incoming, on="pensyarah", how="left")
else:
    base_summary_for_manual["manual_KS_out"] = 0.0
    base_summary_for_manual["manual_KS_in"] = 0.0

base_summary_for_manual["manual_KS_out"] = base_summary_for_manual["manual_KS_out"].fillna(0.0)
base_summary_for_manual["manual_KS_in"] = base_summary_for_manual["manual_KS_in"].fillna(0.0)
base_summary_for_manual["jumlah_KS_adjusted"] = (
    base_summary_for_manual["jumlah_KS"]
    - base_summary_for_manual["manual_KS_out"]
    + base_summary_for_manual["manual_KS_in"]
).round(2)

mt1, mt2 = st.columns([2, 2])
with mt1:
    source_lecturer = st.selectbox(
        "Lecturer to reduce KS",
        sorted(df_summary["pensyarah"].tolist()),
        key="manual_source_lecturer"
    )

source_classes = df_assign[df_assign["pensyarah_utama"] == source_lecturer].copy()
if source_classes.empty:
    st.info("Selected lecturer has no class in the current allocation.")
else:
    with mt2:
        selected_class = st.selectbox(
            "Class / subject to adjust",
            source_classes["kelas_id"].tolist(),
            key="manual_selected_class"
        )

    selected_row = source_classes[source_classes["kelas_id"] == selected_class].iloc[0]
    max_adjust = float(selected_row["KS"])

    source_before = float(base_summary_for_manual.loc[base_summary_for_manual["pensyarah"] == source_lecturer, "jumlah_KS_adjusted"].iloc[0])

    candidates = base_summary_for_manual[
        (base_summary_for_manual["pensyarah"] != source_lecturer)
        & (base_summary_for_manual["aktif"] == True)
    ].copy()
    candidates["same_subject"] = candidates["senarai_subjek"].astype(str).apply(
        lambda x: 1 if selected_row["kod_kursus"] in x else 0
    )
    candidates = candidates.sort_values(["same_subject", "jumlah_KS_adjusted"], ascending=[False, True])

    c1, c2, c3 = st.columns([1, 2, 2])
    with c1:
        ks_adjusted = st.number_input(
            "KS to transfer/share",
            min_value=0.5,
            max_value=max_adjust,
            value=min(2.0, max_adjust),
            step=0.5,
            key="manual_ks_adjusted"
        )
    with c2:
        receiver_lecturer = st.selectbox(
            "Receiver lecturer",
            candidates["pensyarah"].tolist(),
            key="manual_receiver_lecturer"
        )
    with c3:
        manual_note = st.text_input(
            "Adjustment note",
            value="Manual fine tuning after workload review",
            key="manual_note"
        )

    receiver_before = float(base_summary_for_manual.loc[base_summary_for_manual["pensyarah"] == receiver_lecturer, "jumlah_KS_adjusted"].iloc[0])
    source_after = round(source_before - float(ks_adjusted), 2)
    receiver_after = round(receiver_before + float(ks_adjusted), 2)

    a1, a2, a3, a4 = st.columns(4)
    with a1:
        metric_card("Source Before", source_before, source_lecturer)
    with a2:
        metric_card("Source After", source_after, f"-{ks_adjusted} KS")
    with a3:
        metric_card("Receiver Before", receiver_before, receiver_lecturer)
    with a4:
        metric_card("Receiver After", receiver_after, f"+{ks_adjusted} KS")

    b1, b2 = st.columns([2, 1])
    with b1:
        if st.button("✅ Apply Manual Fine Tuning", use_container_width=True):
            case_no = 1 if manual_log is None or manual_log.empty else int(manual_log["case_no"].max()) + 1
            new_row = pd.DataFrame([{
                "case_no": case_no,
                "source_lecturer": source_lecturer,
                "receiver_lecturer": receiver_lecturer,
                "kelas_id": selected_row["kelas_id"],
                "kod_kursus": selected_row["kod_kursus"],
                "KS_adjusted": float(ks_adjusted),
                "source_KS_before": source_before,
                "receiver_KS_before": receiver_before,
                "source_KS_after": source_after,
                "receiver_KS_after": receiver_after,
                "note": manual_note,
            }])
            st.session_state["manual_tuning_log"] = pd.concat([manual_log, new_row], ignore_index=True)
            st.success("Manual adjustment added to Manual Fine Tuning Log.")
            st.rerun()
    with b2:
        if st.button("🧹 Clear Manual Log", use_container_width=True):
            st.session_state["manual_tuning_log"] = pd.DataFrame()
            st.success("Manual Fine Tuning Log cleared.")
            st.rerun()

manual_log = st.session_state.get("manual_tuning_log", pd.DataFrame())
if manual_log is not None and not manual_log.empty:
    st.markdown("### Manual Fine Tuning Log")
    st.dataframe(manual_log, use_container_width=True, height=300)
else:
    st.info("No manual fine tuning has been applied yet.")

# ============================================================
# 7. Executive Dashboard + Export
# ============================================================
section("7. Executive Dashboard", "Executive dashboard for main allocation, workload, audit, manual adjustment, emergency, and export.")
s = df_status.iloc[0]

runtime=st.session_state.get("runtime_seconds",0)
# Fairness Score measures workload balance only. It is separated from preference satisfaction.
# Now based on average weekly workload across 14 weeks, not static final KS.
if weekly_analysis is not None and not weekly_analysis.empty and target_ks:
    active_sum = weekly_analysis.copy()
    fairness = round(max(0, 100 - (active_sum["average_semester_load"].sub(target_ks).abs().mean() / max(target_ks, 1) * 100)), 1) if not active_sum.empty else 0
else:
    fairness = 0
# Preference Score is KS-weighted so one large non-preferred assignment is not hidden by many small preferred classes.
if not df_assign.empty and "preference_score" in df_assign.columns:
    pref_score = round((df_assign["preference_score"] * df_assign["KS"]).sum() / max(df_assign["KS"].sum(), 1), 1)
else:
    pref_score = 0
d1, d2, d3, d4, d5, d6 = st.columns(6)
with d1:
    metric_card("Coverage", f"{s['kelas_diagih']}/{s['jumlah_kelas_aktif']}", "Allocated classes")
with d2:
    metric_card("Fair Load", int(s["pensyarah_adil"]), "Within min/max")
with d3:
    metric_card("Underload", int(s["pensyarah_underload"]), "Below minimum")
with d4:
    metric_card("Overload", int(s["pensyarah_overload"]), "Above maximum")
with d5:
    metric_card("Target KS", target_ks, "System target")
with d6:
    metric_card("Emergency", len(emergency_log) if emergency_log is not None else 0, "Case log")

tabs = st.tabs(["📌 Allocation", "👤 Lecturer Analysis", "⏱️ Temporary & Emergency", "📊 Charts", "🔍 Audit", "📥 Export"])

with tabs[0]:
    st.markdown("### Main Class Allocation")
    st.dataframe(df_assign, use_container_width=True, height=520)

with tabs[1]:
    st.markdown("### Lecturer Analysis")
    st.caption("This view shows the overall semester story: base KS, emergency coverage, temporary cover, and week-by-week workload changes.")
    st.dataframe(df_summary_enhanced, use_container_width=True, height=420)
    st.markdown("### Weekly Workload Timeline")
    st.dataframe(weekly_analysis, use_container_width=True, height=420)
    if semester_event_log is not None and not semester_event_log.empty:
        st.markdown("### Semester Event Notes")
        st.dataframe(semester_event_log, use_container_width=True, height=260)

with tabs[2]:
    st.markdown("### Temporary Cover and Emergency Cases")
    st.caption("This tab separates normal temporary cover from emergency replacement, so the analysis shows the full semester story.")

    st.markdown("#### Temporary Cover Cases")
    if df_temp_cover.empty:
        st.success("No temporary cover cases.")
    else:
        st.warning("Late-entry lecturers detected. Early weeks require temporary cover.")
        st.dataframe(df_temp_cover, use_container_width=True, height=300)

    st.markdown("#### Emergency Replacement Cases")
    if emergency_log is None or emergency_log.empty:
        st.success("No emergency replacement cases.")
    else:
        st.warning("Emergency cases recorded. Check Week-by-week Analysis and Semester Event Notes for average and peak workload.")
        st.dataframe(emergency_log, use_container_width=True, height=360)

    st.markdown("#### Combined Semester Event Notes")
    if semester_event_log is None or semester_event_log.empty:
        st.info("No temporary cover or emergency event recorded.")
    else:
        st.dataframe(semester_event_log, use_container_width=True, height=360)

with tabs[3]:
    st.markdown("### Workload Distribution")
    chart_df = df_summary.copy()
    manual_log_for_chart = st.session_state.get("manual_tuning_log", pd.DataFrame())

    if manual_log_for_chart is not None and not manual_log_for_chart.empty:
        out_adj = manual_log_for_chart.groupby("source_lecturer")["KS_adjusted"].sum().reset_index().rename(
            columns={"source_lecturer": "pensyarah", "KS_adjusted": "manual_out"}
        )
        in_adj = manual_log_for_chart.groupby("receiver_lecturer")["KS_adjusted"].sum().reset_index().rename(
            columns={"receiver_lecturer": "pensyarah", "KS_adjusted": "manual_in"}
        )
        chart_df = chart_df.merge(out_adj, on="pensyarah", how="left").merge(in_adj, on="pensyarah", how="left")
    else:
        chart_df["manual_out"] = 0.0
        chart_df["manual_in"] = 0.0

    chart_df["manual_out"] = chart_df["manual_out"].fillna(0.0)
    chart_df["manual_in"] = chart_df["manual_in"].fillna(0.0)
    chart_df["jumlah_KS_adjusted"] = (chart_df["jumlah_KS"] - chart_df["manual_out"] + chart_df["manual_in"]).round(2)
    
    if weekly_analysis is not None and not weekly_analysis.empty:
        avg_cols = ["pensyarah", "average_semester_load", "peak_weekly_load", "average_load_status"]
        chart_df = chart_df.merge(weekly_analysis[avg_cols], on="pensyarah", how="left")
        chart_df["jumlah_KS_adjusted"] = chart_df["average_semester_load"].fillna(chart_df["jumlah_KS_adjusted"])
        chart_df["status_load"] = chart_df["average_load_status"].fillna(chart_df["status_load"])
    
    chart_df["chart_label"] = chart_df["jumlah_KS_adjusted"].astype(str) + " avg KS | " + chart_df["bil_subjek"].astype(str) + " subjects"

    # >>> PASTIKAN BARIS IF DI BAWAH INI SEBARIS DENGAN IF-ELSE DI ATAS <<<
    if px is not None and not chart_df.empty:
        status_color_map = {
            "FAIR_AVERAGE": "#10b981",
            "UNDERLOAD_AVERAGE": "#f59e0b",
            "OVERLOAD_AVERAGE": "#ef4444",
            "FAIR": "#10b981",
            "UNDERLOAD": "#f59e0b",
            "OVERLOAD": "#ef4444"
        }

        fig = px.bar(
            chart_df.sort_values("jumlah_KS_adjusted"),
            x="jumlah_KS_adjusted",
            y="pensyarah",
            orientation="h",
            text="chart_label",
            color="status_load",
            title="Workload Distribution: KS and Number of Subjects",
            hover_data=["jumlah_KS", "bil_subjek", "minimum_KS", "maksimum_KS", "senarai_subjek"],
            color_discrete_map=status_color_map
        )
        
        fig.update_traces(
            textposition="inside",
            textfont=dict(family="Inter, sans-serif", size=11, color="white"),
            marker=dict(line=dict(width=0))
        )
        
        fig.update_layout(
            height=760,
            template="plotly_white",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis_title="Adjusted KS",
            yaxis_title="Lecturer",
            font=dict(family="Inter, sans-serif", size=12, color="#1e293b"),
            title=dict(
                font=dict(family="Inter, sans-serif", size=16, color="#0f172a", weight="bold"),
                pad=dict(b=20)
            ),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                title=dict(text="")
            ),
            xaxis=dict(
                showgrid=True,
                gridcolor="#f1f5f9",
                zeroline=False
            ),
            yaxis=dict(
                autorange="reversed"
            )
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        cols_chart_df = ["pensyarah", "jumlah_KS_adjusted", "bil_subjek", "status_load"]
        df_chart_clean = chart_df[cols_chart_df] if all(c in chart_df.columns for c in cols_chart_df) else chart_df
        st.write(df_chart_clean.to_html(index=False, classes='clean-table'), unsafe_allow_html=True)
with tabs[4]:
    st.markdown("### Audit Check")
    if df_unassigned.empty:
        st.success("All active classes have been allocated.")
    else:
        st.error("Some active classes are unallocated.")
        st.dataframe(df_unassigned, use_container_width=True)

    under = df_summary[df_summary["status_load"] == "UNDERLOAD"]
    over = df_summary[df_summary["status_load"] == "OVERLOAD"]
    if not under.empty:
        st.warning("Underload lecturers.")
        st.dataframe(under, use_container_width=True)
    if not over.empty:
        st.error("Overload lecturers.")
        st.dataframe(over, use_container_width=True)

    st.markdown("### Closed Classes")
    st.dataframe(df_closed, use_container_width=True, height=300)

with tabs[5]:
    metadata = pd.DataFrame([{
        "semester_code": st.session_state.get("semester_code", ""),
        "semester_format_note": "UiTM code, e.g. 20241, 20242, 20251, 20252, 20261, 20262",
        "processing_time_sec": st.session_state.get("runtime_seconds", 0),
    }])
    for _df in [df_status, df_assign, df_summary_enhanced, df_temp_cover, emergency_log, weekly_analysis, semester_event_log, df_unassigned, df_closed, df_all]:
        if _df is not None and isinstance(_df, pd.DataFrame) and "semester_code" not in _df.columns:
            _df.insert(0, "semester_code", st.session_state.get("semester_code", ""))

    # ------------------------------------------------------------
    # BUTTON 1: DOWNLOAD EXCEL (Sedia Ada)
    # ------------------------------------------------------------
    output = to_excel_bytes({
        "Metadata": metadata,
        "Status": df_status,
        "Main_Allocation": df_assign,
        "Lecturer_Analysis": df_summary_enhanced,
        "Weekly_Load_Analysis": weekly_analysis,
        "Semester_Event_Log": semester_event_log,
        "Temporary_Cover": df_temp_cover,
        "Emergency_Log": emergency_log,
        "Manual_Fine_Tuning_Log": st.session_state.get("manual_tuning_log", pd.DataFrame()),
        "Unallocated_Classes": df_unassigned,
        "Closed_Classes": df_closed,
        "Updated_Main_File": df_all,
    })
    st.download_button(
        "📥 Download Full Result Excel",
        data=output,
        file_name=f"MyTimes_result_{st.session_state.get('semester_code','')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.markdown("---")

    # ------------------------------------------------------------
    # BUTTON 2: DOWNLOAD PREMIUM EXECUTIVE DASHBOARD HTML (REKAAN BARU)
    # ------------------------------------------------------------
    st.markdown("### 🌐 Laporan Eksekutif Premium (Premium HTML Dashboard)")
    st.caption("Muat turun laporan bertaraf eksekutif dengan reka bentuk grid, kotak KPI moden, dan layout kompak bersaiz skrin/A4.")

    # Ambil data statistik dari status row
    s_row = df_status.iloc[0] if df_status is not None else {}
    
    # Ekstrak nilai untuk Kotak KPI HTML
    kpi_kelas_aktif = s_row.get("jumlah_kelas_aktif", 0)
    kpi_kelas_diagih = s_row.get("kelas_diagih", 0)
    kpi_ks_aktif = s_row.get("jumlah_KS_aktif", 0)
    kpi_ks_diagih = s_row.get("KS_diagih", 0)
    kpi_lect_aktif = s_row.get("pensyarah_aktif", 0)
    kpi_lect_adil = s_row.get("pensyarah_adil", 0)
    kpi_lect_over = s_row.get("pensyarah_overload", 0)
    kpi_target_ks = s_row.get("target_purata_KS", 0)
    
    # Ambil data log manual jika wujud
    df_manual_log = st.session_state.get("manual_tuning_log", pd.DataFrame())

    # --- Penapisan lajur terhad supaya jadual kemas (Clean View) ---
    df_assign_html = df_assign[["kelas_id", "kod_kursus", "kelas_baru", "KS", "saiz_kelas", "pensyarah_utama", "preference_match"]].to_html(index=False, classes='clean-table') if df_assign is not None else ""
    df_summary_html = df_summary_enhanced[["pensyarah", "peranan", "minimum_KS", "maksimum_KS", "jumlah_KS", "bil_subjek", "weekly_load_range", "average_semester_load"]].to_html(index=False, classes='clean-table') if df_summary_enhanced is not None else ""
    
    week_cols = [f"Week_{i}_KS" for i in range(1, SEMESTER_WEEKS + 1)]
    df_weekly_html = weekly_analysis[["pensyarah", "status_load"] + week_cols + ["average_semester_load"]].to_html(index=False, classes='clean-table') if weekly_analysis is not None else ""
    df_event_html = semester_event_log[["event_category", "lecturer", "event_role", "subject_code", "class_group", "weeks", "note"]].to_html(index=False, classes='clean-table') if semester_event_log is not None else ""

    # --- STRUKTUR HTML & CSS PREMIUM (DASHBOARD PORTAL) ---
    premium_html_report = f"""
    <!DOCTYPE html>
    <html lang="ms">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MyTimes Executive Dashboard - {st.session_state.get('semester_code','')}</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
            
            * {{ box-sizing: border-box; font-family: 'Inter', sans-serif; }}
            body {{ background-color: #f8fafc; color: #0f172a; margin: 0; padding: 20px; }}
            
            /* Page Layout Optimization for Screen & A4 Print */
            .dashboard-card {{ max-width: 1300px; margin: 0 auto; background: #ffffff; padding: 30px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.03); border: 1px solid #e2e8f0; }}
            
            /* Top Branding Header */
            .main-header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #f1f5f9; padding-bottom: 20px; margin-bottom: 25px; }}
            .brand h1 {{ margin: 0; font-size: 1.8em; font-weight: 700; color: #1e3a8a; letter-spacing: -0.5px; }}
            .brand p {{ margin: 5px 0 0 0; color: #64748b; font-size: 0.95em; }}
            .badge-semester {{ background-color: #dbeafe; color: #1e40af; font-weight: 600; padding: 6px 14px; border-radius: 30px; font-size: 0.85em; }}
            
            /* 4x2 Grid Kotak KPI */
            .kpi-container {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 30px; }}
            .kpi-card {{ background: #ffffff; padding: 18px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 2px 4px rgba(0,0,0,0.01); border-top: 4px solid #cbd5e1; transition: transform 0.2s; }}
            .kpi-card:hover {{ transform: translateY(-2px); }}
            .kpi-card .label {{ font-size: 0.75em; text-transform: uppercase; font-weight: 600; color: #64748b; letter-spacing: 0.5px; }}
            .kpi-card .value {{ font-size: 1.6em; font-weight: 700; margin: 8px 0 2px 0; color: #1e293b; }}
            .kpi-card .subtext {{ font-size: 0.75em; color: #94a3b8; }}
            
            /* KPI Border Colors Theme */
            .blue-theme {{ border-top-color: #3b82f6; background-color: #f0f7ff; }}
            .green-theme {{ border-top-color: #10b981; background-color: #f0fdf4; }}
            .purple-theme {{ border-top-color: #8b5cf6; background-color: #f5f3ff; }}
            .orange-theme {{ border-top-color: #f59e0b; background-color: #fffbeb; }}
            
            /* Compact Data Section with Internal Scroll (Taknak panjang sangat) */
            h2 {{ font-size: 1.15em; color: #0f172a; margin-top: 25px; margin-bottom: 12px; font-weight: 600; display: flex; align-items: center; gap: 8px; }}
            h2::before {{ content: ''; display: inline-block; width: 4px; height: 16px; background: #3b82f6; border-radius: 2px; }}
            
            .table-wrapper {{ max-height: 280px; overflow-y: auto; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 20px; box-shadow: inset 0 2px 4px rgba(0,0,0,0.02); }}
            
            /* Premium Clean Table CSS */
            table.clean-table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 0.82em; }}
            table.clean-table th {{ background-color: #f8fafc; color: #475569; font-weight: 600; padding: 10px 14px; border-bottom: 2px solid #e2e8f0; position: sticky; top: 0; z-index: 10; }}
            table.clean-table td {{ padding: 10px 14px; border-bottom: 1px solid #f1f5f9; color: #334155; }}
            table.clean-table tr:nth-of-type(even) td {{ background-color: #fafbfc; }}
            table.clean-table tr:hover td {{ background-color: #f1f5f9; }}
            
            .empty-msg {{ color: #94a3b8; font-style: italic; font-size: 0.85em; padding: 15px; background: #f8fafc; border-radius: 6px; border: 1px dashed #e2e8f0; text-align: center; }}
            .footer {{ text-align: center; margin-top: 35px; padding-top: 15px; border-top: 1px solid #f1f5f9; font-size: 0.8em; color: #94a3b8; font-weight: 500; }}
            
            /* Print A4 Styling Optimization */
            @media print {{
                body {{ background-color: #ffffff; padding: 0; }}
                .dashboard-card {{ box-shadow: none; border: none; padding: 10px; }}
                .table-wrapper {{ max-height: none; overflow: visible; }}
                table.clean-table th {{ position: static; }}
                .kpi-card {{ background: #ffffff !important; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="dashboard-card">
                
                <div class="main-header">
                    <div class="brand">
                        <h1>MyTimes Executive Analytics Portal</h1>
                        <p>Laporan Pengagihan Jam Kredit & Analisis Beban Kerja Fakulti</p>
                    </div>
                    <div>
                        <span class="badge-semester">Kod Semester: {st.session_state.get('semester_code','')}</span>
                    </div>
                </div>

                <div class="kpi-container">
                    <div class="kpi-card blue-theme">
                        <div class="label">Kelas Aktif</div>
                        <div class="value">{kpi_kelas_aktif}</div>
                        <div class="subtext">Jumlah Group Ditawarkan</div>
                    </div>
                    <div class="kpi-card blue-theme">
                        <div class="label">Kelas Diagih</div>
                        <div class="value">{kpi_kelas_diagih} / {kpi_kelas_aktif}</div>
                        <div class="subtext">Status Pengagihan Model</div>
                    </div>
                    <div class="kpi-card green-theme">
                        <div class="label">Total KS Aktif</div>
                        <div class="value">{kpi_ks_aktif} KS</div>
                        <div class="subtext">Beban Kerja Keseluruhan</div>
                    </div>
                    <div class="kpi-card green-theme">
                        <div class="label">KS Berjaya Diagih</div>
                        <div class="value">{kpi_ks_diagih} KS</div>
                        <div class="subtext">Kadar Liputan: 100%</div>
                    </div>
                    <div class="kpi-card purple-theme">
                        <div class="label">Pensyarah Aktif</div>
                        <div class="value">{kpi_lect_aktif} Staf</div>
                        <div class="subtext">Tersedia Mengajar</div>
                    </div>
                    <div class="kpi-card purple-theme">
                        <div class="label">Beban Adil (Fair)</div>
                        <div class="value">{kpi_lect_adil} Staf</div>
                        <div class="subtext">Memenuhi Min/Max Cap</div>
                    </div>
                    <div class="kpi-card orange-theme">
                        <div class="label">System Target Load</div>
                        <div class="value">{kpi_target_ks} KS</div>
                        <div class="subtext">Purata Optimum Dicapai</div>
                    </div>
                    <div class="kpi-card orange-theme">
                        <div class="label">Staf Overload</div>
                        <div class="value" style="color: { '#10b981' if kpi_lect_over == 0 else '#ef4444' };">{kpi_lect_over}</div>
                        <div class="subtext">Melebihi Had Maksimum</div>
                    </div>
                </div>

                <h2>1. Keputusan Agihan Kelas Utama (Main Class Allocation)</h2>
                <div class="table-wrapper">
                    {df_assign_html}
                </div>

                <h2>2. Rumusan Status Beban Kerja Pensyarah</h2>
                <div class="table-wrapper">
                    {df_summary_html}
                </div>

                <h2>3. Garis Masa Agihan Jam Kredit Mingguan (Week 1 - 14)</h2>
                <div class="table-wrapper">
                    {df_weekly_html}
                </div>

                <h2>4. Log Peristiwa Semester (Temporary Cover & Emergency Log)</h2>
                <div class="table-wrapper">
                    {df_event_html if df_event_html != "" else "<p class='empty-msg'>Tiada sebarang catatan kes penukaran pensyarah/cuti minggu awal.</p>"}
                </div>

                <h2>5. Pelarasan Manual AJK & Unallocated Class Audit</h2>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                    <div>
                        <h3 style="font-size:0.85em; color:#475569; text-transform:uppercase; margin-bottom:8px;">Pelarasan Manual (Fine Tuning)</h3>
                        <div class="table-wrapper" style="max-height:180px;">
                            {df_manual_log[["case_no", "kelas_id", "KS_adjusted", "note"]].to_html(index=False, classes='clean-table') if not df_manual_log.empty else "<p class='empty-msg'>Tiada pelarasan manual dilakukan.</p>"}
                        </div>
                    </div>
                    <div>
                        <h3 style="font-size:0.85em; color:#475569; text-transform:uppercase; margin-bottom:8px;">Unallocated Active Classes</h3>
                        <div class="table-wrapper" style="max-height:180px;">
                            {df_unassigned[["kelas_id", "kod_kursus", "ks"]].to_html(index=False, classes='clean-table') if df_unassigned is not None and not df_unassigned.empty else "<p class='empty-msg' style='color:#16a34a; background:#f0fdf4;'>✔ Semua aktif kelas berjaya diselesaikan.</p>"}
                        </div>
                    </div>
                </div>

                <div class="footer">
                    MyTimes Dashboard Portal Engine • Diperkesakan oleh Sistem Algoritma PuLP Fairness Target • Masa Penjanaan: {st.session_state.get('runtime_seconds', 0)}s
                </div>
                
            </div>
        </div>
    </body>
    </html>
    """

    st.download_button(
        "🌐 Download Premium Dashboard HTML",
        data=premium_html_report,
        file_name=f"MyTimes_PREMIUM_DASHBOARD_{st.session_state.get('semester_code','')}.html",
        mime="text/html",
        use_container_width=True,
    )
    st.markdown("---")

    # ------------------------------------------------------------
    # BUTTON 2: DOWNLOAD FULL HTML REPORT (SEMUA SEKALI RESULT)
    # ------------------------------------------------------------
    st.markdown("### 🌐 Laporan Penuh Sistem MyTimes (HTML Format)")
    st.caption("Butang di bawah akan memuat turun fail HTML premium yang menggabungkan kesemua keputusan dashboard, analisis mingguan, log kecemasan, dan tetapan manual.")

    # Ambil data log manual jika wujud
    df_manual_log = st.session_state.get("manual_tuning_log", pd.DataFrame())

    # Menjana struktur kod HTML penuh dengan reka bentuk CSS moden
    full_html_report = f"""
    <!DOCTYPE html>
    <html lang="ms">
    <head>
        <meta charset="UTF-8">
        <title>Laporan Penuh MyTimes - Semester {st.session_state.get('semester_code','')}</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 40px; background-color: #f4f6f9; color: #333; line-height: 1.6; }}
            .container {{ max-width: 1400px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }}
            
            /* Header Style */
            .header {{ background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); color: #fff; padding: 30px; border-radius: 8px; margin-bottom: 30px; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 2.2em; letter-spacing: 1px; }}
            .header p {{ margin: 10px 0 0 0; opacity: 0.9; font-size: 1.1em; }}
            
            /* Section & Card Style */
            h2 {{ color: #1e3c72; border-left: 5px solid #2a5298; padding-left: 12px; margin-top: 40px; margin-bottom: 15px; font-size: 1.5em; }}
            .meta-box {{ background-color: #eef2f7; padding: 15px; border-radius: 6px; font-size: 0.95em; margin-bottom: 20px; border-left: 4px solid #1e3c72; }}
            .empty-msg {{ color: #7f8c8d; font-style: italic; background: #f8f9fa; padding: 15px; border-radius: 6px; border: 1px dashed #ccc; }}
            
            /* Table Modern Design */
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 30px; font-size: 0.9em; box-shadow: 0 2px 5px rgba(0,0,0,0.02); border-radius: 6px; overflow: hidden; }}
            th {{ background-color: #2a5298; color: #ffffff; text-align: left; font-weight: 600; padding: 12px 15px; border: 1px solid #2a5298; }}
            td {{ padding: 10px 15px; border: 1px solid #e1e8ed; background-color: #fff; }}
            tr:nth-of-type(even) td {{ background-color: #f8fafc; }}
            tr:hover td {{ background-color: #f1f5f9; }}
            
            /* Badges & Footer */
            .badge-info {{ background: #e0f2fe; color: #0369a1; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.85em; }}
            .footer {{ text-align: center; margin-top: 50px; padding-top: 20px; border-top: 1px solid #e1e8ed; font-size: 0.85em; color: #7f8c8d; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>MyTimes Executive Dashboard Report</h1>
                <p>Sistem Pengagihan Beban Kerja Pensyarah (KS Terminology)</p>
            </div>

            <div class="meta-box">
                <b>Kod Semester:</b> {st.session_state.get('semester_code','')} | 
                <b>Masa Pemprosesan:</b> {st.session_state.get('runtime_seconds', 0)} saat | 
                <b>Tarikh Dijana:</b> {time.strftime('%d-%m-%Y %H:%M:%S')}
            </div>

            <h2>1. Ringkasan Status Agihan (Status Summary)</h2>
            {df_status.to_html(index=False, classes='table') if df_status is not None else "<p class='empty-msg'>Tiada data status.</p>"}

            <h2>2. Jadual Agihan Utama (Main Class Allocation)</h2>
            {df_assign.to_html(index=False, classes='table') if df_assign is not None and not df_assign.empty else "<p class='empty-msg'>Tiada data kelas diagihkan.</p>"}

            <h2>3. Analisis Beban Kerja Pensyarah (Lecturer Analysis Enhanced)</h2>
            {df_summary_enhanced.to_html(index=False, classes='table') if df_summary_enhanced is not None and not df_summary_enhanced.empty else "<p class='empty-msg'>Tiada rekod data pensyarah.</p>"}

            <h2>4. Garis Masa Beban Kerja Mingguan (Weekly Workload Timeline)</h2>
            {weekly_analysis.to_html(index=False, classes='table') if weekly_analysis is not None and not weekly_analysis.empty else "<p class='empty-msg'>Tiada garis masa mingguan dijana.</p>"}

            <h2>5. Nota Peristiwa Semester (Semester Event Notes)</h2>
            {semester_event_log.to_html(index=False, classes='table') if semester_event_log is not None and not semester_event_log.empty else "<p class='empty-msg'>Tiada catatan nota peristiwa direkodkan.</p>"}

            <h2>6. Log Kes Kecemasan (Emergency Replacement Log)</h2>
            {emergency_log.to_html(index=False, classes='table') if emergency_log is not None and not emergency_log.empty else "<p class='empty-msg'>Tiada kes penukaran kecemasan (Emergency) dimasukkan.</p>"}

            <h2>7. Log Pelarasan Manual (Manual Fine Tuning Log)</h2>
            {df_manual_log.to_html(index=False, classes='table') if not df_manual_log.empty else "<p class='empty-msg'>Tiada sebarang perubahan manual (Fine Tuning) dibuat oleh AJK.</p>"}

            <h2>8. Kes Cover Sementara (Temporary Cover Cases)</h2>
            {df_temp_cover.to_html(index=False, classes='table') if df_temp_cover is not None and not df_temp_cover.empty else "<p class='empty-msg'>Tiada pensyarah masuk lewat / kes cover awal minggu.</p>"}

            <h2>9. Kelas Tiada Agihan (Unallocated Classes)</h2>
            {df_unassigned.to_html(index=False, classes='table') if df_unassigned is not None and not df_unassigned.empty else "<p class='empty-msg' style='color:#155724; background:#d4edda; border-color:#c3e6cb;'>Semua kelas aktif berjaya diagihkan sepenuhnya (Zero Unallocated).</p>"}

            <h2>10. Kelas Ditutup (Closed Classes)</h2>
            {df_closed.to_html(index=False, classes='table') if df_closed is not None and not df_closed.empty else "<p class='empty-msg'>Tiada kelas berstatus TUTUP.</p>"}

            <div class="footer">
                MyTimes © 2026 • Fair KS Distribution Engine • Generated via Executive Streamlit Portal
            </div>
        </div>
    </body>
    </html>
    """

    st.download_button(
        "🌐 Download Full Result HTML",
        data=full_html_report,
        file_name=f"MyTimes_FULL_REPORT_{st.session_state.get('semester_code','')}.html",
        mime="text/html",
        use_container_width=True,
    )


st.sidebar.metric("Processing Time (sec)", st.session_state.get("runtime_seconds",0))
st.sidebar.metric("Fairness Score", f"{fairness}%", help="Based on average weekly workload across 14 weeks.")
st.sidebar.metric("Preference Score", f"{pref_score}%")
