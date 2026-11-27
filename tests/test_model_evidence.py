import unittest
from deal_engine.model_evidence import match_model_evidence

class ModelEvidenceTest(unittest.TestCase):
    def test_exact_only(self):
        rows = [{"brand":"Whynter","model":"IMC-491DC","identities":["upc:850956003668"]}]
        self.assertEqual(match_model_evidence({"identity":"upc:850956003668"},rows)["identity_basis"],"exact_identifier")
        self.assertEqual(match_model_evidence({"brand":"WHYNTER","model":"IMC-491DC"},rows)["identity_basis"],"structured_brand_model")
        self.assertIsNone(match_model_evidence({"name":"Whynter IMC-491DC"},rows))
        self.assertIsNone(match_model_evidence({"brand":"Whynter","model":"IMC-491DC2"},rows))
        self.assertIsNone(match_model_evidence({"identity":"upc:850956003668"},rows+rows))

    def test_variant_identifier_required(self):
        rows = [{"brand":"SenCre","model":"BXZ002","identities":["upc:B0G5YLWNFJ"],"require_exact_identifier":True}]
        self.assertIsNone(match_model_evidence({"brand":"SenCre","model":"BXZ002"},rows))
        self.assertEqual(match_model_evidence({"brand":"SenCre","identity":"upc:B0G5YLWNFJ"},rows)["identity_basis"],"exact_identifier")
        self.assertIsNone(match_model_evidence({"brand":"SenCre","model":"Other","identity":"upc:B0G5YLWNFJ"},rows))

    def test_exact_identifier_curated_brand_alias_does_not_relax_variants(self):
        rows = [{"brand": "GE Profile", "model": None,
                 "identities": ["upc:B0FWLSYPN9"],
                 "exact_id_brand_aliases": ["Profile"],
                 "status": "MANUAL FILL DOCUMENTED", "watch": False}]
        matched = match_model_evidence({"identity": "upc:B0FWLSYPN9", "brand": "Profile"}, rows)
        self.assertEqual(matched["status"], "MANUAL FILL DOCUMENTED")
        self.assertEqual(matched["identity_basis"], "exact_identifier")
        self.assertIsNone(match_model_evidence({"identity": "upc:B0FWLSYPN9", "brand": "Unrelated"}, rows))
        self.assertIsNone(match_model_evidence({"identity": "upc:B0FWLSYPN9", "brand": "Profile", "model": "Wrong"}, rows))
        self.assertIsNone(match_model_evidence({"identity": "upc:OTHER", "brand": "Profile"}, rows))
        self.assertIsNone(match_model_evidence({"brand": "Profile"}, rows))
