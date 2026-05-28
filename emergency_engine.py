# ============================================================
# MyTimes 6-File System — Emergency Reallocation Engine
# ============================================================
import pandas as pd


EMERGENCY_LOG_COLUMNS = [
    "case_no", "emergency_type", "emergency_reason", "emergency_lecturer",
    "class_id", "subject_code", "class_group",
    "original_week_before", "replacement_week", "original_week_continue",
    "replacement_lecturer", "split_group", "subject_KS", "replacement_weeks",
    "KS_before_replacement", "KS_added_full_class", "KS_added_average_semester",
    "KS_after_replacement", "average_KS_after_replacement", "peak_KS_after_replacement",
    "minimum_KS", "maximum_KS", "remaining_average_capacity_after",
    "remaining_capacity_after",
    "same_subject_experience", "eligibility_note", "emergency_decision_reason",
    "KS_calculation_method", "status"
]


def ensure_emergency_log(session_state):
    if "emergency_log" not in session_state or session_state["emergency_log"] is None:
        session_state["emergency_log"] = pd.DataFrame(columns=EMERGENCY_LOG_COLUMNS)


def _safe_bool(x):
    if isinstance(x, bool):
        return x
    return str(x).strip().lower() in {"true", "1", "yes", "y", "aktif", "active"}


def _week_range_text(a, b):
    return f"{int(a)}-{int(b)}" if int(a) != int(b) else str(int(a))


def _decision_reason(row, emergency_reason, split=False):
    reasons = []
    if int(row.get("same_subject_experience", 0)) == 1:
        reasons.append("already teaches / has experience with the same subject")
    if bool(row.get("below_min_before", False)) and bool(row.get("meets_min_after", False)):
        reasons.append("helps the lecturer reach the minimum KS requirement")
    elif bool(row.get("below_min_before", False)):
        reasons.append("improves an underload lecturer's KS position")
    if split:
        reasons.append("single lecturer could not take the full class KS, so the emergency class is split between two lecturers")
    else:
        reasons.append("still within maximum KS after taking the full class credit")
    if emergency_reason:
        reasons.append(f"emergency reason: {emergency_reason}")
    return "; ".join(reasons).capitalize() + "."


def _prepare_current_load(df_summary, emergency_log):
    required_cols = [
        "pensyarah", "jumlah_KS", "minimum_KS", "maksimum_KS", "aktif",
        "minggu_mula_available", "minggu_akhir_available", "senarai_subjek"
    ]
    available_cols = [c for c in required_cols if c in df_summary.columns]
    current_load = df_summary[available_cols].copy()
    if "minimum_KS" not in current_load.columns:
        current_load["minimum_KS"] = 0
    if "maksimum_KS" not in current_load.columns:
        current_load["maksimum_KS"] = 999
    if "senarai_subjek" not in current_load.columns:
        current_load["senarai_subjek"] = ""
    current_load = current_load.rename(columns={"jumlah_KS": "jumlah_KS_asal"})

    # Emergency workload must be tracked on a 14-week average basis.
    # A 4-KS class covered for 4 weeks contributes 4*(4/14)=1.14 average KS, not 4 full-semester KS.
    if emergency_log is not None and not emergency_log.empty:
        log = emergency_log.copy()
        if "replacement_lecturer" not in log.columns and "pensyarah_pengganti" in log.columns:
            log["replacement_lecturer"] = log["pensyarah_pengganti"]
        if "KS_added_average_semester" not in log.columns:
            if "KS_added_full_class" in log.columns and "replacement_weeks" in log.columns:
                log["KS_added_average_semester"] = (
                    pd.to_numeric(log["KS_added_full_class"], errors="coerce").fillna(0)
                    * pd.to_numeric(log["replacement_weeks"], errors="coerce").fillna(0) / 14.0
                )
            else:
                log["KS_added_average_semester"] = 0
        if "status" in log.columns:
            log = log[log["status"] == "OK"]
        previous = (
            log.groupby("replacement_lecturer")["KS_added_average_semester"]
            .sum()
            .reset_index()
            .rename(columns={"replacement_lecturer": "pensyarah", "KS_added_average_semester": "KS_emergency_avg_before"})
        ) if not log.empty else pd.DataFrame(columns=["pensyarah", "KS_emergency_avg_before"])
        current_load = current_load.merge(previous, on="pensyarah", how="left")
    else:
        current_load["KS_emergency_avg_before"] = 0.0

    current_load["KS_emergency_avg_before"] = current_load["KS_emergency_avg_before"].fillna(0.0)
    current_load["jumlah_KS_semasa"] = current_load["jumlah_KS_asal"].astype(float) + current_load["KS_emergency_avg_before"].astype(float)
    current_load["minimum_KS"] = pd.to_numeric(current_load["minimum_KS"], errors="coerce").fillna(0).astype(float)
    current_load["maksimum_KS"] = pd.to_numeric(current_load["maksimum_KS"], errors="coerce").fillna(999).astype(float)
    current_load["aktif"] = current_load["aktif"].apply(_safe_bool)
    return current_load


