import json
import os

from scoring import (
    STAFF_CONTACT_TIME_LIMIT,
    GCS_TIME_LIMIT,
    MONITORING_TIME_LIMIT,
    VENOUS_ACCESS_TIME_LIMIT,
    INFUSION_TIME_LIMIT,
    BGA_TIME_LIMIT,
    FAST_TIME_LIMIT,
    MONITORING_SIGNALS,
    POINTS,
    SAFETY_CAP_TRIGGERS,
    first_event_time,
    first_event_time_matching,
    has_event,
    closest_vital,
    new_report,
    deduct,
    apply_safety_cap,
    apply_verdict,
)

# ---------------------------------------------------------------------------
# Helper: accept an action if the student did it personally OR delegated it.
# ---------------------------------------------------------------------------
def _has_action_or_delegate(events, base_codes):
    delegate_codes = [f"DELEGATE_{c}" for c in base_codes]
    return has_event(events, base_codes + delegate_codes)


def _first_time_action_or_delegate(events, base_codes):
    delegate_codes = [f"DELEGATE_{c}" for c in base_codes]
    return first_event_time(events, base_codes + delegate_codes)


def _action_entry(name, result, time_s=None, note=None, points_deducted=0):
    """Build a structured action entry for abcde_detail."""
    entry = {
        "action": name,
        "result": result,        # "Completed", "Missed", "Late", "Wrong Order"
        "points_deducted": points_deducted,
    }
    if time_s is not None:
        mins, secs = divmod(int(time_s), 60)
        entry["time"] = f"{mins}:{secs:02d}"
    if note:
        entry["note"] = note
    return entry


