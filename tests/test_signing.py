import json
from pathlib import Path
import unittest

from dpp_webhook.cli import build_parser, prepare_payload
from dpp_webhook.signing import compact_json, sign_payload

ROOT = Path(__file__).resolve().parents[1]


class SigningTests(unittest.TestCase):
    def test_compact_json_matches_json_stringify_shape(self) -> None:
        payload = {
            "specVersion": "1.0",
            "data": {"productWeight": 420, "concentrationRange": 8.5},
        }

        body = compact_json(payload)

        self.assertEqual(
            body,
            '{"specVersion":"1.0","data":{"productWeight":420,"concentrationRange":8.5}}',
        )
        self.assertEqual(json.loads(body), payload)

    def test_signature_matches_known_hmac(self) -> None:
        payload = {"specVersion": "1.0", "messageId": "unique-msg-id-013"}
        signed = sign_payload(
            payload=payload,
            webhook_secret="D-pjxQB-UvkrYHxeNRk7jZgo0zm9dWNsyGiJZqWBFSg",
            timestamp="2026-06-12T07:41:42.301Z",
        )

        self.assertEqual(signed.timestamp, "2026-06-12T07:41:42.301Z")
        self.assertEqual(signed.body, '{"specVersion":"1.0","messageId":"unique-msg-id-013"}')
        self.assertEqual(
            signed.signature,
            "69ee91bc4ba7334fa4f74c3df6d3110f292b974884d7c083e872dc3d2eef9638",
        )

    def test_sample_payload_matches_postman_curl_signature(self) -> None:
        payload = {
            "specVersion": "1.0",
            "messageId": "unique-msg-id-013",
            "timestamp": "2026-05-22T10:00:00.000Z",
            "operation": "upsert",
            "data": {
                "materialsAndComposition": {
                    "sections": {
                        "materials": {
                            "fields": {
                                "batteryChemistry": "Lithium Iron Phosphate (LFP)",
                                "criticalRawMaterial": "Lithium",
                            }
                        },
                        "hazardousSubstance": {
                            "fields": {
                                "name": "Cobalt",
                                "impact": "Toxic to aquatic life",
                                "location": "Battery Cathode",
                                "indentifiers": "CAS-7440-48-4",
                                "hazardousClasses": "Acute Toxicity Category 4",
                                "concentrationRange": 8.5,
                            }
                        },
                    }
                },
                "generalProductAndManufacturerInfo": {
                    "sections": {
                        "productAndManufacturerInformation": {
                            "fields": {
                                "gtin": "09506000123456",
                                "expiryDate": "2035-12-31",
                                "productName": "Cleantron Battery Pack - 13",
                                "productWeight": 420,
                                "manufactureDate": "2026-01-15",
                                "manufacturePlace": "Dhaka, Bangladesh",
                                "productBatchNumber": "BATCH-20260115-001",
                                "productModelNumber": "EVBP-60-LFP",
                                "productImage": (
                                    "https://cdn.pixabay.com/photo/2024/05/26/10/15/"
                                    "bird-8788491_1280.jpg"
                                ),
                                "productSerialNumber": "SN-2026-00012345_13",
                                "manufacturerIdentification": "MFG-BD-001",
                            }
                        }
                    }
                },
            },
        }
        signed = sign_payload(
            payload=payload,
            webhook_secret="D-pjxQB-UvkrYHxeNRk7jZgo0zm9dWNsyGiJZqWBFSg",
            timestamp="2026-06-12T07:41:42.301Z",
        )

        self.assertEqual(
            signed.signature,
            "18b4d1c18516334618a95a0aca5c302adafa965aadeaaffeaced547e89a19465",
        )

    def test_cli_generates_dynamic_message_id_by_default(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "generate",
                "--secret",
                "secret",
                "--payload",
                str(ROOT / "examples/payload.json"),
            ]
        )

        first = prepare_payload(args)
        second = prepare_payload(args)

        self.assertNotEqual(first["messageId"], "unique-msg-id-013")
        self.assertNotEqual(second["messageId"], "unique-msg-id-013")
        self.assertNotEqual(first["messageId"], second["messageId"])

    def test_cli_can_preserve_message_id(self) -> None:
        original_payload = json.loads((ROOT / "examples/payload.json").read_text(encoding="utf-8"))
        parser = build_parser()
        args = parser.parse_args(
            [
                "generate",
                "--secret",
                "secret",
                "--payload",
                str(ROOT / "examples/payload.json"),
                "--preserve-message-id",
            ]
        )

        payload = prepare_payload(args)

        self.assertEqual(payload["messageId"], original_payload["messageId"])


if __name__ == "__main__":
    unittest.main()