def _next_case_no(emergency_log):
    if emergency_log is None or emergency_log.empty:
        return 1
    if "case_no" in emergency_log.columns:
        val = pd.to_numeric(emergency_log["case_no"], errors="coerce").max()
        return int(val) + 1 if pd.notna(val) else 1
    return 1


def _candidate_pool(current_load, emergency_lecturer, overlap_start, overlap_end, subject_code, ks_value, semester_weeks=14):
    replacement_weeks = max(0, int(overlap_end) - int(overlap_start) + 1)
    average_added = round(float(ks_value) * replacement_weeks / float(semester_weeks), 4)

    candidates = current_load[
        (current_load["pensyarah"] != emergency_lecturer)
        & (current_load["aktif"] == True)
        & (current_load["minggu_mula_available"] <= overlap_start)
        & (current_load["minggu_akhir_available"] >= overlap_end)
    ].copy()
    if candidates.empty:
        return candidates

    candidates["same_subject_experience"] = candidates["senarai_subjek"].astype(str).apply(
        lambda x: 1 if str(subject_code) in x else 0
    )

    # Two views are kept:
    # 1) peak_KS_after_replacement = affected-week load while the lecturer covers.
    #    This is the HARD eligibility rule and must not exceed maximum_KS.
    # 2) average_KS_after_replacement = fair semester reporting average across 14 weeks.
    candidates["KS_added_average_semester"] = average_added
    candidates["peak_KS_after_replacement"] = candidates["jumlah_KS_semasa"] + float(ks_value)
    candidates["average_KS_after_replacement"] = candidates["jumlah_KS_semasa"] + average_added

    # Backward-compatible columns used by the UI/log.
    candidates["KS_after_replacement"] = candidates["peak_KS_after_replacement"]
    candidates["remaining_average_capacity_after"] = candidates["maksimum_KS"] - candidates["average_KS_after_replacement"]
    candidates["remaining_capacity_after"] = candidates["remaining_average_capacity_after"]

    candidates["below_min_before"] = candidates["jumlah_KS_semasa"] < candidates["minimum_KS"]
    candidates["meets_min_after"] = candidates["average_KS_after_replacement"] >= candidates["minimum_KS"]
    candidates["underload_gap_before"] = (candidates["minimum_KS"] - candidates["jumlah_KS_semasa"]).clip(lower=0)
    return candidates


def _rank_candidates(candidates):
    return candidates.sort_values(
        by=["same_subject_experience", "meets_min_after", "below_min_before", "jumlah_KS_semasa", "remaining_capacity_after"],
        ascending=[False, False, False, True, False],
    )


