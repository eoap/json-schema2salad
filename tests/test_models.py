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

from pydantic import ValidationError

from json_schema2salad.models import (
    ArrayType,
    EnumType,
    ImportDirective,
    RecordField,
    RecordType,
    SaladDocument,
    SpecializeDef,
)


class SpecializeDefTests(unittest.TestCase):
    def test_as_salad_uses_alias_names(self) -> None:
        specialize = SpecializeDef(specialize_from='BaseType', specialize_to='ConcreteType')

        self.assertEqual(
            {'specializeFrom': 'BaseType', 'specializeTo': 'ConcreteType'},
            specialize.as_salad(),
        )


class RecordFieldTests(unittest.TestCase):
    def test_name_is_trimmed_and_type_property_reflects_alias_field(self) -> None:
        field = RecordField(name='  title  ', type='string', jsonldPredicate='sld:title')

        self.assertEqual('title', field.name)
        self.assertEqual('string', field.type)
        self.assertEqual(
            {
                'name': 'title',
                'type': 'string',
                'jsonldPredicate': 'sld:title',
            },
            field.as_salad(),
        )

    def test_empty_name_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            RecordField(name='   ', type='string')

    def test_validate_assignment_revalidates_name_changes(self) -> None:
        field = RecordField(name='title', type='string')

        with self.assertRaises(ValidationError):
            field.name = '   '


class RecordTypeTests(unittest.TestCase):
    def test_record_name_is_trimmed(self) -> None:
        record = RecordType(name='  ExampleRecord  ')

        self.assertEqual('ExampleRecord', record.name)

    def test_empty_record_name_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            RecordType(name='   ')

    def test_record_serializes_nested_fields_and_specialize_aliases(self) -> None:
        record = RecordType(
            name='ExampleRecord',
            fields=[RecordField(name='value', type=ArrayType(items='string'))],
            extends=['BaseRecord'],
            specialize=[SpecializeDef(specialize_from='BaseRecord', specialize_to='ExampleRecord')],
        )

        self.assertEqual(
            {
                'type': 'record',
                'name': 'ExampleRecord',
                'fields': [
                    {
                        'name': 'value',
                        'type': {'type': 'array', 'items': 'string'},
                    }
                ],
                'extends': ['BaseRecord'],
                'specialize': [
                    {'specializeFrom': 'BaseRecord', 'specializeTo': 'ExampleRecord'}
                ],
            },
            record.as_salad(),
        )

    def test_json_ref_source_is_kept_internal(self) -> None:
        record = RecordType(
            name='ExampleRecord',
            json_ref_source='file:///schemas/example.json#/$defs/ExampleRecord',
        )

        self.assertEqual(
            'file:///schemas/example.json#/$defs/ExampleRecord',
            record.json_ref_source,
        )
        self.assertNotIn('json_ref_source', record.as_salad())


class EnumAndArrayTypeTests(unittest.TestCase):
    def test_enum_and_array_models_support_recursive_type_expression(self) -> None:
        enum_type = EnumType(name='Status', symbols=['open', 'closed'])
        array_type = ArrayType(items=['null', enum_type])

        self.assertEqual(
            {'type': 'array', 'items': ['null', {'type': 'enum', 'name': 'Status', 'symbols': ['open', 'closed']}]},
            array_type.as_salad(),
        )

    def test_enum_json_ref_source_is_kept_internal(self) -> None:
        enum_type = EnumType(
            name='Status',
            symbols=['open', 'closed'],
            json_ref_source='file:///schemas/example.json#/$defs/Status',
        )

        self.assertEqual(
            'file:///schemas/example.json#/$defs/Status',
            enum_type.json_ref_source,
        )
        self.assertNotIn('json_ref_source', enum_type.as_salad())


class SaladDocumentTests(unittest.TestCase):
    def test_import_directive_serializes_alias(self) -> None:
        directive = ImportDirective(**{'$import': 'https://example.org/schema.yaml'})

        self.assertEqual({'$import': 'https://example.org/schema.yaml'}, directive.as_salad())
        self.assertEqual('https://example.org/schema.yaml', directive.import_)

    def test_add_appends_graph_entries_and_serializes_document_aliases(self) -> None:
        import_directive = ImportDirective(**{'$import': 'https://example.org/schema.yaml'})
        enum_type = EnumType(name='Status', symbols=['open', 'closed'])
        record_type = RecordType(name='ExampleRecord')
        document = SaladDocument(
            **{
                '$namespaces': {'ex': 'https://example.org/ns#'},
            }
        )

        returned = document.add(import_directive, enum_type, record_type)

        self.assertIs(document, returned)
        self.assertEqual([import_directive, enum_type, record_type], document.graph)
        serialized = document.as_salad()

        self.assertEqual(
            ['$namespaces', '$graph'],
            list(serialized.keys()),
        )
        self.assertEqual(
            {
                '$namespaces': {'ex': 'https://example.org/ns#'},
                '$graph': [
                    {'$import': 'https://example.org/schema.yaml'},
                    {'type': 'enum', 'name': 'Status', 'symbols': ['open', 'closed']},
                    {'type': 'record', 'name': 'ExampleRecord', 'fields': []},
                ],
            },
            serialized,
        )


if __name__ == '__main__':
    unittest.main()
