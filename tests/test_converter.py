# Copyright 2026 Terradue
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest

from json_schema2salad import (
    convert_json_schema_to_salad,
    convert_json_schema_to_salad_details,
    plan_conversion_names,
)
from json_schema2salad.models import ImportDirective


STRING_FORMAT_SCHEMA_URI = "https://raw.githubusercontent.com/eoap/schemas/refs/heads/main/string_format.yaml"
STRING_FORMAT_NAMESPACE_URI = f"{STRING_FORMAT_SCHEMA_URI}#"
SALAD_NAMESPACE_URI = "https://w3id.org/cwl/salad#"


class ConversionDocumentationTests(unittest.TestCase):
    def test_field_doc_appends_example_when_description_is_present(self) -> None:
        schema = {
            'title': 'Root',
            'type': 'object',
            'properties': {
                'name': {
                    'type': 'string',
                    'description': 'Human readable name',
                    'example': 'Alice',
                }
            },
            'required': ['name'],
        }

        document, warnings = convert_json_schema_to_salad(schema)
        root_record = next(type_def for type_def in document.graph if type_def.name == 'Root')
        field = root_record.fields[0]

        self.assertEqual([], warnings)
        self.assertEqual('Human readable name\n\nExample: Alice', field.doc)

    def test_enum_doc_uses_example_when_description_is_missing(self) -> None:
        schema = {
            'title': 'Root',
            'type': 'object',
            'properties': {
                'status': {
                    'type': 'string',
                    'enum': ['open', 'closed'],
                    'example': 'open',
                }
            },
            'required': ['status'],
        }

        document, warnings = convert_json_schema_to_salad(schema)
        enum_type = next(type_def for type_def in document.graph if type_def.name != 'Root')

        self.assertEqual([], warnings)
        self.assertEqual('Example: open', enum_type.doc)


class StringFormatConversionTests(unittest.TestCase):
    def assert_imports_string_format_schema(self, document) -> None:
        self.assertEqual(
            {
                'sld': SALAD_NAMESPACE_URI,
                'string_format': STRING_FORMAT_NAMESPACE_URI,
            },
            document.namespaces,
        )
        self.assertIsInstance(document.graph[0], ImportDirective)
        self.assertEqual(STRING_FORMAT_SCHEMA_URI, document.graph[0].import_)

    def test_string_format_maps_to_eoap_salad_reference(self) -> None:
        schema = {
            'title': 'Root',
            'type': 'object',
            'properties': {
                'published': {
                    'type': 'string',
                    'format': 'date',
                }
            },
            'required': ['published'],
        }

        document, warnings = convert_json_schema_to_salad(schema)
        root_record = next(type_def for type_def in document.graph if getattr(type_def, 'name', None) == 'Root')
        field = root_record.fields[0]

        self.assertEqual([], warnings)
        self.assert_imports_string_format_schema(document)
        self.assertEqual('string_format:Date', field.type)

    def test_string_format_applies_inside_arrays_and_nullable_unions(self) -> None:
        schema = {
            'title': 'Root',
            'type': 'object',
            'properties': {
                'timestamps': {
                    'type': 'array',
                    'items': {
                        'type': 'string',
                        'format': 'date-time',
                    },
                },
                'callback': {
                    'type': ['string', 'null'],
                    'format': 'uri',
                },
            },
            'required': ['timestamps'],
        }

        document, warnings = convert_json_schema_to_salad(schema)
        root_record = next(type_def for type_def in document.graph if getattr(type_def, 'name', None) == 'Root')
        timestamps = next(field for field in root_record.fields if field.name == 'timestamps')
        callback = next(field for field in root_record.fields if field.name == 'callback')

        self.assertEqual([], warnings)
        self.assert_imports_string_format_schema(document)
        self.assertEqual('string_format:DateTime', timestamps.type.items)
        self.assertEqual(['string_format:URI', 'null'], callback.type)

    def test_plain_strings_do_not_import_string_format_schema(self) -> None:
        schema = {
            'title': 'Root',
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
            },
            'required': ['name'],
        }

        document, warnings = convert_json_schema_to_salad(schema)
        root_record = next(type_def for type_def in document.graph if type_def.name == 'Root')
        name = next(field for field in root_record.fields if field.name == 'name')

        self.assertEqual([], warnings)
        self.assertEqual({'sld': SALAD_NAMESPACE_URI}, document.namespaces)
        self.assertNotIsInstance(document.graph[0], ImportDirective)
        self.assertEqual('string', name.type)

    def test_all_eoap_string_formats_are_supported(self) -> None:
        expected_refs = {
            'date': 'Date',
            'date-time': 'DateTime',
            'duration': 'Duration',
            'email': 'Email',
            'hostname': 'Hostname',
            'idn-email': 'IDNEmail',
            'idn-hostname': 'IDNHostname',
            'ipv4': 'IPv4',
            'ipv6': 'IPv6',
            'iri': 'IRI',
            'iri-reference': 'IRIReference',
            'json-pointer': 'JsonPointer',
            'password': 'Password',
            'relative-json-pointer': 'RelativeJsonPointer',
            'uuid': 'UUID',
            'uri': 'URI',
            'uri-reference': 'URIReference',
            'uri-template': 'URITemplate',
            'time': 'Time',
        }
        schema = {
            'title': 'Root',
            'type': 'object',
            'properties': {
                name.replace('-', '_'): {
                    'type': 'string',
                    'format': name,
                }
                for name in expected_refs
            },
            'required': [name.replace('-', '_') for name in expected_refs],
        }

        document, warnings = convert_json_schema_to_salad(schema)
        root_record = next(type_def for type_def in document.graph if getattr(type_def, 'name', None) == 'Root')
        fields_by_name = {field.name: field for field in root_record.fields}

        self.assertEqual([], warnings)
        self.assert_imports_string_format_schema(document)
        for format_name, record_name in expected_refs.items():
            field_name = format_name.replace('-', '_')
            self.assertEqual(f'string_format:{record_name}', fields_by_name[field_name].type)


