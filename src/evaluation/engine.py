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
    first_event_time,
    first_event_time_matching,
    has_event,
    closest_vital,
    new_report,
    deduct,
    apply_safety_cap,
    apply_verdict,
)

# Known gaps, not implemented because the log schema can't support them
# reliably (see conversation): 12-lead-ECG-before-shock-workup timing,
# "fixation on wrong diagnosis" detection, emergency-team alerting,
# unnecessary repeat diagnostics, and leaving the patient unattended
# (all Rule 24 items, but need multi-actor presence / NLP the log doesn't give).


def evaluate_session(parsed_session_path, output_report_path):
    """
    Reads a parsed JSON file and applies the ABCDE medical rules
    to generate a scoring report.
    """
    with open(parsed_session_path, 'r', encoding='utf-8') as f:
        session_data = json.load(f)

    # Person A's parser emits two shapes: a bare event list (from .txt logs) or
    # {"metadata", "events", "vital_parameters"} (from .docx logs). Normalize both.
    if isinstance(session_data, list):
        events = session_data
        metadata = {}
        vitals = []
    else:
        events = session_data.get('events', [])
        metadata = session_data.get('metadata', {})
        vitals = session_data.get('vital_parameters', [])

    report = new_report(metadata)

    # --- Coverage Statistics ---
    # Only count Start/Info phase to avoid double-counting Stop/Cancel phases for same action
    start_events = [e for e in events if e.get("phase", "Start") in ("Start", "Info")]
    total_actions = len(start_events)
    unknown_events = [e for e in start_events if "UNKNOWN" in e.get("action_code", "")]
    unknown_actions = len(unknown_events)
    evaluated_actions = total_actions - unknown_actions
    
    report["coverage"]["total_actions"] = total_actions
    report["coverage"]["evaluated_actions"] = evaluated_actions
    report["coverage"]["unknown_actions"] = unknown_actions
    
    unique_unknowns = sorted(list(set(e.get("action_raw", "") for e in unknown_events)))
    report["coverage"]["unknown_action_list"] = unique_unknowns
    if total_actions > 0:
        report["coverage"]["coverage_percent"] = round((evaluated_actions / total_actions) * 100, 1)
    else:
        report["coverage"]["coverage_percent"] = 0.0

    # --- A: Airway ---
    if has_event(events, ["CHECK_AIRWAY"]):
        report["abcde_breakdown"]["A_Airway"]["status"] = "Passed"
    else:
        report["abcde_breakdown"]["A_Airway"]["points_deducted"] = POINTS["MISSING_AIRWAY"]
        report["feedback"].append("[A] Airway was not checked!")
        deduct(report, POINTS["MISSING_AIRWAY"], "completeness")

    # --- B: Breathing ---
    if has_event(events, ["CHECK_BREATHING"]):
        report["abcde_breakdown"]["B_Breathing"]["status"] = "Passed"
    else:
        report["abcde_breakdown"]["B_Breathing"]["points_deducted"] = POINTS["MISSING_BREATHING"]
        report["feedback"].append("[B] Breathing was not checked!")
        deduct(report, POINTS["MISSING_BREATHING"], "completeness")

    # --- C: Circulation ---
    # Bundles: pulse + recap time (Step 4 shock recognition), physician contact (Step 5),
    # full monitoring panel (Step 7), venous access (Step 10), infusion (Step 11),
    # blood gas analysis (Step 12), FAST ultrasound (Step 13).
    c_points_deducted = 0
    c_passed = True

    if not has_event(events, ["CHECK_PULSE"]):
        c_passed = False
        c_points_deducted += POINTS["MISSING_PULSE"]
        report["feedback"].append("[C] Pulse was not checked!")
        deduct(report, POINTS["MISSING_PULSE"], "completeness")

    # Step 4: shock recognition relies on recap (capillary refill) time, alongside pulse.
    if not has_event(events, ["RECAP_TIME"]):
        c_passed = False
        c_points_deducted += POINTS["MISSING_RECAP_CHECK"]
        report["feedback"].append("[C] Capillary refill / recap time was never assessed!")
        deduct(report, POINTS["MISSING_RECAP_CHECK"], "completeness")

    staff_time = first_event_time_matching(
        events, lambda e: e.get("action_code") == "DELEGATE_NPC" and "medizin" in e.get("details", "").lower()
    )
    if staff_time is None:
        c_passed = False
        c_points_deducted += POINTS["MISSING_STAFF_CONTACT"]
        report["feedback"].append("[C] Physician/medical staff was never contacted!")
        deduct(report, POINTS["MISSING_STAFF_CONTACT"], "completeness")
    elif staff_time > STAFF_CONTACT_TIME_LIMIT:
        c_passed = False
        c_points_deducted += POINTS["LATE_STAFF_CONTACT"]
        report["feedback"].append(
            f"[C] Physician contacted late at {staff_time}s (target < {STAFF_CONTACT_TIME_LIMIT}s)."
        )
        deduct(report, POINTS["LATE_STAFF_CONTACT"], "timing")

    missing_signals = []
    late_signals = []
    any_monitoring_done = False
    for code, label in MONITORING_SIGNALS.items():
        t = first_event_time(events, [code])
        if t is None:
            missing_signals.append(label)
        else:
            any_monitoring_done = True
            if t > MONITORING_TIME_LIMIT:
                late_signals.append((label, t))

    if not any_monitoring_done:
        c_passed = False
        c_points_deducted += POINTS["MISSING_ALL_MONITORING"]
        report["feedback"].append("[C] Critical: No monitoring equipment (BP/ECG/pulse ox/temperature) applied!")
        report["critical_errors"].append("MISSING_STEP_MONITORING")
        deduct(report, POINTS["MISSING_ALL_MONITORING"], "completeness")
    else:
        if missing_signals:
            c_passed = False
            amount = POINTS["MONITORING_SIGNAL_ISSUE"] * len(missing_signals)
            c_points_deducted += amount
            report["feedback"].append(f"[C] Monitoring incomplete, never applied: {', '.join(missing_signals)}.")
            deduct(report, amount, "completeness")
        for label, t in late_signals:
            c_passed = False
            c_points_deducted += POINTS["MONITORING_SIGNAL_ISSUE"]
            report["feedback"].append(f"[C] {label} applied late at {t}s (target < {MONITORING_TIME_LIMIT}s).")
            deduct(report, POINTS["MONITORING_SIGNAL_ISSUE"], "timing")

    iv_time = first_event_time(events, ["IV_ACCESS"])
    if iv_time is None:
        c_passed = False
        c_points_deducted += POINTS["MISSING_VENOUS_ACCESS"]
        report["feedback"].append("[C] Venous access (PVK) was never established!")
        deduct(report, POINTS["MISSING_VENOUS_ACCESS"], "completeness")
    elif iv_time > VENOUS_ACCESS_TIME_LIMIT:
        c_passed = False
        c_points_deducted += POINTS["LATE_VENOUS_ACCESS"]
        report["feedback"].append(
            f"[C] Venous access established late at {iv_time}s (target < {VENOUS_ACCESS_TIME_LIMIT}s)."
        )
        deduct(report, POINTS["LATE_VENOUS_ACCESS"], "timing")

    infusion_time = first_event_time(events, ["INFUSION"])
    if infusion_time is None:
        c_passed = False
        c_points_deducted += POINTS["MISSING_INFUSION"]
        report["feedback"].append("[C] Infusion was never started!")
        deduct(report, POINTS["MISSING_INFUSION"], "completeness")
    elif infusion_time > INFUSION_TIME_LIMIT:
        c_passed = False
        c_points_deducted += POINTS["LATE_INFUSION"]
        report["feedback"].append(
            f"[C] Infusion started late at {infusion_time}s (target < {INFUSION_TIME_LIMIT}s)."
        )
        deduct(report, POINTS["LATE_INFUSION"], "timing")

    bga_time = first_event_time(events, ["BLOOD_GAS_ANALYSIS"])
    if bga_time is None:
        c_passed = False
        c_points_deducted += POINTS["MISSING_BGA"]
        report["feedback"].append("[C] Blood gas analysis (BGA) was never performed!")
        deduct(report, POINTS["MISSING_BGA"], "completeness")
    elif bga_time > BGA_TIME_LIMIT:
        c_passed = False
        c_points_deducted += POINTS["LATE_BGA"]
        report["feedback"].append(
            f"[C] Blood gas analysis performed late at {bga_time}s (target < {BGA_TIME_LIMIT}s)."
        )
        deduct(report, POINTS["LATE_BGA"], "timing")

    fast_time = first_event_time(events, ["ULTRASOUND_FAST"])
    if fast_time is None:
        c_passed = False
        c_points_deducted += POINTS["MISSING_FAST"]
        report["feedback"].append("[C] FAST ultrasound was never performed!")
        deduct(report, POINTS["MISSING_FAST"], "completeness")
    elif fast_time > FAST_TIME_LIMIT:
        c_passed = False
        c_points_deducted += POINTS["LATE_FAST"]
        report["feedback"].append(
            f"[C] FAST ultrasound performed late at {fast_time}s (target < {FAST_TIME_LIMIT}s)."
        )
        deduct(report, POINTS["LATE_FAST"], "timing")

    report["abcde_breakdown"]["C_Circulation"]["status"] = "Passed" if c_passed else "Missed"
    report["abcde_breakdown"]["C_Circulation"]["points_deducted"] = c_points_deducted

    # --- D: Disability ---
    # Step 6: GCS/neuro status within 5 min; blood sugar required if consciousness is altered.
    d_points_deducted = 0
    d_passed = True

    gcs_time = first_event_time(events, ["GCS_CHECK"])
    if gcs_time is None:
        d_passed = False
        d_points_deducted += POINTS["MISSING_GCS"]
        report["feedback"].append("[D] GCS / neurological status was never assessed!")
        deduct(report, POINTS["MISSING_GCS"], "completeness")
    elif gcs_time > GCS_TIME_LIMIT:
        d_passed = False
        d_points_deducted += POINTS["LATE_GCS"]
        report["feedback"].append(f"[D] GCS assessed late at {gcs_time}s (target < {GCS_TIME_LIMIT}s).")
        deduct(report, POINTS["LATE_GCS"], "timing")

    # Only checkable when vital_parameters are available (docx-derived sessions).
    if vitals:
        consciousness_altered = any(v.get("gcs") is not None and v.get("gcs") < 15 for v in vitals)
        if consciousness_altered and not has_event(events, ["BLOOD_SUGAR"]):
            d_passed = False
            d_points_deducted += POINTS["MISSING_BLOOD_SUGAR_CHECK"]
            report["feedback"].append(
                "[D] Consciousness was altered (GCS < 15) but blood sugar was never measured!"
            )
            deduct(report, POINTS["MISSING_BLOOD_SUGAR_CHECK"], "completeness")

    report["abcde_breakdown"]["D_Disability"]["status"] = "Passed" if d_passed else "Missed"
    report["abcde_breakdown"]["D_Disability"]["points_deducted"] = d_points_deducted

    # --- E: Exposure ---
    if has_event(events, ["UNDRESS_PATIENT"]):
        report["abcde_breakdown"]["E_Exposure"]["status"] = "Passed"
    else:
        report["abcde_breakdown"]["E_Exposure"]["points_deducted"] = POINTS["MISSING_UNDRESS"]
        report["feedback"].append("[E] Patient was never undressed for examination!")
        deduct(report, POINTS["MISSING_UNDRESS"], "completeness")

    # --- Step 4: shock recognition safety check ---
    # Doc's explicit "Fehlerkriterium": putting the patient in shock position
    # (REPOSITION with "Schocklage" in the details) is only justified once a
    # clinical sign of shock -- pulse or recap time -- has actually been checked.
    shock_indication_time = first_event_time(events, ["RECAP_TIME", "CHECK_PULSE"])
    shock_position_events = [
        e for e in events
        if e.get("action_code") == "REPOSITION"
        and e.get("phase") == "Start"
        and "schocklage" in e.get("details", "").lower()
    ]
    if shock_position_events:
        earliest_shock_position_time = min(e.get("sim_time_seconds", 0) for e in shock_position_events)
        if shock_indication_time is None or earliest_shock_position_time < shock_indication_time:
            report["critical_errors"].append("SHOCK_POSITION_WITHOUT_INDICATION")
            report["feedback"].append(
                f"CRITICAL ERROR: Patient placed in shock position at {earliest_shock_position_time}s without a "
                "prior clinical indication (pulse/recap-time was not checked first)!"
            )
            deduct(report, POINTS["SHOCK_POSITION_WITHOUT_INDICATION"], "critical_errors")

    # --- Critical errors (Rule 24) ---

    # Non-prep MEDICATION admin events, reused by both the catecholamine critical-error
    # check and the ADRENALINE_BEFORE_MONITORING order check below.
    admin_med_events = []
    for e in events:
        if e.get("action_code") == "MEDICATION":
            details = e.get("details", "").strip()
            details_lower = details.lower()
            # "(Vorbereiten)" means the drug was only prepared, not given to the patient.
            # Only actual administration counts as the Rule 24 violation.
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
                    "CRITICAL ERROR: Ketamine (anesthesia induction) given without indication on the normal ward! "
                    f"(Event at {e.get('sim_time', e.get('sim_time_seconds'))})"
                )
                deduct(report, POINTS["UNINDICATED_ANESTHESIA_INDUCTION"], "critical_errors")

    if vitals:
        for e in events:
            if e.get("action_code") == "OXYGEN_APPLY":
                vital = closest_vital(vitals, e.get("sim_time_seconds", 0))
                spo2 = vital.get("spo2_percent") if vital else None
                if spo2 is not None and spo2 > 96:
                    report["critical_errors"].append("OXYGEN_WITHOUT_INDICATION")
                    report["feedback"].append(
                        f"ERROR: Oxygen given at {e.get('sim_time')} while SpO2 was {spo2}% (>96%, no indication)."
                    )
                    deduct(report, POINTS["OXYGEN_WITHOUT_INDICATION"], "critical_errors")

    decision = str(metadata.get("Entscheidung", "")).lower()
    if "pci" in decision or "koronarangiographie" in decision:
        report["critical_errors"].append("WRONG_DECISION_PCI")
        report["feedback"].append(
            f"CRITICAL ERROR: Decision recorded as '{metadata.get('Entscheidung')}' -- PCI/coronary "
            "angiography was activated despite a suspected postoperative bleeding!"
        )
        deduct(report, POINTS["WRONG_DECISION_PCI"], "critical_errors")

    # --- Order / dependency checks ("Reihenfolge / Abhaengigkeiten") ---
    # Each is a one-time yes/no check: did this happen out of the expected order at all.

    first_monitor_time = first_event_time(events, list(MONITORING_SIGNALS.keys()))
    catecholamine_admins = [
        (e, d) for e, d in admin_med_events if "adrenalin" in d or "noradrenalin" in d
    ]
    if catecholamine_admins:
        earliest_admin_time = min(e.get("sim_time_seconds", 0) for e, _ in catecholamine_admins)
        if first_monitor_time is None or earliest_admin_time < first_monitor_time:
            report["feedback"].append(
                f"[Order] Adrenalin/Noradrenalin given at {earliest_admin_time}s before any monitoring "
                f"(BP/ECG/pulse ox/temp) was applied"
                + (f" (monitoring started at {first_monitor_time}s)." if first_monitor_time is not None else " (monitoring was never applied).")
            )
            deduct(report, POINTS["ORDER_ADRENALINE_BEFORE_MONITORING"], "order")

    initial_assessment_time = first_event_time(events, ["CHECK_AIRWAY", "CHECK_BREATHING", "CHECK_PULSE"])
    if admin_med_events:
        earliest_med_time = min(e.get("sim_time_seconds", 0) for e, _ in admin_med_events)
        if initial_assessment_time is None or earliest_med_time < initial_assessment_time:
            report["feedback"].append(
                f"[Order] Medication given at {earliest_med_time}s before the initial ABCDE assessment "
                "(airway/breathing/pulse check) was performed."
            )
            deduct(report, POINTS["ORDER_MEDICATION_BEFORE_ASSESSMENT"], "order")

    infusion_starts = [
        e for e in events if e.get("action_code") == "INFUSION" and e.get("phase") == "Start"
    ]
    infusion_prepped = any(e.get("details", "").strip().lower().startswith("(vorbereiten)") for e in infusion_starts)
    infusion_administered = any(
        not e.get("details", "").strip().lower().startswith("(vorbereiten)") for e in infusion_starts
    )
    if infusion_prepped and not infusion_administered:
        report["feedback"].append(
            "[Order] Infusion was prepared but never actually administered to the patient."
        )
        deduct(report, POINTS["ORDER_INFUSION_PREPARED_NOT_ADMINISTERED"], "order")

    # FAST ultrasound should follow the physical exam (palpation), not precede it.
    fast_check_time = first_event_time(events, ["ULTRASOUND_FAST"])
    palpation_time = first_event_time(events, ["PALPATION"])
    if fast_check_time is not None and palpation_time is not None and fast_check_time < palpation_time:
        report["feedback"].append(
            f"[Order] FAST ultrasound performed at {fast_check_time}s before the physical exam "
            f"(palpation, at {palpation_time}s) -- palpation should come first."
        )
        deduct(report, POINTS["ORDER_FAST_BEFORE_PALPATION"], "order")

    # Breathing should be assessed before pulse is checked or palpation is done.
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
            + (f"(breathing checked at {breathing_time}s)." if breathing_time is not None else "(breathing was never checked).")
        )
        deduct(report, POINTS["ORDER_ASSESSMENT_BEFORE_BREATHING"], "order")

    apply_safety_cap(report)
    apply_verdict(report)

    # Save the output report
    os.makedirs(os.path.dirname(output_report_path), exist_ok=True)
    with open(output_report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=4, ensure_ascii=False)

    print(
        f"Generated report for {os.path.basename(parsed_session_path)} "
        f"with Score: {report['overall_score']} ({report['verdict']})"
    )
    return report


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parsed_dir = os.path.abspath(os.path.join(script_dir, "../../data/parsed"))
    reports_dir = os.path.abspath(os.path.join(script_dir, "../../data/reports"))

    json_files = [f for f in os.listdir(parsed_dir) if f.endswith(".json")]

    if not json_files:
        print("⚠️ No JSON files found. Is Person A finished with the parser?")

    for json_file in json_files:
        input_path = os.path.join(parsed_dir, json_file)
        output_path = os.path.join(reports_dir, json_file.replace(".json", "_report.json"))
        try:
            evaluate_session(input_path, output_path)
        except Exception as ex:
            print(f"❌ Failed to evaluate {json_file}: {ex}")
