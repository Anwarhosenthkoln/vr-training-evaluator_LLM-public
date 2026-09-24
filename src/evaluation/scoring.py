# Scoring infrastructure: tunable numbers + generic helpers, kept separate from
# the clinical rule checks in newengine.py. Time limits come from
# "Ablauf_Notfall auf Normalstation_NBA.docx"; every point value below is our
# own placeholder scale, pending the doctor's sign-off -- tune freely.

STAFF_CONTACT_TIME_LIMIT = 600     # Step 5: physician contacted within 10 min
GCS_TIME_LIMIT = 300               # Step 6: neuro/GCS assessed within 5 min
MONITORING_TIME_LIMIT = 600        # Step 7: BP/ECG/PulseOx/Temp within 10 min
VENOUS_ACCESS_TIME_LIMIT = 1200    # Step 10: IV_ACCESS (PVK) within 20 min
INFUSION_TIME_LIMIT = 1320         # Step 11: INFUSION within 22 min
BGA_TIME_LIMIT = 1500              # Step 12: blood gas analysis within 25 min
FAST_TIME_LIMIT = 1800             # Step 13: FAST ultrasound within 30 min

# Step 7 requires all four of these, not just one.
MONITORING_SIGNALS = {
    "BP_CUFF_APPLY": "blood pressure cuff",
    "ECG_3LEAD_APPLY": "3-lead ECG",
    "PULSE_OX_APPLY": "pulse oximetry",
    "TEMPERATURE": "temperature",
}

POINTS = {
    "MISSING_AIRWAY": 10,
    "MISSING_BREATHING": 10,
    "MISSING_PULSE": 10,
    "MISSING_RECAP_CHECK": 5,
    "MISSING_STAFF_CONTACT": 10,
    "LATE_STAFF_CONTACT": 5,
    "MISSING_ALL_MONITORING": 15,
    "MONITORING_SIGNAL_ISSUE": 3,   # per missing/late signal among the 4 above
    "MISSING_VENOUS_ACCESS": 10,
    "LATE_VENOUS_ACCESS": 5,
    "MISSING_INFUSION": 10,
    "LATE_INFUSION": 5,
    "MISSING_BGA": 10,
    "LATE_BGA": 5,
    "MISSING_FAST": 10,
    "LATE_FAST": 5,
    "MISSING_GCS": 10,
    "LATE_GCS": 5,
    "MISSING_BLOOD_SUGAR_CHECK": 10,  # only applies if consciousness was altered
    "MISSING_UNDRESS": 10,
    "CATECHOLAMINE_ON_WARD": 20,
    "OXYGEN_WITHOUT_INDICATION": 10,
    "WRONG_DECISION_PCI": 25,
    # Confirmed by a real expert annotation in the data ("falsch, keine
    # Narkoseinduktion notwendig") -- unindicated anesthesia induction on the ward.
    "UNINDICATED_ANESTHESIA_INDUCTION": 15,
    # Sequence/order violations -- "Reihenfolge / Abhaengigkeiten" pillar from
    # Entwicklung eines standardisierten Bewertungsmodells...docx. Each is
    # flagged once per session (it's a yes/no "did this happen out of order",
    # not something to penalize per repetition).
    "ORDER_ADRENALINE_BEFORE_MONITORING": 10,
    "ORDER_MEDICATION_BEFORE_ASSESSMENT": 10,
    "ORDER_INFUSION_PREPARED_NOT_ADMINISTERED": 5,
    # Both confirmed by real expert annotations in the data, not guessed:
    # "richtig, jedoch erst nach koerperlicher Untersuchung -> Palpation" and
    # "vorherige Kontrolle der Atmung eigentlich notwendig" (x2, different sessions).
    "ORDER_FAST_BEFORE_PALPATION": 5,
    "ORDER_ASSESSMENT_BEFORE_BREATHING": 5,
    # Step 4: shock recognition. Explicit "Fehlerkriterium" in the procedure doc --
    # putting the patient in shock position before any clinical sign was checked.
    "SHOCK_POSITION_WITHOUT_INDICATION": 15,
}

# "Fatal Flaw" safety net: a student can't pass by being fast everywhere else
# while skipping a life-critical step or committing a critical error.
SAFETY_CAP_SCORE = 49

# Placeholder pass/fail cutoff -- not confirmed by the doctor. Since the safety
# cap tops out at 49, anything capped will always fail under this threshold.
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
    """Vital_parameters entry nearest in time to sim_time_seconds (vitals are logged on a separate timeline)."""
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
        "abcde_breakdown": {
            "A_Airway": {"status": "Missed", "points_deducted": 0},
            "B_Breathing": {"status": "Missed", "points_deducted": 0},
            "C_Circulation": {"status": "Missed", "points_deducted": 0},
            "D_Disability": {"status": "Missed", "points_deducted": 0},
            "E_Exposure": {"status": "Missed", "points_deducted": 0},
        },
        # Orthogonal view of the same deductions, grouped by rubric pillar
        # (completeness / order / timing / critical) per the design doc's
        # suggested "Score gesamt + Teilscore" output.
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
    "Fatal Flaw" override: skipping Airway/Breathing entirely, or triggering any
    critical error, caps the score even if every timed/completeness item elsewhere
    was fast and complete. Prevents a "speed-run" session from looking like a pass.
    """
    airway_missed = report["abcde_breakdown"]["A_Airway"]["status"] != "Passed"
    breathing_missed = report["abcde_breakdown"]["B_Breathing"]["status"] != "Passed"
    if (airway_missed or breathing_missed or report["critical_errors"]) and report["overall_score"] > SAFETY_CAP_SCORE:
        report["overall_score"] = SAFETY_CAP_SCORE
        report["feedback"].append(
            f"[Safety Cap] Score capped at {SAFETY_CAP_SCORE} -- a life-critical step (Airway/Breathing) "
            "was skipped or a critical error occurred, regardless of performance elsewhere."
        )