class RecordNamingTests(unittest.TestCase):
    def test_root_object_record_uses_sanitized_title(self) -> None:
        schema = {
            'title': 'Order Root/v2',
            'type': 'object',
            'properties': {
                'id': {'type': 'string'},
            },
            'required': ['id'],
        }

        document, warnings = convert_json_schema_to_salad(schema)

        self.assertEqual([], warnings)
        self.assertTrue(any(type_def.name == 'Order_Root_v2' for type_def in document.graph))

    def test_nested_object_record_uses_title_when_present(self) -> None:
        schema = {
            'title': 'Root',
            'type': 'object',
            'properties': {
                'contact': {
                    'title': 'Contact Details/v2',
                    'type': 'object',
                    'properties': {
                        'email': {'type': 'string'},
                    },
                    'required': ['email'],
                }
            },
            'required': ['contact'],
        }

        document, warnings = convert_json_schema_to_salad(schema)
        root_record = next(type_def for type_def in document.graph if type_def.name == 'Root')
        contact_field = next(field for field in root_record.fields if field.name == 'contact')

        self.assertEqual([], warnings)
        self.assertEqual('Contact_Details_v2', contact_field.type)
        self.assertTrue(any(type_def.name == 'Contact_Details_v2' for type_def in document.graph))

    def test_nested_object_record_keeps_field_based_name_without_title(self) -> None:
        schema = {
            'title': 'Root',
            'type': 'object',
            'properties': {
                'contact': {
                    'type': 'object',
                    'properties': {
                        'email': {'type': 'string'},
                    },
                    'required': ['email'],
                }
            },
            'required': ['contact'],
        }

        document, warnings = convert_json_schema_to_salad(schema)
        root_record = next(type_def for type_def in document.graph if type_def.name == 'Root')
        contact_field = next(field for field in root_record.fields if field.name == 'contact')

        self.assertEqual([], warnings)
        self.assertEqual('Root_contact', contact_field.type)
        self.assertTrue(any(type_def.name == 'Root_contact' for type_def in document.graph))

    def test_definition_object_ref_uses_title_record_name(self) -> None:
        schema = {
            'title': 'Root',
            'type': 'object',
            'properties': {
                'billing': {'$ref': '#/$defs/BillingAddress'},
            },
            'required': ['billing'],
            '$defs': {
                'BillingAddress': {
                    'title': 'Billing Address/v2',
                    'type': 'object',
                    'properties': {
                        'street': {'type': 'string'},
                    },
                    'required': ['street'],
                },
            },
        }

        document, warnings = convert_json_schema_to_salad(schema)
        root_record = next(type_def for type_def in document.graph if type_def.name == 'Root')
        billing_field = next(field for field in root_record.fields if field.name == 'billing')
        graph_names = [type_def.name for type_def in document.graph]

        self.assertEqual([], warnings)
        self.assertEqual('Billing_Address_v2', billing_field.type)
        self.assertIn('Billing_Address_v2', graph_names)
        self.assertNotIn('DefsBillingAddress', graph_names)


