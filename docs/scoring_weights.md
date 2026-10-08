# VR Medical Evaluation — Scoring Configuration & Weights

***Note to Medical Consultant:*** *The current numeric weights and time limits are placeholder values based on initial documentation ("Ablauf_Notfall auf Normalstation_NBA.docx"). Please review, adjust, and validate these rules so they correctly reflect real-world medical expectations.*

## 1. Time Limits for Critical Actions
These limits dictate when an action triggers a "Timing Deduction".

| Action | Required Time Limit | Notes |
|--------|----------------------|-------|
| **Physician / Staff Contact** | < 10 min (600s) | Step 5 |
| **GCS / Neuro Check** | < 5 min (300s) | Step 6 |
| **Full Monitoring (BP, ECG, SpO2, Temp)** | < 10 min (600s) | All 4 required (Step 7) |
| **Venous Access (PVK)** | < 20 min (1200s) | Step 10 |
| **Infusion Started** | < 22 min (1320s) | Step 11 |
| **Blood Gas Analysis (BGA)** | < 25 min (1500s) | Step 12 |
| **FAST Ultrasound** | < 30 min (1800s) | Step 13 |

---

## 2. Completeness Deductions
These points are deducted if an action is completely missing from the session.

| Missing Action | Point Deduction |
|----------------|-----------------|
| Missing Airway Check (A) | -10 |
| Missing Breathing Check (B) | -10 |
| Missing Pulse Check (C) | -10 |
| Missing Capillary Refill (ReCap) | -5 |
| Missing Physician Contact | -10 |
| Missing Venous Access | -10 |
| Missing Infusion | -10 |
| Missing Blood Gas Analysis | -10 |
| Missing FAST Ultrasound | -10 |
| Missing GCS / Neuro Check (D) | -10 |
| Missing Blood Sugar *(If GCS < 15)* | -10 |
| Missing Patient Undressing (E) | -10 |
| No Monitoring Applied at all | -15 |

---

## 3. Order / Procedural Violations
These points are deducted when a student performs the right action but in the wrong clinical sequence.

| Violation | Point Deduction | Rationale |
|-----------|-----------------|-----------|
| Adrenalin/Noradrenalin before Monitoring | -10 | Medication given before BP/ECG control |
| Medication given before ABC Assessment | -10 | Medication given before initial assessment |
| Infusion prepared but not administered | -5 | Wasted step / delay without application |
| FAST Ultrasound before Palpation | -5 | Palpation should precede apparatus-based checks |
| Palpation / Pulse before Breathing Check | -5 | Breathing check takes higher ABC priority |

---

## 4. Critical Errors (Rule 24 & Indication Violations)
These actions are strictly forbidden or medically unindicated for the specific scenario and location.

| Critical Error | Point Deduction | Notes |
|----------------|-----------------|-------|
| **Wrong Decision: PCI** | -25 | Activating PCI on a bleeding patient |
| **Catecholamines on Ward** | -20 | Adrenalin/Noradrenalin strictly IV in normal ward |
| **Unindicated Anesthesia Induction** | -15 | e.g. Ketamine on ward without indication |
| **Shock Position w/o Indication** | -15 | Legs up without prior Pulse/ReCap check |
| **Oxygen w/o Indication** | -10 | Oxygen administered when SpO2 > 96% |

---

## 5. Pass / Fail & Safety Mechanics

- **Initial Score:** 100 points
- **Current Passing Threshold:** 70 points
- **Safety Cap Mechanism (Target Max: 49 / FAIL)**: 
  If a student completely misses an `A` (Airway) or `B` (Breathing) vital step, OR triggers ANY **Critical Error** (Section 4), their final score is **capped at 49**. This prevents a student who made a fatal error from "passing" simply because they were fast at other steps.
