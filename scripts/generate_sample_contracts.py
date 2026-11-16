"""Generate sample DOCX contracts for RedLiner email and redlining tests.

Run:
    PYTHONPATH=. uv run python scripts/generate_sample_contracts.py
"""

from __future__ import annotations

from pathlib import Path

import docx

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "sample_contracts"

CLEAN_CLAUSES = [
    (
        "1. Payment and Billing Terms",
        "Customer shall pay all undisputed invoice amounts on Net 60 terms. Customer "
        "may withhold payment in good faith for disputed amounts pending resolution. "
        "Late payments on undisputed sums accrue interest at the lesser of 1.0% per "
        "annum or the maximum rate permitted by law.",
    ),
    (
        "2. Intellectual Property Ownership",
        "Customer retains all rights, title, and interest in Customer Data and all "
        "deliverables. All custom deliverables are work made for hire owned by "
        "Customer. Vendor retains ownership of its pre-existing platform and grants "
        "Customer a non-exclusive license to use it during the subscription term.",
    ),
    (
        "3. Limitation of Liability",
        "Except for breaches of confidentiality, gross negligence, or "
        "indemnification obligations, each party's aggregate liability arising out "
        "of this Agreement shall not exceed the aggregate fees paid by Customer in "
        "the preceding twelve (12) months. Neither party is liable for indirect, "
        "incidental, special, or consequential damages.",
    ),
    (
        "4. Indemnification Obligations",
        "Vendor shall defend, indemnify and hold harmless Customer against "
        "third-party intellectual property infringement and data breach losses.",
    ),
    (
        "5. Term and Termination",
        "The initial term is twelve (12) months. Customer may terminate this "
        "Agreement for convenience upon thirty (30) days' prior written notice "
        "without penalty. Prepaid fees for the unused portion of the term shall be "
        "refunded on a pro-rata basis.",
    ),
    (
        "6. Data Privacy and Security",
        "Vendor maintains SOC 2 Type II controls, encrypts Customer Data in transit "
        "and at rest, and notifies Customer within forty-eight (48) hours of "
        "confirming a breach affecting Customer Data.",
    ),
    (
        "7. Governing Law and Dispute Resolution",
        "This Agreement shall be construed under Delaware law. Disputes shall be "
        "resolved by binding arbitration administered by the American Arbitration "
        "Association in Wilmington, Delaware.",
    ),
]

UNFAVORABLE_CLAUSES = [
    (
        "1. Payment and Billing Terms",
        "All invoices issued by Vendor are due upon receipt and payable within Net "
        "15 days. All fees are non-refundable and prepaid annually. Late payments "
        "incur a 1.5% per month interest surcharge on the outstanding balance.",
    ),
    (
        "2. Intellectual Property Ownership",
        "Vendor retains all right, title, and interest in the platform and all "
        "deliverables. Customer hereby assigns to Vendor all rights in derivative "
        "works, custom deliverables, and feedback. Customer receives only a "
        "non-transferable license to use the deliverables during the term.",
    ),
    (
        "3. Limitation of Liability",
        "Vendor's aggregate liability shall be uncapped and without limitation, "
        "including for indirect, incidental, special, and consequential damages. "
        "Customer's liability shall not be limited. Vendor liability shall not be "
        "limited for any reason.",
    ),
    (
        "4. Indemnification Obligations",
        "Customer shall indemnify, defend, and hold harmless Vendor against all "
        "third-party claims, including intellectual property infringement claims. "
        "Vendor shall have no obligation to defend Customer for intellectual "
        "property infringement or data breach claims.",
    ),
    (
        "5. Term and Termination",
        "The initial term is thirty-six (36) months and is strictly non-cancelable. "
        "Customer has no termination for convenience and must pay an early "
        "termination fee equal to 100% of the remaining fees.",
    ),
    (
        "6. Data Privacy and Security",
        "Vendor will use reasonable efforts only to protect Customer Data and will "
        "notify Customer within thirty days of confirmation of a security incident. "
        "No specific encryption or audit standard is required.",
    ),
    (
        "7. Governing Law and Dispute Resolution",
        "This Agreement is governed by the laws of England and Wales, and the "
        "parties submit to the exclusive jurisdiction of the courts of London, "
        "England.",
    ),
]


def build_contract(path: Path, title: str, clauses: list[tuple[str, str]], note: str) -> None:
    document = docx.Document()
    document.add_heading(title, 0)
    document.add_paragraph(
        'This Master Software as a Service Agreement ("Agreement") is entered into '
        'by and between ApexCloud Enterprise Ltd ("Vendor") and Global Enterprises '
        'Inc ("Customer").'
    )
    for heading, body in clauses:
        document.add_heading(heading, level=1)
        document.add_paragraph(body)
    document.core_properties.title = title
    document.core_properties.author = "RedLiner Test Fixtures"
    document.core_properties.comments = note
    document.save(str(path))


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    build_contract(
        OUTPUT_DIR / "sample_clean_saas_agreement.docx",
        "Master Software as a Service Agreement — Customer-Friendly Sample",
        CLEAN_CLAUSES,
        "Sample contract for RedLiner testing. This version is intended to pass the "
        "default enterprise playbook without redlines.",
    )
    build_contract(
        OUTPUT_DIR / "sample_unfavorable_saas_agreement.docx",
        "Master Software as a Service Agreement — Vendor-Friendly Sample",
        UNFAVORABLE_CLAUSES,
        "Sample contract for RedLiner testing. This version contains multiple "
        "playbook violations and should trigger human review.",
    )
    print(f"Wrote samples to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
