
import os
from fpdf import FPDF
import json

def create_pdf(path, content):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 10, content)
    pdf.output(path)

base_dir = "tests/samples"
os.makedirs(f"{base_dir}/criminal/guilty", exist_ok=True)
os.makedirs(f"{base_dir}/criminal/acquitted", exist_ok=True)
os.makedirs(f"{base_dir}/civil/plaintiff_won", exist_ok=True)
os.makedirs(f"{base_dir}/civil/plaintiff_lost", exist_ok=True)

test_data = []

# Criminal Guilty
for i in range(1, 6):
    content = f"""
    IN THE COURT OF SESSIONS, NEW DELHI
    CASE NO: CR/{100+i}/2023
    STATE VS JOHN DOE {i}
    
    The accused is charged under Section 379 of IPC for theft of a mobile phone.
    Evidence show fingerprints of the accused on the stolen item.
    The prosecution has proved the case beyond reasonable doubt.
    JUDGMENT: The accused is found GUILTY and sentenced to 2 years imprisonment.
    """
    path = f"{base_dir}/criminal/guilty/case_{i}.pdf"
    create_pdf(path, content)
    test_data.append({
        "path": path,
        "type": "criminal_guilty",
        "expected_verdict": "guilty",
        "expected_appeal": "yes",
        "expected_days": "30"
    })

# Criminal Acquitted
for i in range(1, 6):
    content = f"""
    IN THE COURT OF SESSIONS, MUMBAI
    CASE NO: CR/{200+i}/2023
    STATE VS JANE SMITH {i}
    
    The accused is charged under Section 323 of IPC for assault.
    The witnesses turned hostile and did not support the prosecution story.
    There is no medical evidence to corroborate the injury.
    JUDGMENT: The accused is ACQUITTED of all charges due to lack of evidence.
    """
    path = f"{base_dir}/criminal/acquitted/case_{i}.pdf"
    create_pdf(path, content)
    test_data.append({
        "path": path,
        "type": "criminal_acquitted",
        "expected_verdict": "acquitted",
        "expected_appeal": "yes",
        "expected_days": "90"
    })

# Civil Won
for i in range(1, 6):
    content = f"""
    IN THE CIVIL COURT, BANGALORE
    CASE NO: CS/{300+i}/2023
    ALICE {i} VS BOB {i}
    
    The plaintiff sought recovery of possession of property marked A.
    The plaintiff produced a registered sale deed showing ownership.
    The defendant failed to prove adverse possession.
    JUDGMENT: THE SUIT IS DECREED in favor of the plaintiff. Possession to be handed over in 60 days.
    """
    path = f"{base_dir}/civil/plaintiff_won/case_{i}.pdf"
    create_pdf(path, content)
    test_data.append({
        "path": path,
        "type": "civil_won",
        "expected_verdict": "won",
        "expected_appeal": "yes",
        "expected_days": "30"
    })

# Civil Lost
for i in range(1, 6):
    content = f"""
    IN THE CIVIL COURT, CHENNAI
    CASE NO: CS/{400+i}/2023
    CHARLIE {i} VS DAVID {i}
    
    The plaintiff filed a suit for recovery of money amounting to 5 lakhs.
    The plaintiff could not produce any promissory note or loan agreement.
    The suit is barred by limitation as the debt was from 2010.
    JUDGMENT: THE SUIT IS DISMISSED. Plaintiff is not entitled to any relief.
    """
    path = f"{base_dir}/civil/plaintiff_lost/case_{i}.pdf"
    create_pdf(path, content)
    test_data.append({
        "path": path,
        "type": "civil_lost",
        "expected_verdict": "lost",
        "expected_appeal": "yes",
        "expected_days": "30"
    })

with open("tests/test_metadata.json", "w") as f:
    json.dump(test_data, f, indent=4)

print("Generated 20 sample PDFs and test_metadata.json")
