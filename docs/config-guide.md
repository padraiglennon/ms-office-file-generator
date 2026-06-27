# The data file (JSON) - field-by-field guide

This is the file you edit to decide **what goes into** your Office file. You do
not need any programming knowledge - copy the sample, change the values, and
save. The structure is always the same three sections, and **any section you
don't need can be left out**.

A working example lives at [`configs/sample-deck.json`](https://github.com/padraiglennon/common-file-generator/blob/main/configs/sample-deck.json).

```json
{
  "text":   { ... },
  "tables": [ ... ],
  "media":  [ ... ]
}
```

> JSON does not allow comments. This guide explains each field instead - keep it
> open beside your data file while you edit.

## 1. `text` - fill in words

A list of name -> value pairs. The **name** matches a tag you placed in the
template (see the [template guide](golden-file-guide.md)); the **value** is the
text that replaces it.

```json
"text": {
  "title": "Q3 Business Review",
  "author": "A. Non"
}
```

In PowerPoint and Word, the tag in the template looks like `{{title}}`.
In Excel, the tag is a **defined name** called `title`.

## 2. `tables` - fill in rows of data

A list of tables. Each table has:

| Field    | Required | What it is                                                    |
| -------- | -------- | ------------------------------------------------------------- |
| `name`   | yes      | The name of the table tag in the template.                    |
| `header` | no       | A single row of column titles, written first.                 |
| `rows`   | yes      | The data rows. Each row is a list of cell values.             |

```json
"tables": [
  {
    "name": "RevenueTable",
    "header": ["Region", "Q2", "Q3"],
    "rows": [
      ["North", "120", "138"],
      ["South", "98",  "101"]
    ]
  }
]
```

If you provide **more rows or columns than the template table has room for**,
the extra data is skipped and the report file tells you exactly what was left
out - nothing crashes.

## 3. `media` - add pictures

A list of images. Each has:

| Field  | Required | What it is                                                  |
| ------ | -------- | ----------------------------------------------------------- |
| `name` | yes      | The name of the picture tag in the template.                |
| `path` | yes      | Where the image file is, relative to this data file.        |

```json
"media": [
  { "name": "Logo", "path": "../assets/sample-logo.png" }
]
```

If the image file can't be found, the report file says so and the rest of the
file is still produced.

## What happens if something doesn't match?

Nothing is ever lost silently. After every run a **report file** is written next
to your output (for `out.pptx` you get `out.report.txt`). It is written in plain
English, for example:

```
  - [WARNING] tables.RevenueTable: you provided 6 rows but the template table
    holds 4; kept the first 4.
  - [ERROR] media.Logo: image file not found: assets/sample-logo.png.
```

Read it, fix the data file or the template, and run again.
