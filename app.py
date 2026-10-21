
from flask import Flask, render_template, request, send_file
import sqlite3
from pathlib import Path
from datetime import datetime
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "cloudbridge.db"

# Illustrative demo rates only. These are NOT live cloud prices.
# memory_score is a sample suitability score, not a measured benchmark.
CLOUD_PROVIDERS = {
    "AWS": {
        "vm_hourly": 0.050,
        "storage_gb_monthly": 0.023,
        "memory_score": 88,
        "performance_score": 90
    },
    "Azure": {
        "vm_hourly": 0.060,
        "storage_gb_monthly": 0.020,
        "memory_score": 92,
        "performance_score": 87
    },
    "Google Cloud": {
        "vm_hourly": 0.045,
        "storage_gb_monthly": 0.020,
        "memory_score": 86,
        "performance_score": 89
    }
}

PRIORITY_LABELS = {
    "cost": "Lowest Cost",
    "memory": "Memory Focused",
    "balanced": "Balanced"
}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS comparison_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                vms INTEGER NOT NULL,
                hours REAL NOT NULL,
                storage REAL NOT NULL,
                priority TEXT NOT NULL,
                recommended_provider TEXT NOT NULL,
                lowest_cost REAL NOT NULL
            )
        """)


def calculate_comparison(vms, hours, storage, priority):
    results = []

    for provider, rates in CLOUD_PROVIDERS.items():
        compute_cost = rates["vm_hourly"] * vms * hours
        storage_cost = rates["storage_gb_monthly"] * storage
        monthly_total = compute_cost + storage_cost

        results.append({
            "provider": provider,
            "compute": round(compute_cost, 2),
            "storage": round(storage_cost, 2),
            "total": round(monthly_total, 2),
            "yearly": round(monthly_total * 12, 2),
            "memory_score": rates["memory_score"],
            "performance_score": rates["performance_score"],
            "cost_score": 0,
            "balanced_score": 0
        })

    cheapest = min(item["total"] for item in results)

    # Cost score: the cheapest provider receives 100.
    # Other providers score lower according to their relative cost.
    for item in results:
        item["cost_score"] = round(
            (cheapest / item["total"] * 100) if item["total"] > 0 else 100,
            1
        )

        # Balanced score: 60% cost score and 40% sample suitability.
        suitability = (
            item["memory_score"] * 0.5
            + item["performance_score"] * 0.5
        )
        item["balanced_score"] = round(
            item["cost_score"] * 0.60 + suitability * 0.40, 1
        )

    if priority == "memory":
        recommendation = max(results, key=lambda item: item["memory_score"])
        reason = (
            f"{recommendation['provider']} has the highest sample "
            f"memory-suitability score ({recommendation['memory_score']}/100)."
        )
    elif priority == "balanced":
        recommendation = max(results, key=lambda item: item["balanced_score"])
        reason = (
            f"{recommendation['provider']} has the highest balanced score "
            f"({recommendation['balanced_score']}/100), combining estimated "
            "cost and sample suitability."
        )
    else:
        recommendation = min(results, key=lambda item: item["total"])
        reason = (
            f"{recommendation['provider']} has the lowest estimated total "
            f"cost: ${recommendation['total']:.2f} per month."
        )

    return results, recommendation, reason


def parse_workload(form):
    vms = int(form.get("vms", 2))
    hours = float(form.get("hours", 730))
    storage = float(form.get("storage", 100))
    priority = form.get("priority", "cost")
    budget = float(form.get("budget", 100))

    if not 1 <= vms <= 10000:
        raise ValueError("VM count must be between 1 and 10,000.")
    if not 0 <= hours <= 100000:
        raise ValueError("Usage hours must be between 0 and 100,000.")
    if not 0 <= storage <= 10000000:
        raise ValueError("Storage must be between 0 and 10,000,000 GB.")
    if not 0 <= budget <= 1000000000:
        raise ValueError("Monthly budget must be between $0 and $1,000,000,000.")
    if priority not in PRIORITY_LABELS:
        priority = "cost"

    return vms, hours, storage, priority, budget


def build_report(vms, hours, storage, priority, budget,
                 results, recommendation, reason):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle",
        parent=styles["Title"],
        fontSize=24,
        leading=30,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#245bd7"),
        spaceAfter=8
    ))
    styles.add(ParagraphStyle(
        name="SectionHeading",
        parent=styles["Heading2"],
        textColor=colors.HexColor("#245bd7"),
        spaceBefore=14,
        spaceAfter=8
    ))

    story = [
        Paragraph("CloudBridge", styles["ReportTitle"]),
        Paragraph(
            "Multi-Cloud Resource Comparison Report",
            styles["Normal"]
        ),
        Spacer(1, 8 * mm),
        Paragraph("1. Workload Configuration", styles["SectionHeading"])
    ]

    workload_data = [
        ["Setting", "Value"],
        ["Virtual machines", str(vms)],
        ["Usage hours per month", f"{hours:g}"],
        ["Storage", f"{storage:g} GB"],
        ["Optimization priority", PRIORITY_LABELS[priority]],
        ["Monthly budget", f"${budget:,.2f}"]
    ]

    workload_table = Table(workload_data, colWidths=[70 * mm, 85 * mm])
    workload_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d3c70")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d3ddeb")),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE")
    ]))
    story += [workload_table, Paragraph(
        "2. Provider Cost Estimates", styles["SectionHeading"]
    )]

    cost_data = [[
        "Provider", "Compute", "Storage", "Monthly", "Yearly"
    ]]
    for item in results:
        cost_data.append([
            item["provider"],
            f"${item['compute']:.2f}",
            f"${item['storage']:.2f}",
            f"${item['total']:.2f}",
            f"${item['yearly']:.2f}"
        ])

    cost_table = Table(
        cost_data,
        colWidths=[39 * mm, 27 * mm, 27 * mm, 29 * mm, 29 * mm]
    )
    cost_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d3c70")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d3ddeb")),
        ("PADDING", (0, 0), (-1, -1), 7),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE")
    ]))
    story += [cost_table, Paragraph(
        "3. Smart Recommendation", styles["SectionHeading"]
    )]

    story.append(Paragraph(
        f"<b>Recommended provider:</b> {recommendation['provider']}",
        styles["Normal"]
    ))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(reason, styles["Normal"]))
    story.append(Spacer(1, 4 * mm))

    difference = recommendation["total"] - budget
    if difference > 0:
        budget_text = (
            f"Budget alert: estimated monthly cost exceeds your budget "
            f"by ${difference:.2f}."
        )
    else:
        budget_text = (
            f"Budget status: within your monthly budget, with "
            f"${abs(difference):.2f} remaining."
        )

    story += [
        Paragraph("4. Budget and Forecast", styles["SectionHeading"]),
        Paragraph(
            f"Recommended estimated monthly cost: "
            f"${recommendation['total']:.2f}",
            styles["Normal"]
        ),
        Paragraph(
            f"Estimated yearly cost: ${recommendation['yearly']:.2f}",
            styles["Normal"]
        ),
        Paragraph(budget_text, styles["Normal"]),
        Spacer(1, 8 * mm),
        Paragraph("Pricing Disclaimer", styles["SectionHeading"]),
        Paragraph(
            "This report uses illustrative sample hourly compute rates, "
            "storage rates, and suitability scores for demonstration. "
            "It does not fetch live prices from AWS, Microsoft Azure, or "
            "Google Cloud. Actual prices depend on region, machine type, "
            "operating system, discounts, data transfer, taxes, and other "
            "services. Yearly forecasts assume the same usage and rates "
            "for 12 months. This report is not a billing quote.",
            styles["Normal"]
        ),
        Spacer(1, 8 * mm),
        Paragraph(
            f"Generated by CloudBridge on "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            styles["Normal"]
        )
    ]

    doc.build(story)
    buffer.seek(0)
    return buffer


initialize_database()


@app.route("/", methods=["GET", "POST"])
def home():
    results = []
    recommendation = None
    reason = None
    error = None
    budget = 100.0
    vms = 2
    hours = 730.0
    storage = 100.0
    priority = "cost"

    if request.method == "POST":
        try:
            vms, hours, storage, priority, budget = parse_workload(request.form)
            results, recommendation, reason = calculate_comparison(
                vms, hours, storage, priority
            )

            with get_db() as conn:
                conn.execute("""
                    INSERT INTO comparison_history
                    (created_at, vms, hours, storage, priority,
                     recommended_provider, lowest_cost)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    vms, hours, storage, priority,
                    recommendation["provider"], recommendation["total"]
                ))

        except (ValueError, TypeError) as exc:
            error = str(exc) or "Please enter valid workload values."
            results = []
            recommendation = None
            reason = None

    with get_db() as conn:
        history = conn.execute("""
            SELECT * FROM comparison_history
            ORDER BY id DESC
            LIMIT 10
        """).fetchall()

    budget_difference = (
        round(recommendation["total"] - budget, 2)
        if recommendation else 0
    )

    return render_template(
        "index.html",
        results=results,
        recommendation=recommendation,
        reason=reason,
        error=error,
        history=history,
        vms=vms,
        hours=hours,
        storage=storage,
        priority=priority,
        budget=budget,
        budget_difference=budget_difference,
        priority_labels=PRIORITY_LABELS
    )


@app.route("/download-report", methods=["POST"])
def download_report():
    try:
        vms, hours, storage, priority, budget = parse_workload(request.form)
        results, recommendation, reason = calculate_comparison(
            vms, hours, storage, priority
        )
        pdf = build_report(
            vms, hours, storage, priority, budget,
            results, recommendation, reason
        )

        return send_file(
            pdf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name="CloudBridge_Comparison_Report.pdf"
        )
    except (ValueError, TypeError) as exc:
        return (
            f"Could not generate the report: {exc}. "
            "Return to the dashboard and enter valid values.",
            400
        )


@app.route("/health")
def health():
    return {"status": "CloudBridge is running"}


if __name__ == "__main__":
    app.run(debug=True)
