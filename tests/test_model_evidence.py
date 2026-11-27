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
