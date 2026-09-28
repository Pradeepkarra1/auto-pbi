import tempfile
import unittest
from pathlib import Path

from auto_pbi.config import ConfigError, load_config

VALID = """
project:
  name: Test Dash
data:
  source: data.csv
kpis:
  - name: Revenue
    column: amount
    aggregation: sum
pages:
  - name: Overview
    visuals:
      - type: kpi_row
"""


class TestConfig(unittest.TestCase):
    def _write(self, text: str) -> Path:
        d = Path(tempfile.mkdtemp())
        p = d / "dashboard.yaml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_load_valid(self):
        cfg = load_config(self._write(VALID))
        self.assertEqual(cfg.project.safe_name, "TestDash")
        self.assertEqual(cfg.kpis[0].aggregation, "sum")

    def test_missing_project_name(self):
        with self.assertRaises(ConfigError):
            load_config(self._write("project: {}\ndata:\n  source: x.csv\n"))

    def test_unknown_aggregation(self):
        bad = VALID.replace("aggregation: sum", "aggregation: median")
        with self.assertRaises(ConfigError):
            load_config(self._write(bad))

    def test_unknown_visual_type(self):
        bad = VALID.replace("type: kpi_row", "type: waterfall")
        with self.assertRaises(ConfigError):
            load_config(self._write(bad))

    def test_kpi_needs_source(self):
        bad = VALID.replace("    column: amount\n    aggregation: sum\n", "")
        with self.assertRaises(ConfigError):
            load_config(self._write(bad))

    def test_unknown_kpi_reference(self):
        bad = VALID + "      - type: kpi\n        value: Nope\n"
        with self.assertRaises(ConfigError):
            load_config(self._write(bad))

    def test_trend_needs_date_column(self):
        bad = VALID.replace("    aggregation: sum\n", "    aggregation: sum\n    trend: yoy\n")
        with self.assertRaises(ConfigError):
            load_config(self._write(bad))

    def test_safe_name(self):
        cfg = load_config(self._write(VALID.replace("name: Test Dash", "name: sales-performance 2026!")))
        self.assertEqual(cfg.project.safe_name, "SalesPerformance2026")

    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            load_config("/nonexistent/dashboard.yaml")


if __name__ == "__main__":
    unittest.main()