def compute_emergency_reallocation(
    df_assign,
    df_summary,
    emergency_log,
    emergency_lecturer,
    start_week,
    end_week,
    emergency_reason="",
    emergency_type="Temporary class replacement",
    allow_split_replacement=True,
):
    """
    Emergency rule:
    - Replacement KS is counted as FULL class KS if one lecturer covers the class.
    - If no single lecturer can take the full class without exceeding maximum KS, MyTimes can split the emergency class into two lecturers.
      Example: one 4-KS class can be covered as 2 KS + 2 KS.
    - Weekly lecturer analysis must be read together with the emergency log because actual load changes by week.
    """
    if df_assign.empty or df_summary.empty:
        return pd.DataFrame(columns=EMERGENCY_LOG_COLUMNS)

    emergency_classes = df_assign[df_assign["pensyarah_utama"] == emergency_lecturer].copy()
    if emergency_classes.empty:
        return pd.DataFrame(columns=EMERGENCY_LOG_COLUMNS)

    current_load = _prepare_current_load(df_summary, emergency_log)
    case_no = _next_case_no(emergency_log)
    rows = []

    for _, row in emergency_classes.iterrows():
        class_start = int(row["minggu_mula_kelas"])
        class_end = int(row["minggu_akhir_kelas"])
        overlap_start = max(class_start, int(start_week))
        overlap_end = min(class_end, int(end_week))
        if overlap_start > overlap_end:
            continue

        replacement_weeks = overlap_end - overlap_start + 1
        ks_full_class = round(float(row["KS"]), 2)
        base_common = {
            "case_no": case_no,
            "emergency_type": emergency_type,
            "emergency_reason": emergency_reason,
            "emergency_lecturer": emergency_lecturer,
            "class_id": row["kelas_id"],
            "subject_code": row["kod_kursus"],
            "class_group": row["kelas_baru"],
            "original_week_before": _week_range_text(class_start, overlap_start - 1) if class_start < overlap_start else "",
            "replacement_week": _week_range_text(overlap_start, overlap_end),
            "original_week_continue": _week_range_text(overlap_end + 1, class_end) if overlap_end < class_end else "",
            "subject_KS": ks_full_class,
            "replacement_weeks": replacement_weeks,
        }

        candidates = _candidate_pool(current_load, emergency_lecturer, overlap_start, overlap_end, row["kod_kursus"], ks_full_class)
        if candidates.empty:
            fail = dict(base_common)
            fail.update({
                "replacement_lecturer": "NO AVAILABLE LECTURER", "split_group": "",
                "KS_before_replacement": 0, "KS_added_full_class": ks_full_class, "KS_added_average_semester": 0,
                "KS_after_replacement": 0, "average_KS_after_replacement": 0, "peak_KS_after_replacement": 0,
                "minimum_KS": 0, "maximum_KS": 0, "remaining_average_capacity_after": 0, "remaining_capacity_after": 0,
                "same_subject_experience": "No",
                "eligibility_note": "No active lecturer is available for the selected emergency weeks.",
                "emergency_decision_reason": "Failed because no active lecturer is available for the selected emergency period.",
                "KS_calculation_method": "Full subject/class KS per replaced class",
                "status": "FAILED",
            })
            rows.append(fail)
            continue

        # HARD RULE: emergency / temporary cover cannot exceed maximum KS in the affected week(s).
        # The 14-week average is only a reporting metric, not an eligibility loophole.
        eligible = candidates[candidates["peak_KS_after_replacement"] <= candidates["maksimum_KS"]].copy()
        if not eligible.empty:
            selected = _rank_candidates(eligible).iloc[0]
            replacement_lecturer = selected["pensyarah"]
            # Track current affected-week load for subsequent emergency classes so the
            # same lecturer is not repeatedly selected beyond max KS.
            current_load.loc[current_load["pensyarah"] == replacement_lecturer, "jumlah_KS_semasa"] = float(selected["peak_KS_after_replacement"])
            out = dict(base_common)
            out.update({
                "replacement_lecturer": replacement_lecturer,
                "split_group": "Single lecturer full class coverage",
                "KS_before_replacement": round(float(selected["jumlah_KS_semasa"]), 2),
                "KS_added_full_class": ks_full_class,
                "KS_added_average_semester": round(float(selected["KS_added_average_semester"]), 2),
                "KS_after_replacement": round(float(selected["KS_after_replacement"]), 2),
                "average_KS_after_replacement": round(float(selected["average_KS_after_replacement"]), 2),
                "peak_KS_after_replacement": round(float(selected["peak_KS_after_replacement"]), 2),
                "minimum_KS": round(float(selected["minimum_KS"]), 2),
                "maximum_KS": round(float(selected["maksimum_KS"]), 2),
                                                                        "remaining_average_capacity_after": round(float(selected["remaining_average_capacity_after"]), 2),
                        "remaining_capacity_after": round(float(selected["remaining_capacity_after"]), 2),
                "same_subject_experience": "Yes" if int(selected["same_subject_experience"]) == 1 else "No",
                "eligibility_note": "Eligible: active, available during emergency weeks, and within maximum KS in the affected week(s). Average load is used only for reporting.",
                "emergency_decision_reason": _decision_reason(selected, emergency_reason, split=False),
                "KS_calculation_method": "Full subject/class KS per replaced class",
                "status": "OK",
            })
            rows.append(out)
            continue

        # Fallback: split one emergency class between two lecturers, e.g. 4 KS = 2 KS + 2 KS.
        if allow_split_replacement:
            split_ks = round(ks_full_class / 2.0, 2)
            split_candidates = _candidate_pool(current_load, emergency_lecturer, overlap_start, overlap_end, row["kod_kursus"], split_ks)
            split_eligible = split_candidates[split_candidates["peak_KS_after_replacement"] <= split_candidates["maksimum_KS"]].copy()
            split_eligible = _rank_candidates(split_eligible).head(2)

            if len(split_eligible) >= 2:
                for part_no, (_, selected) in enumerate(split_eligible.iterrows(), start=1):
                    replacement_lecturer = selected["pensyarah"]
                    # Track current affected-week load for subsequent emergency classes so the
                    # same lecturer is not repeatedly selected beyond max KS.
                    current_load.loc[current_load["pensyarah"] == replacement_lecturer, "jumlah_KS_semasa"] = float(selected["peak_KS_after_replacement"])
                    out = dict(base_common)
                    out.update({
                        "emergency_type": f"{emergency_type} - split coverage",
                        "replacement_lecturer": replacement_lecturer,
                        "split_group": f"Split {part_no}/2",
                        "KS_before_replacement": round(float(selected["jumlah_KS_semasa"]), 2),
                        "KS_added_full_class": split_ks,
                        "KS_added_average_semester": round(float(selected["KS_added_average_semester"]), 2),
                        "KS_after_replacement": round(float(selected["KS_after_replacement"]), 2),
                        "average_KS_after_replacement": round(float(selected["average_KS_after_replacement"]), 2),
                        "peak_KS_after_replacement": round(float(selected["peak_KS_after_replacement"]), 2),
                        "minimum_KS": round(float(selected["minimum_KS"]), 2),
                        "maximum_KS": round(float(selected["maksimum_KS"]), 2),
                                        "remaining_average_capacity_after": round(float(selected["remaining_average_capacity_after"]), 2),
                "remaining_capacity_after": round(float(selected["remaining_capacity_after"]), 2),
                        "same_subject_experience": "Yes" if int(selected["same_subject_experience"]) == 1 else "No",
                        "eligibility_note": "Eligible for split emergency coverage: active, available, and within maximum KS after partial KS allocation.",
                        "emergency_decision_reason": _decision_reason(selected, emergency_reason, split=True),
                        "KS_calculation_method": "Split emergency coverage: subject/class KS divided between two lecturers",
                        "status": "OK",
                    })
                    rows.append(out)
                continue

        fail = dict(base_common)
        fail.update({
            "replacement_lecturer": "NO ELIGIBLE CANDIDATE", "split_group": "",
            "KS_before_replacement": 0, "KS_added_full_class": ks_full_class, "KS_added_average_semester": 0,
            "KS_after_replacement": 0, "average_KS_after_replacement": 0, "peak_KS_after_replacement": 0,
            "minimum_KS": 0, "maximum_KS": 0, "remaining_average_capacity_after": 0, "remaining_capacity_after": 0,
            "same_subject_experience": "No",
            "eligibility_note": "All available lecturers would exceed maximum KS in the affected week(s). Split coverage also failed or was disabled.",
            "emergency_decision_reason": "Failed because no single or split replacement can satisfy the hard weekly maximum KS rule for the selected emergency weeks.",
            "KS_calculation_method": "Full subject/class KS, with split fallback if enabled",
            "status": "FAILED",
        })
        rows.append(fail)

    return pd.DataFrame(rows, columns=EMERGENCY_LOG_COLUMNS)
