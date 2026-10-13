# Support tracker task

Create one original support-operations task for a business colleague.

Use Google Sheets as the one scored application. Do not introduce additional applications
or background-only applications. The colleague asks for a specific update to an existing
row of a named support tracker, with a clear business reason for the new value. Keep the
instruction concise and preserve the row's identifier and its existing customer note.

Compose the task from the reusable sheet_row_state asset. Its complete English description
is at assetforge/artifacts/construction_assets/sheet_row_state/1.0.0/ASSET.md, and its parameter
contract is in definition.json alongside it. The supplied asset description includes both;
read them fully before choosing parameters.

Choose original names, a realistic row identifier, the column to update, its new value, and
the note to preserve. The asset provides spreadsheet, worksheet, and row records plus
terminal-state assertions. The initial value of the updated column must differ from the
requested value. State the business update and the preservation requirement in the public
instruction, without describing a particular sequence of tool calls.

The asset uses a literal row_key column. Include that exact column name in headers.
The row_key parameter supplies the row's identifier value, such as SUP-003; it is not a
header name.

A good task asks for a meaningful status change and keeps an existing note unchanged.
A poor task asks for a value already present, refers to a nonexistent column, or invents
an unrelated update solely to increase complexity. Do not copy an existing task.
