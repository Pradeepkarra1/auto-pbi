"""End-to-end: tiny CSV + YAML -> full .pbip project; assert the tree."""

import json
import tempfile
import unittest
from pathlib import Path

from auto_pbi.cli import main as cli_main
from auto_pbi.config import load_config
from auto_pbi.infer import infer_schema
from auto_pbi.plan import build_plan

CSV = """order_id,order_date,region,amount
1,2024-01-05,West,100.0
2,2024-02-10,East,250.5
3,2025-03-15,West,75.25
"""

YAML = """
project:
  name: E2E Test
  theme: corporate
data:
  source: data.csv
  table: Orders
  date_column: order_date
business_rules:
  - name: Net Sales
    definition: Sales after returns.
    dax: SUM(Orders[amount])
kpis:
  - name: Total Sales
    rule: Net Sales
    format: currency
    target: 1000
    trend: yoy
  - name: Order Count
    column: order_id
    aggregation: count
    format: integer
pages:
  - name: Overview
    visuals:
      - type: kpi_row
      - type: line
        title: Sales trend
        category: Date.Month
        values: [Total Sales]
      - type: bar
        title: Sales by region
        category: Orders.region
        values: [Total Sales]
      - type: gauge
        title: Sales vs target
        value: Total Sales
"""


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "data.csv").write_text(CSV, encoding="utf-8")
        (self.tmp / "dashboard.yaml").write_text(YAML, encoding="utf-8")
        self.out = self.tmp / "out"

    def test_build_tree(self):
        rc = cli_main(["build", "--config", str(self.tmp / "dashboard.yaml"),
                       "--out", str(self.out)])
        self.assertEqual(rc, 0)

        root = self.out
        self.assertTrue((root / "E2ETest.pbip").exists())
        sm = root / "E2ETest.SemanticModel"
        rep = root / "E2ETest.Report"
        for rel in [
            "definition.pbism",
            "definition/database.tmdl",
            "definition/model.tmdl",
            "definition/relationships.tmdl",
            "definition/tables/Orders.tmdl",
            "definition/tables/Date.tmdl",
            "definition/tables/KPI Glossary.tmdl",
        ]:
            self.assertTrue((sm / rel).exists(), rel)
        for rel in [
            "definition.pbir",
            "definition/version.json",
            "definition/report.json",
            "definition/pages/pages.json",
            "definition/pages/overview/page.json",
            "definition/pages/kpi_glossary/page.json",
            "StaticResources/RegisteredResources/AutoPBI_Corporate.json",
        ]:
            self.assertTrue((rep / rel).exists(), rel)

        # every JSON file parses
        for p in root.rglob("*.json"):
            with open(p, encoding="utf-8") as f:
                json.load(f)

        # TMDL is tab-indented, no BOM
        tmdl = (sm / "definition/tables/Orders.tmdl").read_bytes()
        self.assertFalse(tmdl.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\tcolumn order_id", tmdl)
        self.assertIn(b"measure 'Total Sales YoY %'", tmdl)
        self.assertIn(b"measure 'Total Sales Target'", tmdl)
        self.assertIn(b"partition Orders = m", tmdl)

        # report.json points at the registered theme
        report_json = json.loads((rep / "definition/report.json").read_text())
        self.assertEqual(
            report_json["themeCollection"]["customTheme"]["packageName"],
            "RegisteredResources/AutoPBI_Corporate.json")

        # overview page has title + 2 cards + line + bar + gauge = 6 visuals
        visuals = list((rep / "definition/pages/overview/visuals").iterdir())
        self.assertEqual(len(visuals), 6)
        types = set()
        for v in visuals:
            doc = json.loads((v / "visual.json").read_text())
            types.add(doc["visual"]["visualType"])
        self.assertEqual(types, {"textbox", "cardVisual", "lineChart",
                                 "clusteredBarChart", "gauge"})

        # gauge binds the target measure
        gauge = json.loads(
            (rep / "definition/pages/overview/visuals/sales_vs_target/visual.json")
            .read_text())
        refs = [p["queryRef"]
                for p in gauge["visual"]["query"]["queryState"]["TargetValue"]["projections"]]
        self.assertEqual(refs, ["Orders.Total Sales Target"])

        # pages.json ordering
        pages = json.loads((rep / "definition/pages/pages.json").read_text())
        self.assertEqual(pages["pageOrder"], ["overview", "kpi_glossary"])

    def test_validate_ok(self):
        rc = cli_main(["validate", "--config", str(self.tmp / "dashboard.yaml")])
        self.assertEqual(rc, 0)

    def test_schema_inference(self):
        cols = infer_schema(self.tmp / "data.csv")
        by_name = {c.name: c for c in cols}
        self.assertEqual(by_name["order_id"].tmdl_type, "int64")
        self.assertEqual(by_name["order_date"].tmdl_type, "dateTime")
        self.assertEqual(by_name["region"].tmdl_type, "string")
        self.assertEqual(by_name["amount"].tmdl_type, "double")

    def test_plan_measures(self):
        cfg = load_config(self.tmp / "dashboard.yaml")
        plan = build_plan(cfg, infer_schema(self.tmp / "data.csv"))
        names = plan.measure_names()
        self.assertIn("Total Sales", names)
        self.assertIn("Total Sales YoY %", names)
        self.assertIn("Total Sales Target", names)  # gauge reuses the KPI target
        self.assertIn("Total Sales vs Target", names)
        self.assertTrue(plan.glossary_rows)


if __name__ == "__main__":
    unittest.main()
