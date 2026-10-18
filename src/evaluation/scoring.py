# Scoring infrastructure: tunable numbers + generic helpers, kept separate from
# the clinical rule checks in engine.py.
#
# REVISION HISTORY
# ----------------
# October 2026 – Updated per VR_Scoring_Weights_Doctor_Review_NBA.pdf:
#   - Time limits revised down for physician contact (10→2 min), monitoring
#     (10→5 min), venous access (20→5 min), infusion (22→6 min),
#     BGA (25→10 min), FAST (30→10 min).
#   - BGA and FAST ultrasound re-classified as "further diagnostics" (post-ABCDE),
#     no longer part of Section C.
#   - New critical-error rules: intubation without capnography, intubation without
#     prior airway check, skipping O2 for a critical patient (SpO2<90%), not
#     starting CPR when patient is unresponsive / HR<30.
#   - Patient-speaks-as-airway-proof removed (doctor: → not acceptable).
#   - Auscultation added as a separate Breathing sub-check.
#   ERC 2025 guidelines consulted for timing and clinical thresholds.

STAFF_CONTACT_TIME_LIMIT = 120     # Step 5: physician contacted within 2 min (Dr. Adams: "2")
GCS_TIME_LIMIT = 300               # Step 6: neuro/GCS assessed within 5 min (confirmed)
MONITORING_TIME_LIMIT = 300        # Step 7: full monitoring panel within 5 min (Dr. Adams: "5")
VENOUS_ACCESS_TIME_LIMIT = 300     # Step 10: IV access within 5 min (Dr. Adams: "5")
INFUSION_TIME_LIMIT = 360          # Step 11: infusion started within 6 min (Dr. Adams: "6")
BGA_TIME_LIMIT = 600               # BGA within 10 min of order (Dr. Adams: "10")
FAST_TIME_LIMIT = 600              # FAST within 10 min of order (Dr. Adams: "10")

# Step 7 requires all four of these, not just one.
MONITORING_SIGNALS = {
    "BP_CUFF_APPLY": "blood pressure cuff",
    "ECG_3LEAD_APPLY": "3-lead ECG",
    "PULSE_OX_APPLY": "pulse oximetry",
    "TEMPERATURE": "temperature",
}

POINTS = {
    # A - Airway
    "MISSING_AIRWAY": 10,
    # B - Breathing
    "MISSING_BREATHING": 10,
    "MISSING_AUSCULTATION": 5,      # Doctor: add auscultation as a separate B point
    # C - Circulation (core shock/haemodynamic checks)
    "MISSING_PULSE": 10,
    "MISSING_RECAP_CHECK": 5,
    "MISSING_STAFF_CONTACT": 10,
    "LATE_STAFF_CONTACT": 5,
    "MISSING_ALL_MONITORING": 15,
    "MONITORING_SIGNAL_ISSUE": 3,   # per missing/late signal among the 4
    "MISSING_VENOUS_ACCESS": 10,
    "LATE_VENOUS_ACCESS": 5,
    "MISSING_INFUSION": 10,
    "LATE_INFUSION": 5,
    # Further diagnostics (post-ABCDE) - Doctor: BGA and FAST do NOT belong to C
    "MISSING_BGA": 10,              # Not required in every scenario
    "LATE_BGA": 5,
    "MISSING_FAST": 10,             # Not required in every scenario
    "LATE_FAST": 5,
    # D - Disability
    "MISSING_GCS": 10,
    "LATE_GCS": 5,
    "MISSING_BLOOD_SUGAR_CHECK": 10,  # only applies if consciousness was altered
    # E - Exposure
    "MISSING_UNDRESS": 10,
    # Critical errors (Rule 24)
    "CATECHOLAMINE_ON_WARD": 20,
    "OXYGEN_WITHOUT_INDICATION": 10,        # SpO2 > 96%: point deduction only, NOT safety cap
    "OXYGEN_CHEST_PAIN_WITHOUT_INDICATION": 10,  # SpO2 > 90% in chest pain patient
    "WRONG_DECISION_PCI": 25,
    "UNINDICATED_ANESTHESIA_INDUCTION": 15,
    "INTUBATION_WITHOUT_CAPNOGRAPHY": 10,   # Doctor: new critical error
    "INTUBATION_WITHOUT_AIRWAY_CHECK": 15,  # Doctor: must check airway BEFORE intubation
    "SKIPPED_OXYGEN_CRITICAL_PATIENT": 15,  # Doctor: skipping O2 for SpO2 < 90% patient
    "MISSED_CPR_INDICATION": 20,            # Doctor: not starting CPR when HR<30 or apneic
    # Sequence/order violations
    "ORDER_ADRENALINE_BEFORE_MONITORING": 10,
    "ORDER_MEDICATION_BEFORE_ASSESSMENT": 10,
    "ORDER_INFUSION_PREPARED_NOT_ADMINISTERED": 5,
    "ORDER_FAST_BEFORE_PALPATION": 5,
    "ORDER_ASSESSMENT_BEFORE_BREATHING": 5,
    "ORDER_INTUBATION_BEFORE_AIRWAY_CHECK": 10,  # separate from missing check price
    # Step 4: shock position without prior indication
    "SHOCK_POSITION_WITHOUT_INDICATION": 15,
}

