"""Cohort module: definition, operations, cohort_id, compile and suppress (docs/specs/34-*.md).

REST, MCP and the chat are thin layers over this package.
"""
from .definition import (CUT_POINTS, SCHEMA_VERSION, Definition, DefinitionError, Operation, Population,
                         apply, cohort_id, data_notes, json_schema, operation_json_schema, parse)
from .queries import count, data_date, pivot, snapshot_id, vocabulary
from .suppress import MIN_CELL, CountResult, PivotResult
from .vocabulary import VocabEntry, Vocabulary

__all__ = ["CUT_POINTS", "SCHEMA_VERSION", "Definition", "DefinitionError", "Operation", "Population", "apply", "cohort_id",
           "data_notes", "json_schema", "operation_json_schema", "parse", "count", "data_date", "pivot", "snapshot_id", "vocabulary",
           "MIN_CELL", "CountResult", "PivotResult", "VocabEntry", "Vocabulary"]
