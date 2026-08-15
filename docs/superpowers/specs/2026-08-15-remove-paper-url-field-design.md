# Remove the Paper URL Text Field

## Goal

Remove the redundant `论文URL` text field from Feishu delivery. Preserve duplicate detection by using the URL stored in the existing `论文链接` hyperlink field.

## Considered Approaches

1. Use `论文链接` for duplicate detection. This removes the duplicate field while preserving current behavior. Selected.
2. Remove duplicate detection. This is simpler but would insert the same paper again on later runs.
3. Add a new hidden identifier field. This replaces one redundant field with another and is unnecessary for arXiv URLs.

## Data Flow

`paper_to_record_fields` writes one canonical paper URL into `论文链接` using Feishu's hyperlink object shape. Before insertion, `list_existing_urls` requests only `论文链接`, requires each returned value to be a mapping whose `link` member is a non-empty string, extracts `fields["论文链接"]["link"]`, normalizes it, and returns the existing URL set. Delivery compares each new record's `论文链接.link` URL against that string set before batch creation.

## Schema

Remove `论文URL` from the required Feishu field definitions and documentation. `论文链接` remains a required URL field. All other field names and types remain unchanged.

## Migration and Error Handling

First audit existing rows. For rows with a valid old `论文URL` but missing `论文链接`, copy the canonical URL into the `论文链接` hyperlink field. Rows missing both values must be repaired manually or deleted. After all rows have a valid `论文链接.link`, deploy the new code and verify one delivery run. Only then delete the physical `论文URL` column in Feishu using an account with table-edit permission. Removing it from `EXPECTED_FIELD_TYPES` alone does not delete the column.

After migration, an existing record without a valid `论文链接` URL is invalid table data. The client raises a `FeishuApiError` naming `论文链接`; it does not skip the record or disable duplicate detection. The parser rejects missing fields, `None`, empty mappings, missing `link`, and non-string or empty `link` values.

## Tests

- Record conversion no longer emits `论文URL` and still emits the canonical URL in `论文链接`.
- Schema validation no longer requires `论文URL`.
- Existing-record pagination requests `field_names: ["论文链接"]` and normalizes URLs from `论文链接.link` objects.
- Missing, `None`, empty, missing-`link`, non-string-`link`, and empty-`link` values raise `FeishuApiError`.
- Delivery integration filtering proves a record with a matching `论文链接.link` is not included in the batch-create payload.
- README, `docs/feishu-official-api-research.md`, and the current Feishu delivery design docs no longer instruct users to create `论文URL`.