# "Fatal Flaw" safety net: a student can't pass by being fast everywhere else
# while skipping a life-critical step or committing a critical error.
# NOTE: OXYGEN_WITHOUT_INDICATION is NOT a safety-cap trigger (doctor's review:
# it is a deduction, not an automatic fail for simply giving O2 unsafely).
SAFETY_CAP_TRIGGERS = {
    "WRONG_MED_CATECHOLAMINE",
    "UNINDICATED_ANESTHESIA_INDUCTION",
    "WRONG_DECISION_PCI",
    "INTUBATION_WITHOUT_AIRWAY_CHECK",
    "MISSED_CPR_INDICATION",
    "SHOCK_POSITION_WITHOUT_INDICATION",
}
SAFETY_CAP_SCORE = 49

# Pass/fail cutoff – confirmed by Dr. Adams' review (Section 6 of review doc).
PASS_THRESHOLD = 70


def first_event_time(events, action_codes):
    """Earliest sim_time_seconds among events matching action_codes, or None if it never happened."""
    matches = [e.get("sim_time_seconds", 0) for e in events if e.get("action_code") in action_codes]
    return min(matches) if matches else None


def first_event_time_matching(events, predicate):
    """Earliest sim_time_seconds among events satisfying predicate(event), or None."""
    matches = [e.get("sim_time_seconds", 0) for e in events if predicate(e)]
    return min(matches) if matches else None


def has_event(events, action_codes):
    return any(e.get("action_code") in action_codes for e in events)


def closest_vital(vitals, sim_time_seconds):
    """Vital_parameters entry nearest in time to sim_time_seconds."""
    if not vitals:
        return None
    return min(vitals, key=lambda v: abs(v.get("sim_time_seconds", 0) - sim_time_seconds))


def apply_verdict(report):
    report["verdict"] = "Pass" if report["overall_score"] >= PASS_THRESHOLD else "Fail"


def new_report(metadata):
    return {
        "session_info": metadata,
        "overall_score": 100,
        "verdict": "Pass",
        "coverage": {
            "total_actions": 0,
            "evaluated_actions": 0,
            "unknown_actions": 0,
            "unknown_action_list": [],
            "coverage_percent": 100.0
        },
        "abcde_breakdown": {
            "A_Airway": {"status": "Missed", "points_deducted": 0},
            "B_Breathing": {"status": "Missed", "points_deducted": 0},
            "C_Circulation": {"status": "Missed", "points_deducted": 0},
            "D_Disability": {"status": "Missed", "points_deducted": 0},
            "E_Exposure": {"status": "Missed", "points_deducted": 0},
        },
        # Further diagnostics (post-ABCDE, not part of C) — BGA and FAST
        "further_diagnostics": {
            "BGA": {"status": "Missed", "points_deducted": 0},
            "FAST": {"status": "Missed", "points_deducted": 0},
        },
        # Orthogonal view grouped by rubric pillar
        "score_breakdown": {
            "completeness": {"points_deducted": 0},
            "order": {"points_deducted": 0},
            "timing": {"points_deducted": 0},
            "critical_errors": {"points_deducted": 0},
        },
        "feedback": [],
        "critical_errors": [],
    }


def deduct(report, amount, category):
    report["overall_score"] = max(0, report["overall_score"] - amount)
    report["score_breakdown"][category]["points_deducted"] += amount


def apply_safety_cap(report):
    """
    "Fatal Flaw" override: skipping Airway/Breathing entirely, or triggering a
    designated safety-cap critical error, caps the score at 49 (always Fail).
    NOTE: Oxygen given at SpO2 > 96% is a point deduction only, not a cap trigger.
    """
    airway_missed = report["abcde_breakdown"]["A_Airway"]["status"] != "Passed"
    breathing_missed = report["abcde_breakdown"]["B_Breathing"]["status"] != "Passed"
    cap_errors = [e for e in report["critical_errors"] if e in SAFETY_CAP_TRIGGERS]
    if (airway_missed or breathing_missed or cap_errors) and report["overall_score"] > SAFETY_CAP_SCORE:
        report["overall_score"] = SAFETY_CAP_SCORE
        report["feedback"].append(
            f"[Safety Cap] Score capped at {SAFETY_CAP_SCORE} – a life-critical step (Airway/Breathing) "
            "was skipped or a fatal clinical error occurred."
        )