class DuplicateSourceRefTests(unittest.TestCase):
    def test_repeated_titled_inline_object_reuses_existing_record(self) -> None:
        point_schema = {
            'title': 'GeoJSON Point',
            'type': 'object',
            'properties': {
                'type': {'type': 'string', 'enum': ['Point']},
                'coordinates': {
                    'type': 'array',
                    'items': {'type': 'number'},
                },
            },
            'required': ['type', 'coordinates'],
        }
        schema = {
            'title': 'Root',
            'type': 'object',
            'properties': {
                'geometry': {'oneOf': [point_schema]},
                'nested_geometry': {'oneOf': [point_schema]},
            },
            'required': ['geometry', 'nested_geometry'],
        }

        document, warnings = convert_json_schema_to_salad(schema)
        root_record = next(type_def for type_def in document.graph if type_def.name == 'Root')
        geometry = next(field for field in root_record.fields if field.name == 'geometry')
        nested_geometry = next(field for field in root_record.fields if field.name == 'nested_geometry')
        graph_names = [type_def.name for type_def in document.graph]

        self.assertEqual([], warnings)
        self.assertEqual(['GeoJSON_Point'], geometry.type)
        self.assertEqual(['GeoJSON_Point'], nested_geometry.type)
        self.assertEqual(1, graph_names.count('GeoJSON_Point'))
        self.assertNotIn('GeoJSON_Point2', graph_names)
        self.assertEqual(1, graph_names.count('GeoJSON_Point_type'))
        self.assertNotIn('GeoJSON_Point2_type', graph_names)

    def test_matching_inline_title_with_different_schema_keeps_accumulator(self) -> None:
        schema = {
            'title': 'Root',
            'type': 'object',
            'properties': {
                'first': {
                    'title': 'Shared Shape',
                    'type': 'object',
                    'properties': {
                        'value': {'type': 'string'},
                    },
                    'required': ['value'],
                },
                'second': {
                    'title': 'Shared Shape',
                    'type': 'object',
                    'properties': {
                        'count': {'type': 'integer'},
                    },
                    'required': ['count'],
                },
            },
            'required': ['first', 'second'],
        }

        document, warnings = convert_json_schema_to_salad(schema)
        root_record = next(type_def for type_def in document.graph if type_def.name == 'Root')
        first = next(field for field in root_record.fields if field.name == 'first')
        second = next(field for field in root_record.fields if field.name == 'second')
        graph_names = [type_def.name for type_def in document.graph]

        self.assertEqual([], warnings)
        self.assertEqual('Shared_Shape', first.type)
        self.assertEqual('Shared_Shape2', second.type)
        self.assertIn('Shared_Shape', graph_names)
        self.assertIn('Shared_Shape2', graph_names)

    def test_existing_json_ref_source_reuses_name_without_accumulator(self) -> None:
        schema = {
            'title': 'Root',
            'type': 'object',
            'properties': {
                'thing': {'$ref': '#/$defs/Thing'},
            },
            'required': ['thing'],
            '$defs': {
                'Thing': {
                    'title': 'Thing',
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'string'},
                    },
                    'required': ['id'],
                },
            },
        }
        source_ref = 'file:///schemas/root.json#/$defs/Thing'

        plan = plan_conversion_names(
            schema,
            base_uri='file:///schemas/root.json',
            reserved_names={'Thing'},
            source_ref_to_name={source_ref: 'Thing'},
        )
        converted = convert_json_schema_to_salad_details(
            schema,
            base_uri='file:///schemas/root.json',
            plan=plan,
            reserved_names={'Thing'},
        )
        root_record = next(type_def for type_def in converted.document.graph if type_def.name == 'Root')
        thing_field = next(field for field in root_record.fields if field.name == 'thing')
        graph_names = [type_def.name for type_def in converted.document.graph]
        thing_record = next(type_def for type_def in converted.document.graph if type_def.name == 'Thing')

        self.assertEqual('Thing', plan.ref_map['#/$defs/Thing'])
        self.assertEqual('Thing', thing_field.type)
        self.assertEqual(1, graph_names.count('Thing'))
        self.assertNotIn('Thing2', graph_names)
        self.assertEqual(source_ref, thing_record.json_ref_source)

    def test_matching_title_from_different_json_ref_source_still_gets_accumulator(self) -> None:
        schema = {
            'title': 'Root',
            'type': 'object',
            'properties': {
                'thing': {'$ref': '#/$defs/Thing'},
            },
            'required': ['thing'],
            '$defs': {
                'Thing': {
                    'title': 'Thing',
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'string'},
                    },
                    'required': ['id'],
                },
            },
        }

        plan = plan_conversion_names(
            schema,
            base_uri='file:///schemas/other-root.json',
            reserved_names={'Thing'},
            source_ref_to_name={'file:///schemas/root.json#/$defs/Thing': 'Thing'},
        )

        self.assertEqual('Thing2', plan.ref_map['#/$defs/Thing'])


if __name__ == '__main__':
    unittest.main()