def evaluate_session(parsed_session_path, output_report_path):
    """
    Reads a parsed JSON file and applies the ABCDE medical rules to generate
    a scoring report with per-category action detail.

    Rules updated October 2026 per VR_Scoring_Weights_Doctor_Review_NBA.pdf
    and ERC Guidelines 2025.
    """
    with open(parsed_session_path, 'r', encoding='utf-8') as f:
        session_data = json.load(f)

    if isinstance(session_data, list):
        events = session_data
        vitals = []
        # Derive metadata from filename + events for bare-list logs (old TXT format)
        basename = os.path.splitext(os.path.basename(parsed_session_path))[0]
        metadata = {"Modul": "Station"}
        # Extract date & time from filenames like UKK_VR_LogExport_2026-8-17_10-20-33
        import re as _re
        m = _re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})(?:[_-](\d{1,2})-(\d{2})-(\d{2}))?', basename)
        if m:
            yr, mo, dy = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
            metadata["Datum"] = f"{dy}.{mo}.{yr}"
            if m.group(4):
                metadata["Start"] = f"{m.group(4).zfill(2)}:{m.group(5)}:{m.group(6)}"
        else:
            metadata["Datum"] = basename
        # Duration from last event's sim_time
        timed = [e for e in events if e.get("sim_time") and e.get("sim_time") != "0:00"]
        if timed:
            metadata["Dauer"] = timed[-1]["sim_time"]
    else:
        events = session_data.get('events', [])
        metadata = session_data.get('metadata', {})
        vitals = session_data.get('vital_parameters', [])

    report = new_report(metadata)

    # ------------------------------------------------------------------
    # Coverage Statistics
    # ------------------------------------------------------------------
    start_events = [e for e in events if e.get("phase", "Start") in ("Start", "Info")]
    total_actions = len(start_events)
    unknown_events = [e for e in start_events if "UNKNOWN" in e.get("action_code", "")]
    unknown_actions = len(unknown_events)
    evaluated_actions = total_actions - unknown_actions

    report["coverage"]["total_actions"] = total_actions
    report["coverage"]["evaluated_actions"] = evaluated_actions
    report["coverage"]["unknown_actions"] = unknown_actions
    unique_unknowns = sorted(set(e.get("action_raw", "") for e in unknown_events))
    report["coverage"]["unknown_action_list"] = unique_unknowns
    report["coverage"]["coverage_percent"] = (
        round((evaluated_actions / total_actions) * 100, 1) if total_actions > 0 else 0.0
    )

    # ------------------------------------------------------------------
    # A: Airway
    # ------------------------------------------------------------------
    a_actions = []
    if has_event(events, ["CHECK_AIRWAY"]):
        t = first_event_time(events, ["CHECK_AIRWAY"])
        a_actions.append(_action_entry("Airway check (open/look/listen/feel)", "Completed", t))
        report["abcde_breakdown"]["A_Airway"]["status"] = "Passed"
    else:
        a_actions.append(_action_entry(
            "Airway check (open/look/listen/feel)", "Missed",
            note="No explicit airway check detected. ERC 2025 requires opening airway, look/listen/feel.",
            points_deducted=POINTS["MISSING_AIRWAY"]
        ))
        report["abcde_breakdown"]["A_Airway"]["points_deducted"] = POINTS["MISSING_AIRWAY"]
        report["feedback"].append("[A] Airway was not explicitly checked!")
        deduct(report, POINTS["MISSING_AIRWAY"], "completeness")

    report["abcde_detail"]["A_Airway"]["actions"] = a_actions

    # ------------------------------------------------------------------
    # B: Breathing
    # ------------------------------------------------------------------
    b_actions = []
    b_passed = True
    b_points = 0

    if has_event(events, ["CHECK_BREATHING"]):
        t = first_event_time(events, ["CHECK_BREATHING"])
        b_actions.append(_action_entry("Breathing assessment", "Completed", t))
    else:
        b_passed = False
        b_points += POINTS["MISSING_BREATHING"]
        b_actions.append(_action_entry(
            "Breathing assessment", "Missed",
            note="Basic breathing check (respiratory rate, effort) was not performed.",
            points_deducted=POINTS["MISSING_BREATHING"]
        ))
        report["feedback"].append("[B] Breathing was not assessed!")
        deduct(report, POINTS["MISSING_BREATHING"], "completeness")

    if has_event(events, ["AUSCULTATION"]):
        t = first_event_time(events, ["AUSCULTATION"])
        b_actions.append(_action_entry("Lung auscultation", "Completed", t))
    else:
        b_passed = False
        b_points += POINTS["MISSING_AUSCULTATION"]
        b_actions.append(_action_entry(
            "Lung auscultation", "Missed",
            note="Auscultation of the lungs is required as a separate B sub-check (per doctor review).",
            points_deducted=POINTS["MISSING_AUSCULTATION"]
        ))
        report["feedback"].append("[B] Auscultation of the lungs was not performed!")
        deduct(report, POINTS["MISSING_AUSCULTATION"], "completeness")

    report["abcde_breakdown"]["B_Breathing"]["status"] = "Passed" if b_passed else "Missed"
    report["abcde_breakdown"]["B_Breathing"]["points_deducted"] = b_points
    report["abcde_detail"]["B_Breathing"]["actions"] = b_actions

    # ------------------------------------------------------------------
    # C: Circulation
    # ------------------------------------------------------------------
    c_actions = []
    c_points_deducted = 0
    c_passed = True

    # Pulse
    if has_event(events, ["CHECK_PULSE"]):
        t = first_event_time(events, ["CHECK_PULSE"])
        c_actions.append(_action_entry("Pulse check", "Completed", t))
    else:
        c_passed = False
        c_points_deducted += POINTS["MISSING_PULSE"]
        c_actions.append(_action_entry(
            "Pulse check", "Missed",
            note="Pulse assessment is mandatory in C-Circulation.",
            points_deducted=POINTS["MISSING_PULSE"]
        ))
        report["feedback"].append("[C] Pulse was not checked!")
        deduct(report, POINTS["MISSING_PULSE"], "completeness")

    # Capillary refill
    if has_event(events, ["RECAP_TIME"]):
        t = first_event_time(events, ["RECAP_TIME"])
        c_actions.append(_action_entry("Capillary refill (ReCap)", "Completed", t))
    else:
        c_passed = False
        c_points_deducted += POINTS["MISSING_RECAP_CHECK"]
        c_actions.append(_action_entry(
            "Capillary refill (ReCap)", "Missed",
            note="Capillary refill time assesses peripheral perfusion.",
            points_deducted=POINTS["MISSING_RECAP_CHECK"]
        ))
        report["feedback"].append("[C] Capillary refill / recap time was never assessed!")
        deduct(report, POINTS["MISSING_RECAP_CHECK"], "completeness")

    # Physician contact
    staff_time = first_event_time_matching(
        events,
        lambda e: e.get("action_code") in ("DELEGATE_NPC", "CALL_PHYSICIAN")
        and any(kw in e.get("details", "").lower() for kw in ("medizin", "arzt", "physician", "doctor"))
    )
    if staff_time is None:
        c_passed = False
        c_points_deducted += POINTS["MISSING_STAFF_CONTACT"]
        c_actions.append(_action_entry(
            "Physician contact", "Missed",
            note="Medical staff must be contacted within 2 minutes.",
            points_deducted=POINTS["MISSING_STAFF_CONTACT"]
        ))
        report["feedback"].append("[C] Physician / medical staff was never contacted!")
        deduct(report, POINTS["MISSING_STAFF_CONTACT"], "completeness")
    elif staff_time > STAFF_CONTACT_TIME_LIMIT:
        c_passed = False
        c_points_deducted += POINTS["LATE_STAFF_CONTACT"]
        c_actions.append(_action_entry(
            "Physician contact", "Late", staff_time,
            note=f"Target: < {STAFF_CONTACT_TIME_LIMIT}s (2 min). Actual: {staff_time}s.",
            points_deducted=POINTS["LATE_STAFF_CONTACT"]
        ))
        report["feedback"].append(
            f"[C] Physician contacted late at {staff_time}s (target < {STAFF_CONTACT_TIME_LIMIT}s / 2 min)."
        )
        deduct(report, POINTS["LATE_STAFF_CONTACT"], "timing")
    else:
        c_actions.append(_action_entry("Physician contact", "Completed", staff_time))

    # Monitoring panel
    missing_signals = []
    late_signals = []
    any_monitoring_done = False
    for code, label in MONITORING_SIGNALS.items():
        t = _first_time_action_or_delegate(events, [code])
        if t is None:
            missing_signals.append(label)
        else:
            any_monitoring_done = True
            if t > MONITORING_TIME_LIMIT:
                late_signals.append((label, t))
            else:
                c_actions.append(_action_entry(f"Monitoring: {label}", "Completed", t))

    if not any_monitoring_done:
        c_passed = False
        c_points_deducted += POINTS["MISSING_ALL_MONITORING"]
        for code, label in MONITORING_SIGNALS.items():
            c_actions.append(_action_entry(
                f"Monitoring: {label}", "Missed",
                note="No monitoring equipment applied at all.",
                points_deducted=POINTS["MONITORING_SIGNAL_ISSUE"]
            ))
        report["feedback"].append("[C] Critical: No monitoring equipment (BP/ECG/SpO2/temperature) applied!")
        report["critical_errors"].append("MISSING_STEP_MONITORING")
        deduct(report, POINTS["MISSING_ALL_MONITORING"], "completeness")
    else:
        if missing_signals:
            c_passed = False
            amount = POINTS["MONITORING_SIGNAL_ISSUE"] * len(missing_signals)
            c_points_deducted += amount
            for label in missing_signals:
                c_actions.append(_action_entry(
                    f"Monitoring: {label}", "Missed",
                    note=f"Target: within {MONITORING_TIME_LIMIT}s. Never applied.",
                    points_deducted=POINTS["MONITORING_SIGNAL_ISSUE"]
                ))
            report["feedback"].append(
                f"[C] Monitoring incomplete, never applied: {', '.join(missing_signals)}."
            )
            deduct(report, amount, "completeness")
        for label, t in late_signals:
            c_passed = False
            c_points_deducted += POINTS["MONITORING_SIGNAL_ISSUE"]
            c_actions.append(_action_entry(
                f"Monitoring: {label}", "Late", t,
                note=f"Target: < {MONITORING_TIME_LIMIT}s.",
                points_deducted=POINTS["MONITORING_SIGNAL_ISSUE"]
            ))
            report["feedback"].append(
                f"[C] {label} applied late at {t}s (target < {MONITORING_TIME_LIMIT}s)."
            )
            deduct(report, POINTS["MONITORING_SIGNAL_ISSUE"], "timing")

    # IV access
    iv_time = _first_time_action_or_delegate(events, ["IV_ACCESS"])
    if iv_time is None:
        c_passed = False
        c_points_deducted += POINTS["MISSING_VENOUS_ACCESS"]
        c_actions.append(_action_entry(
            "Venous access (PVK)", "Missed",
            note="IV access must be established within 5 minutes.",
            points_deducted=POINTS["MISSING_VENOUS_ACCESS"]
        ))
        report["feedback"].append("[C] Venous access (PVK) was never established!")
        deduct(report, POINTS["MISSING_VENOUS_ACCESS"], "completeness")
    elif iv_time > VENOUS_ACCESS_TIME_LIMIT:
        c_passed = False
        c_points_deducted += POINTS["LATE_VENOUS_ACCESS"]
        c_actions.append(_action_entry(
            "Venous access (PVK)", "Late", iv_time,
            note=f"Target: < {VENOUS_ACCESS_TIME_LIMIT}s.",
            points_deducted=POINTS["LATE_VENOUS_ACCESS"]
        ))
        report["feedback"].append(
            f"[C] Venous access established late at {iv_time}s (target < {VENOUS_ACCESS_TIME_LIMIT}s)."
        )
        deduct(report, POINTS["LATE_VENOUS_ACCESS"], "timing")
    else:
        c_actions.append(_action_entry("Venous access (PVK)", "Completed", iv_time))

    # Infusion
    infusion_time = _first_time_action_or_delegate(events, ["INFUSION"])
    if infusion_time is None:
        c_passed = False
        c_points_deducted += POINTS["MISSING_INFUSION"]
        c_actions.append(_action_entry(
            "Infusion", "Missed",
            note="Infusion must be started within 6 minutes.",
            points_deducted=POINTS["MISSING_INFUSION"]
        ))
        report["feedback"].append("[C] Infusion was never started!")
        deduct(report, POINTS["MISSING_INFUSION"], "completeness")
    elif infusion_time > INFUSION_TIME_LIMIT:
        c_passed = False
        c_points_deducted += POINTS["LATE_INFUSION"]
        c_actions.append(_action_entry(
            "Infusion", "Late", infusion_time,
            note=f"Target: < {INFUSION_TIME_LIMIT}s.",
            points_deducted=POINTS["LATE_INFUSION"]
        ))
        report["feedback"].append(
            f"[C] Infusion started late at {infusion_time}s (target < {INFUSION_TIME_LIMIT}s)."
        )
        deduct(report, POINTS["LATE_INFUSION"], "timing")
    else:
        c_actions.append(_action_entry("Infusion", "Completed", infusion_time))

    report["abcde_breakdown"]["C_Circulation"]["status"] = "Passed" if c_passed else "Missed"
    report["abcde_breakdown"]["C_Circulation"]["points_deducted"] = c_points_deducted
    report["abcde_detail"]["C_Circulation"]["actions"] = c_actions

    # ------------------------------------------------------------------
    # D: Disability
    # ------------------------------------------------------------------
    d_actions = []
    d_points_deducted = 0
    d_passed = True

    gcs_time = first_event_time(events, ["GCS_CHECK", "NEURO_EXAM"])
    if gcs_time is None:
        d_passed = False
        d_points_deducted += POINTS["MISSING_GCS"]
        d_actions.append(_action_entry(
            "GCS / Neurological assessment", "Missed",
            note="Either GCS or neuro exam must be performed within 5 minutes.",
            points_deducted=POINTS["MISSING_GCS"]
        ))
        report["feedback"].append("[D] GCS / neurological status was never assessed!")
        deduct(report, POINTS["MISSING_GCS"], "completeness")
    elif gcs_time > GCS_TIME_LIMIT:
        d_passed = False
        d_points_deducted += POINTS["LATE_GCS"]
        d_actions.append(_action_entry(
            "GCS / Neurological assessment", "Late", gcs_time,
            note=f"Target: < {GCS_TIME_LIMIT}s.",
            points_deducted=POINTS["LATE_GCS"]
        ))
        report["feedback"].append(
            f"[D] GCS / neuro assessment late at {gcs_time}s (target < {GCS_TIME_LIMIT}s)."
        )
        deduct(report, POINTS["LATE_GCS"], "timing")
    else:
        d_actions.append(_action_entry("GCS / Neurological assessment", "Completed", gcs_time))

    if vitals:
        consciousness_altered = any(
            v.get("gcs") is not None and v.get("gcs") < 15 for v in vitals
        )
        if consciousness_altered:
            if _has_action_or_delegate(events, ["BLOOD_SUGAR", "BLOOD_GAS_ANALYSIS"]):
                t = first_event_time(events, ["BLOOD_SUGAR", "BLOOD_GAS_ANALYSIS"])
                d_actions.append(_action_entry("Blood sugar measurement", "Completed", t,
                                               note="Required because GCS < 15."))
            else:
                d_passed = False
                d_points_deducted += POINTS["MISSING_BLOOD_SUGAR_CHECK"]
                d_actions.append(_action_entry(
                    "Blood sugar measurement", "Missed",
                    note="Required because patient had GCS < 15 (altered consciousness).",
                    points_deducted=POINTS["MISSING_BLOOD_SUGAR_CHECK"]
                ))
                report["feedback"].append(
                    "[D] Consciousness was altered (GCS < 15) but blood sugar was never measured!"
                )
                deduct(report, POINTS["MISSING_BLOOD_SUGAR_CHECK"], "completeness")
        else:
            d_actions.append(_action_entry("Blood sugar measurement", "Not Required",
                                           note="GCS was normal — not mandatory."))

    report["abcde_breakdown"]["D_Disability"]["status"] = "Passed" if d_passed else "Missed"
    report["abcde_breakdown"]["D_Disability"]["points_deducted"] = d_points_deducted
    report["abcde_detail"]["D_Disability"]["actions"] = d_actions

    # ------------------------------------------------------------------
    # E: Exposure
    # ------------------------------------------------------------------
    e_actions = []
    if has_event(events, ["UNDRESS_PATIENT"]):
        t = first_event_time(events, ["UNDRESS_PATIENT"])
        e_actions.append(_action_entry("Undress patient for examination", "Completed", t))
        report["abcde_breakdown"]["E_Exposure"]["status"] = "Passed"
    else:
        e_actions.append(_action_entry(
            "Undress patient for examination", "Missed",
            note="Patient must be exposed to allow full head-to-toe assessment.",
            points_deducted=POINTS["MISSING_UNDRESS"]
        ))
        report["abcde_breakdown"]["E_Exposure"]["points_deducted"] = POINTS["MISSING_UNDRESS"]
        report["feedback"].append("[E] Patient was never undressed for examination!")
        deduct(report, POINTS["MISSING_UNDRESS"], "completeness")

    report["abcde_detail"]["E_Exposure"]["actions"] = e_actions

    # ------------------------------------------------------------------
    # Further Diagnostics (post-ABCDE)
    # ------------------------------------------------------------------
    bga_time = _first_time_action_or_delegate(events, ["BLOOD_GAS_ANALYSIS"])
    if bga_time is None:
        report["further_diagnostics"]["BGA"]["status"] = "Missed"
        report["further_diagnostics"]["BGA"]["points_deducted"] = POINTS["MISSING_BGA"]
        report["feedback"].append(
            "[Diagnostics] Blood gas analysis (BGA) was never performed. "
            "(Not required in every scenario — doctor to confirm applicability.)"
        )
        deduct(report, POINTS["MISSING_BGA"], "completeness")
    elif bga_time > BGA_TIME_LIMIT:
        report["further_diagnostics"]["BGA"]["status"] = "Late"
        report["further_diagnostics"]["BGA"]["points_deducted"] = POINTS["LATE_BGA"]
        report["feedback"].append(
            f"[Diagnostics] BGA performed late at {bga_time}s (target < {BGA_TIME_LIMIT}s)."
        )
        deduct(report, POINTS["LATE_BGA"], "timing")
    else:
        report["further_diagnostics"]["BGA"]["status"] = "Passed"

    fast_time = _first_time_action_or_delegate(events, ["ULTRASOUND_FAST"])
    if fast_time is None:
        report["further_diagnostics"]["FAST"]["status"] = "Missed"
        report["further_diagnostics"]["FAST"]["points_deducted"] = POINTS["MISSING_FAST"]
        report["feedback"].append(
            "[Diagnostics] FAST ultrasound was never performed. "
            "(Not required in every scenario — doctor to confirm applicability.)"
        )
        deduct(report, POINTS["MISSING_FAST"], "completeness")
    elif fast_time > FAST_TIME_LIMIT:
        report["further_diagnostics"]["FAST"]["status"] = "Late"
        report["further_diagnostics"]["FAST"]["points_deducted"] = POINTS["LATE_FAST"]
        report["feedback"].append(
            f"[Diagnostics] FAST ultrasound performed late at {fast_time}s (target < {FAST_TIME_LIMIT}s)."
        )
        deduct(report, POINTS["LATE_FAST"], "timing")
    else:
        report["further_diagnostics"]["FAST"]["status"] = "Passed"

    # ------------------------------------------------------------------
    # Step 4: Shock position without clinical indication
    # ------------------------------------------------------------------
    shock_indication_time = first_event_time(events, ["RECAP_TIME", "CHECK_PULSE"])
    shock_position_events = [
        e for e in events
        if e.get("action_code") == "REPOSITION"
        and e.get("phase") == "Start"
        and "schocklage" in e.get("details", "").lower()
    ]
    if shock_position_events:
        earliest_shock_position = min(e.get("sim_time_seconds", 0) for e in shock_position_events)
        if shock_indication_time is None or earliest_shock_position < shock_indication_time:
            report["critical_errors"].append("SHOCK_POSITION_WITHOUT_INDICATION")
            report["feedback"].append(
                f"CRITICAL ERROR: Patient placed in shock position at {earliest_shock_position}s "
                "without prior clinical indication (pulse/recap-time not checked first)!"
            )
            deduct(report, POINTS["SHOCK_POSITION_WITHOUT_INDICATION"], "critical_errors")

    # ------------------------------------------------------------------
    # Critical Errors (Rule 24)
    # ------------------------------------------------------------------
    admin_med_events = []
    intubation_events = [e for e in events if e.get("action_code") == "INTUBATION"]

    for e in events:
        if e.get("action_code") == "MEDICATION":
            details = e.get("details", "").strip()
            details_lower = details.lower()
            if details_lower.startswith("(vorbereiten)"):
                continue
            admin_med_events.append((e, details_lower))

            if "adrenalin" in details_lower or "noradrenalin" in details_lower:
                report["critical_errors"].append("WRONG_MED_CATECHOLAMINE")
                report["feedback"].append(
                    "CRITICAL ERROR: Adrenalin/Noradrenalin cannot be given on the normal ward! "
                    f"(Event at {e.get('sim_time', e.get('sim_time_seconds'))})"
                )
                deduct(report, POINTS["CATECHOLAMINE_ON_WARD"], "critical_errors")

            elif "ketamin" in details_lower:
                report["critical_errors"].append("UNINDICATED_ANESTHESIA_INDUCTION")
                report["feedback"].append(
                    "CRITICAL ERROR: Ketamine (anaesthesia induction) given without indication on the ward! "
                    f"(Event at {e.get('sim_time', e.get('sim_time_seconds'))})"
                )
                deduct(report, POINTS["UNINDICATED_ANESTHESIA_INDUCTION"], "critical_errors")

    if intubation_events:
        capnography_codes = ["CAPNOGRAPHY", "CAPNOGRAPHY_APPLY", "CO2_CHECK"]
        if not has_event(events, capnography_codes):
            report["critical_errors"].append("INTUBATION_WITHOUT_CAPNOGRAPHY")
            report["feedback"].append(
                "CRITICAL ERROR: Intubation performed without capnography verification! "
                "(ERC 2025 ALS: waveform capnography is mandatory after intubation.)"
            )
            deduct(report, POINTS["INTUBATION_WITHOUT_CAPNOGRAPHY"], "critical_errors")

        airway_check_time = first_event_time(events, ["CHECK_AIRWAY"])
        intubation_time = min(e.get("sim_time_seconds", 0) for e in intubation_events)
        if airway_check_time is None or intubation_time < airway_check_time:
            report["critical_errors"].append("INTUBATION_WITHOUT_AIRWAY_CHECK")
            report["feedback"].append(
                "CRITICAL ERROR: Intubation performed before (or without) explicit airway check! "
                "(Doctor review: must check airway before intubation.)"
            )
            deduct(report, POINTS["INTUBATION_WITHOUT_AIRWAY_CHECK"], "critical_errors")

    if vitals:
        chest_pain_scenario = any(
            kw in str(metadata).lower() for kw in ("angina", "chest pain", "brustschmerz")
        )
        already_flagged_o2 = False
        for e in events:
            if e.get("action_code") in ("OXYGEN_APPLY", "DELEGATE_OXYGEN_APPLY"):
                vital = closest_vital(vitals, e.get("sim_time_seconds", 0))
                spo2 = vital.get("spo2_percent") if vital else None
                if spo2 is not None:
                    if spo2 > 96 and not already_flagged_o2:
                        report["critical_errors"].append("OXYGEN_WITHOUT_INDICATION")
                        report["feedback"].append(
                            f"ERROR: Oxygen given at {e.get('sim_time')} while SpO2 was {spo2}% "
                            f"(> 96%, ERC 2025: no indication for supplemental O2). "
                            "Point deduction applied (NOT an automatic fail)."
                        )
                        deduct(report, POINTS["OXYGEN_WITHOUT_INDICATION"], "critical_errors")
                        already_flagged_o2 = True
                    elif chest_pain_scenario and spo2 > 90 and not already_flagged_o2:
                        report["critical_errors"].append("OXYGEN_CHEST_PAIN_WITHOUT_INDICATION")
                        report["feedback"].append(
                            f"ERROR: Oxygen given to a chest pain patient at SpO2 {spo2}% "
                            f"(> 90% — ERC 2025 ACS guidance contra-indicates O2 above 90%)."
                        )
                        deduct(report, POINTS["OXYGEN_CHEST_PAIN_WITHOUT_INDICATION"], "critical_errors")
                        already_flagged_o2 = True

        if vitals:
            critical_spo2 = any(
                v.get("spo2_percent") is not None and v.get("spo2_percent") < 90 for v in vitals
            )
            if critical_spo2 and not _has_action_or_delegate(events, ["OXYGEN_APPLY"]):
                report["critical_errors"].append("SKIPPED_OXYGEN_CRITICAL_PATIENT")
                report["feedback"].append(
                    "CRITICAL ERROR: Patient's SpO2 dropped below 90% but oxygen was never administered! "
                    "(ERC 2025: hypoxaemia must be corrected immediately.)"
                )
                deduct(report, POINTS["SKIPPED_OXYGEN_CRITICAL_PATIENT"], "critical_errors")

            unresponsive = any(v.get("gcs") is not None and v.get("gcs") <= 8 for v in vitals)
            very_low_hr = any(v.get("heart_rate") is not None and v.get("heart_rate") < 30 for v in vitals)
            apnea = any(v.get("respiratory_rate") is not None and v.get("respiratory_rate") == 0 for v in vitals)
            if (very_low_hr or apnea) and not has_event(events, ["CPR"]):
                report["critical_errors"].append("MISSED_CPR_INDICATION")
                report["feedback"].append(
                    "CRITICAL ERROR: Patient had HR < 30 / apnea but CPR was never started! "
                    "(ERC 2025 Adult BLS: start CPR immediately for cardiac arrest.)"
                )
                deduct(report, POINTS["MISSED_CPR_INDICATION"], "critical_errors")

    decision = str(metadata.get("Entscheidung", "")).lower()
    if "pci" in decision or "koronarangiographie" in decision:
        report["critical_errors"].append("WRONG_DECISION_PCI")
        report["feedback"].append(
            f"CRITICAL ERROR: Decision recorded as '{metadata.get('Entscheidung')}' — "
            "PCI/coronary angiography activated despite suspected postoperative bleeding!"
        )
        deduct(report, POINTS["WRONG_DECISION_PCI"], "critical_errors")

    # ------------------------------------------------------------------
    # Order / Dependency Checks
    # ------------------------------------------------------------------
    first_monitor_time = _first_time_action_or_delegate(events, list(MONITORING_SIGNALS.keys()))
    catecholamine_admins = [
        (e, d) for e, d in admin_med_events if "adrenalin" in d or "noradrenalin" in d
    ]
    if catecholamine_admins:
        earliest_admin = min(e.get("sim_time_seconds", 0) for e, _ in catecholamine_admins)
        if first_monitor_time is None or earliest_admin < first_monitor_time:
            report["feedback"].append(
                f"[Order] Adrenalin/Noradrenalin given at {earliest_admin}s before monitoring "
                + (f"(monitoring at {first_monitor_time}s)." if first_monitor_time else "(no monitoring applied).")
            )
            deduct(report, POINTS["ORDER_ADRENALINE_BEFORE_MONITORING"], "order")

    initial_assessment_time = first_event_time(events, ["CHECK_AIRWAY", "CHECK_BREATHING", "CHECK_PULSE"])
    if admin_med_events:
        earliest_med = min(e.get("sim_time_seconds", 0) for e, _ in admin_med_events)
        if initial_assessment_time is None or earliest_med < initial_assessment_time:
            report["feedback"].append(
                f"[Order] Medication given at {earliest_med}s before the initial ABCDE assessment."
            )
            deduct(report, POINTS["ORDER_MEDICATION_BEFORE_ASSESSMENT"], "order")

    infusion_starts = [
        e for e in events if e.get("action_code") == "INFUSION" and e.get("phase") == "Start"
    ]
    infusion_prepped = any(
        e.get("details", "").strip().lower().startswith("(vorbereiten)") for e in infusion_starts
    )
    infusion_administered = any(
        not e.get("details", "").strip().lower().startswith("(vorbereiten)") for e in infusion_starts
    )
    if infusion_prepped and not infusion_administered:
        report["feedback"].append(
            "[Order] Infusion was prepared but never actually administered to the patient."
        )
        deduct(report, POINTS["ORDER_INFUSION_PREPARED_NOT_ADMINISTERED"], "order")

    fast_order_time = _first_time_action_or_delegate(events, ["ULTRASOUND_FAST"])
    palpation_time = first_event_time(events, ["PALPATION"])
    if fast_order_time is not None and palpation_time is not None and fast_order_time < palpation_time:
        report["feedback"].append(
            f"[Order] FAST ultrasound ordered at {fast_order_time}s before physical exam "
            f"(palpation at {palpation_time}s) — palpation should come first."
        )
        deduct(report, POINTS["ORDER_FAST_BEFORE_PALPATION"], "order")

    breathing_time = first_event_time(events, ["CHECK_BREATHING"])
    pulse_time = first_event_time(events, ["CHECK_PULSE"])
    earlier_action = None
    if pulse_time is not None and (breathing_time is None or pulse_time < breathing_time):
        earlier_action = ("pulse check", pulse_time)
    if palpation_time is not None and (breathing_time is None or palpation_time < breathing_time):
        if earlier_action is None or palpation_time < earlier_action[1]:
            earlier_action = ("palpation", palpation_time)
    if earlier_action is not None:
        label, t = earlier_action
        report["feedback"].append(
            f"[Order] {label.capitalize()} performed at {t}s before breathing was assessed "
            + (f"(breathing at {breathing_time}s)." if breathing_time else "(breathing never checked).")
        )
        deduct(report, POINTS["ORDER_ASSESSMENT_BEFORE_BREATHING"], "order")

    # ------------------------------------------------------------------
    # Final scoring
    # ------------------------------------------------------------------
    apply_safety_cap(report)
    apply_verdict(report)

    os.makedirs(os.path.dirname(output_report_path), exist_ok=True)
    with open(output_report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=4, ensure_ascii=False)

    print(
        f"Generated report for {os.path.basename(parsed_session_path)} "
        f"with Score: {report['overall_score']} ({report['verdict']})"
    )
    return report


def evaluate_all_sessions(parsed_dir=None, reports_dir=None):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if parsed_dir is None:
        parsed_dir = os.path.abspath(os.path.join(script_dir, "../../data/parsed"))
    if reports_dir is None:
        reports_dir = os.path.abspath(os.path.join(script_dir, "../../data/reports"))

    os.makedirs(reports_dir, exist_ok=True)
    json_files = [f for f in os.listdir(parsed_dir) if f.endswith(".json")]

    if not json_files:
        print("⚠️  No JSON files found. Is Person A finished with the parser?")
        return

    for json_file in json_files:
        input_path = os.path.join(parsed_dir, json_file)
        output_path = os.path.join(reports_dir, json_file.replace(".json", "_report.json"))
        try:
            evaluate_session(input_path, output_path)
        except Exception as ex:
            print(f"❌ Failed to evaluate {json_file}: {ex}")


if __name__ == "__main__":
    evaluate_all_sessions()
