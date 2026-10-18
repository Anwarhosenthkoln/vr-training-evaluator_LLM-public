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
# The parser maps "NPC beauftragen → Ultraschall" to DELEGATE_ULTRASOUND_FAST etc.
# For clinical completeness either form counts (Step 19 explicitly wants delegation).
# ---------------------------------------------------------------------------
def _has_action_or_delegate(events, base_codes):
    """Return True if any event matches base_codes OR DELEGATE_<base_code>."""
    delegate_codes = [f"DELEGATE_{c}" for c in base_codes]
    return has_event(events, base_codes + delegate_codes)


def _first_time_action_or_delegate(events, base_codes):
    """Earliest time the action was done directly or by delegation."""
    delegate_codes = [f"DELEGATE_{c}" for c in base_codes]
    return first_event_time(events, base_codes + delegate_codes)


def evaluate_session(parsed_session_path, output_report_path):
    """
    Reads a parsed JSON file and applies the ABCDE medical rules to generate
    a scoring report.

    Rules updated October 2026 per VR_Scoring_Weights_Doctor_Review_NBA.pdf
    and ERC Guidelines 2025.
    """
    with open(parsed_session_path, 'r', encoding='utf-8') as f:
        session_data = json.load(f)

    # Person A's parser emits two shapes: a bare list (from .txt logs) or
    # {"metadata", "events", "vital_parameters"} (from .docx logs).
    if isinstance(session_data, list):
        events = session_data
        metadata = {}
        vitals = []
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
    # FIX: Doctor review (→ not acceptable) reversed the previous "patient speaks
    # = airway clear" shortcut. An explicit airway check is now always required.
    # ERC 2025 Adult BLS: open the airway, look/listen/feel.
    if has_event(events, ["CHECK_AIRWAY"]):
        report["abcde_breakdown"]["A_Airway"]["status"] = "Passed"
    else:
        report["abcde_breakdown"]["A_Airway"]["points_deducted"] = POINTS["MISSING_AIRWAY"]
        report["feedback"].append("[A] Airway was not explicitly checked!")
        deduct(report, POINTS["MISSING_AIRWAY"], "completeness")

    # ------------------------------------------------------------------
    # B: Breathing
    # ------------------------------------------------------------------
    # Doctor added: auscultation of the lungs as a separate B sub-check.
    b_passed = True
    b_points = 0

    if has_event(events, ["CHECK_BREATHING"]):
        pass  # basic breathing assessment done
    else:
        b_passed = False
        b_points += POINTS["MISSING_BREATHING"]
        report["feedback"].append("[B] Breathing was not assessed!")
        deduct(report, POINTS["MISSING_BREATHING"], "completeness")

    if not has_event(events, ["AUSCULTATION"]):
        b_passed = False
        b_points += POINTS["MISSING_AUSCULTATION"]
        report["feedback"].append("[B] Auscultation of the lungs was not performed!")
        deduct(report, POINTS["MISSING_AUSCULTATION"], "completeness")

    report["abcde_breakdown"]["B_Breathing"]["status"] = "Passed" if b_passed else "Missed"
    report["abcde_breakdown"]["B_Breathing"]["points_deducted"] = b_points

    # ------------------------------------------------------------------
    # C: Circulation
    # Covers pulse, capillary refill, physician contact, monitoring panel,
    # venous access, and infusion.
    # FIX: BGA and FAST are moved to "Further Diagnostics" (post-ABCDE) per doctor.
    # FIX: Delegated tasks (DELEGATE_*) now count as done.
    # ------------------------------------------------------------------
    c_points_deducted = 0
    c_passed = True

    if not has_event(events, ["CHECK_PULSE"]):
        c_passed = False
        c_points_deducted += POINTS["MISSING_PULSE"]
        report["feedback"].append("[C] Pulse was not checked!")
        deduct(report, POINTS["MISSING_PULSE"], "completeness")

    if not has_event(events, ["RECAP_TIME"]):
        c_passed = False
        c_points_deducted += POINTS["MISSING_RECAP_CHECK"]
        report["feedback"].append("[C] Capillary refill / recap time was never assessed!")
        deduct(report, POINTS["MISSING_RECAP_CHECK"], "completeness")

    # Physician contact: check for any delegation to Arzt/medical staff.
    # The parser stores "NPC beauftragen" → details contain "medizin" / "arzt".
    staff_time = first_event_time_matching(
        events,
        lambda e: e.get("action_code") in ("DELEGATE_NPC", "CALL_PHYSICIAN")
        and any(kw in e.get("details", "").lower() for kw in ("medizin", "arzt", "physician", "doctor"))
    )
    if staff_time is None:
        c_passed = False
        c_points_deducted += POINTS["MISSING_STAFF_CONTACT"]
        report["feedback"].append("[C] Physician / medical staff was never contacted!")
        deduct(report, POINTS["MISSING_STAFF_CONTACT"], "completeness")
    elif staff_time > STAFF_CONTACT_TIME_LIMIT:
        c_passed = False
        c_points_deducted += POINTS["LATE_STAFF_CONTACT"]
        report["feedback"].append(
            f"[C] Physician contacted late at {staff_time}s (target < {STAFF_CONTACT_TIME_LIMIT}s / 2 min)."
        )
        deduct(report, POINTS["LATE_STAFF_CONTACT"], "timing")

    # Monitoring panel (all four required within 5 min per updated limit).
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

    if not any_monitoring_done:
        c_passed = False
        c_points_deducted += POINTS["MISSING_ALL_MONITORING"]
        report["feedback"].append("[C] Critical: No monitoring equipment (BP/ECG/SpO2/temperature) applied!")
        report["critical_errors"].append("MISSING_STEP_MONITORING")
        deduct(report, POINTS["MISSING_ALL_MONITORING"], "completeness")
    else:
        if missing_signals:
            c_passed = False
            amount = POINTS["MONITORING_SIGNAL_ISSUE"] * len(missing_signals)
            c_points_deducted += amount
            report["feedback"].append(
                f"[C] Monitoring incomplete, never applied: {', '.join(missing_signals)}."
            )
            deduct(report, amount, "completeness")
        for label, t in late_signals:
            c_passed = False
            c_points_deducted += POINTS["MONITORING_SIGNAL_ISSUE"]
            report["feedback"].append(
                f"[C] {label} applied late at {t}s (target < {MONITORING_TIME_LIMIT}s)."
            )
            deduct(report, POINTS["MONITORING_SIGNAL_ISSUE"], "timing")

    # IV access (student or delegated to nurse).
    iv_time = _first_time_action_or_delegate(events, ["IV_ACCESS"])
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

    # Infusion (student or delegated).
    infusion_time = _first_time_action_or_delegate(events, ["INFUSION"])
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

    report["abcde_breakdown"]["C_Circulation"]["status"] = "Passed" if c_passed else "Missed"
    report["abcde_breakdown"]["C_Circulation"]["points_deducted"] = c_points_deducted

    # ------------------------------------------------------------------
    # D: Disability
    # FIX: GCS_CHECK and NEURO_EXAM are now both accepted (Step 6 says either).
    # ------------------------------------------------------------------
    d_points_deducted = 0
    d_passed = True

    gcs_time = first_event_time(events, ["GCS_CHECK", "NEURO_EXAM"])
    if gcs_time is None:
        d_passed = False
        d_points_deducted += POINTS["MISSING_GCS"]
        report["feedback"].append("[D] GCS / neurological status was never assessed!")
        deduct(report, POINTS["MISSING_GCS"], "completeness")
    elif gcs_time > GCS_TIME_LIMIT:
        d_passed = False
        d_points_deducted += POINTS["LATE_GCS"]
        report["feedback"].append(
            f"[D] GCS / neuro assessment late at {gcs_time}s (target < {GCS_TIME_LIMIT}s)."
        )
        deduct(report, POINTS["LATE_GCS"], "timing")

    # Blood sugar only required when consciousness is altered (GCS < 15).
    # Doctor note: BGA may contain blood sugar — check both BGA and BLOOD_SUGAR.
    if vitals:
        consciousness_altered = any(
            v.get("gcs") is not None and v.get("gcs") < 15 for v in vitals
        )
        if consciousness_altered and not _has_action_or_delegate(events, ["BLOOD_SUGAR", "BLOOD_GAS_ANALYSIS"]):
            d_passed = False
            d_points_deducted += POINTS["MISSING_BLOOD_SUGAR_CHECK"]
            report["feedback"].append(
                "[D] Consciousness was altered (GCS < 15) but blood sugar was never measured!"
            )
            deduct(report, POINTS["MISSING_BLOOD_SUGAR_CHECK"], "completeness")

    report["abcde_breakdown"]["D_Disability"]["status"] = "Passed" if d_passed else "Missed"
    report["abcde_breakdown"]["D_Disability"]["points_deducted"] = d_points_deducted

    # ------------------------------------------------------------------
    # E: Exposure
    # ------------------------------------------------------------------
    if has_event(events, ["UNDRESS_PATIENT"]):
        report["abcde_breakdown"]["E_Exposure"]["status"] = "Passed"
    else:
        report["abcde_breakdown"]["E_Exposure"]["points_deducted"] = POINTS["MISSING_UNDRESS"]
        report["feedback"].append("[E] Patient was never undressed for examination!")
        deduct(report, POINTS["MISSING_UNDRESS"], "completeness")

    # ------------------------------------------------------------------
    # Further Diagnostics (post-ABCDE)
    # Doctor: BGA and FAST do NOT belong to C; they are further diagnostics.
    # Still scored, but separated from ABCDE breakdown.
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
    # Doctor: also flag shock position when only dyspnoea or angina pectoris
    # is present without prior circulation check.
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

    # Doctor: intubation without capnography is a critical error.
    if intubation_events:
        capnography_codes = ["CAPNOGRAPHY", "CAPNOGRAPHY_APPLY", "CO2_CHECK"]
        if not has_event(events, capnography_codes):
            report["critical_errors"].append("INTUBATION_WITHOUT_CAPNOGRAPHY")
            report["feedback"].append(
                "CRITICAL ERROR: Intubation performed without capnography verification! "
                "(ERC 2025 ALS: waveform capnography is mandatory after intubation.)"
            )
            deduct(report, POINTS["INTUBATION_WITHOUT_CAPNOGRAPHY"], "critical_errors")

        # Doctor: airway must be checked BEFORE intubation.
        airway_check_time = first_event_time(events, ["CHECK_AIRWAY"])
        intubation_time = min(e.get("sim_time_seconds", 0) for e in intubation_events)
        if airway_check_time is None or intubation_time < airway_check_time:
            report["critical_errors"].append("INTUBATION_WITHOUT_AIRWAY_CHECK")
            report["feedback"].append(
                "CRITICAL ERROR: Intubation performed before (or without) explicit airway check! "
                "(Doctor review: must check airway before intubation.)"
            )
            deduct(report, POINTS["INTUBATION_WITHOUT_AIRWAY_CHECK"], "critical_errors")

    # Oxygen without indication checks (NOT safety-cap triggers, only deductions).
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
                        # ERC 2025: do NOT routinely give supplemental O2 if SpO2 > 96%
                        report["critical_errors"].append("OXYGEN_WITHOUT_INDICATION")
                        report["feedback"].append(
                            f"ERROR: Oxygen given at {e.get('sim_time')} while SpO2 was {spo2}% "
                            f"(> 96%, ERC 2025: no indication for supplemental O2). "
                            "Point deduction applied (NOT an automatic fail)."
                        )
                        deduct(report, POINTS["OXYGEN_WITHOUT_INDICATION"], "critical_errors")
                        already_flagged_o2 = True
                    elif chest_pain_scenario and spo2 > 90 and not already_flagged_o2:
                        # ERC 2025: in chest pain / ACS, O2 only if SpO2 < 90%
                        report["critical_errors"].append("OXYGEN_CHEST_PAIN_WITHOUT_INDICATION")
                        report["feedback"].append(
                            f"ERROR: Oxygen given to a chest pain patient at SpO2 {spo2}% "
                            f"(> 90% — ERC 2025 ACS guidance contra-indicates O2 above 90%)."
                        )
                        deduct(report, POINTS["OXYGEN_CHEST_PAIN_WITHOUT_INDICATION"], "critical_errors")
                        already_flagged_o2 = True

        # Doctor: skipping O2 for a critical patient (SpO2 < 90%) is also flagged.
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

        # Doctor: not starting CPR when patient does not breathe or HR < 30.
        unresponsive = any(
            v.get("gcs") is not None and v.get("gcs") <= 8 for v in vitals
        )
        very_low_hr = any(
            v.get("heart_rate") is not None and v.get("heart_rate") < 30 for v in vitals
        )
        apnea = any(
            v.get("respiratory_rate") is not None and v.get("respiratory_rate") == 0 for v in vitals
        )
        if (very_low_hr or apnea) and not has_event(events, ["CPR"]):
            report["critical_errors"].append("MISSED_CPR_INDICATION")
            report["feedback"].append(
                "CRITICAL ERROR: Patient had HR < 30 / apnea but CPR was never started! "
                "(ERC 2025 Adult BLS: start CPR immediately for cardiac arrest.)"
            )
            deduct(report, POINTS["MISSED_CPR_INDICATION"], "critical_errors")

    # Wrong definitive management decision.
    decision = str(metadata.get("Entscheidung", "")).lower()
    if "pci" in decision or "koronarangiographie" in decision:
        report["critical_errors"].append("WRONG_DECISION_PCI")
        report["feedback"].append(
            f"CRITICAL ERROR: Decision recorded as '{metadata.get('Entscheidung')}' — "
            "PCI/coronary angiography activated despite suspected postoperative bleeding!"
        )
        deduct(report, POINTS["WRONG_DECISION_PCI"], "critical_errors")

    # ------------------------------------------------------------------
    # Order / Dependency Checks ("Reihenfolge / Abhängigkeiten")
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

    # FAST before palpation (use delegated time too).
    fast_order_time = _first_time_action_or_delegate(events, ["ULTRASOUND_FAST"])
    palpation_time = first_event_time(events, ["PALPATION"])
    if fast_order_time is not None and palpation_time is not None and fast_order_time < palpation_time:
        report["feedback"].append(
            f"[Order] FAST ultrasound ordered at {fast_order_time}s before physical exam "
            f"(palpation at {palpation_time}s) — palpation should come first."
        )
        deduct(report, POINTS["ORDER_FAST_BEFORE_PALPATION"], "order")

    # Breathing should be assessed before pulse or palpation.
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
    # Apply safety cap and verdict
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
