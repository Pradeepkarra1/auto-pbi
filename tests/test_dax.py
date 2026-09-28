import unittest

from auto_pbi import dax
from auto_pbi.config import KpiConfig


class TestDaxTemplates(unittest.TestCase):
    def test_base_sum(self):
        kpi = KpiConfig(name="Revenue", column="amount", aggregation="sum",
                        format="currency")
        expr, fmt = dax.base_measure(kpi, "Sales", {})
        self.assertEqual(expr, "SUM(Sales[amount])")
        self.assertEqual(fmt, "$#,##0")

    def test_base_distinct_count(self):
        kpi = KpiConfig(name="Customers", column="cust", aggregation="distinct_count")
        expr, _ = dax.base_measure(kpi, "Sales", {})
        self.assertEqual(expr, "DISTINCTCOUNT(Sales[cust])")

    def test_rule_base(self):
        kpi = KpiConfig(name="Total", rule="Net Revenue", format="currency")
        expr, fmt = dax.base_measure(kpi, "Sales", {"Net Revenue": "SUM(Sales[x])"})
        self.assertEqual(expr, "SUM(Sales[x])")
        self.assertEqual(fmt, "$#,##0")

    def test_raw_dax_wins(self):
        kpi = KpiConfig(name="X", column="a", dax="1 + 1", format="percent")
        expr, fmt = dax.base_measure(kpi, "Sales", {})
        self.assertEqual((expr, fmt), ("1 + 1", "0.0%"))

    def test_yoy_shape(self):
        expr = dax.yoy_growth("Total Revenue")
        self.assertIn("SAMEPERIODLASTYEAR('Date'[Date])", expr)
        self.assertIn("[Total Revenue]", expr)
        self.assertTrue(dax.check_balanced(expr))

    def test_mom_qoq_balanced(self):
        self.assertTrue(dax.check_balanced(dax.mom_growth("M")))
        self.assertTrue(dax.check_balanced(dax.qoq_growth("M")))
        self.assertTrue(dax.check_balanced(dax.ytd("M")))
        self.assertTrue(dax.check_balanced(dax.vs_target("M")))

    def test_check_balanced(self):
        self.assertTrue(dax.check_balanced("SUMX(Sales, Sales[a] * (1 - Sales[b]))"))
        self.assertFalse(dax.check_balanced("SUM(Sales[a]"))
        self.assertFalse(dax.check_balanced("SUM(Sales[a]))"))
        # quotes are ignored for bracket counting
        self.assertTrue(dax.check_balanced('FORMAT([Date], "mmm (yyyy")'))


if __name__ == "__main__":
    unittest.main()
