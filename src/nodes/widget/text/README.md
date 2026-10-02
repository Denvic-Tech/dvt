# Text

Node type: `Text`.

## Purpose and selection

Place explanatory text on the graph canvas, for section labels or context for readers.

## Inputs and configuration

Set `text_content`; styling uses `font_family`, `font_size` (8–72, default 14), `font_weight`, `font_style`, `text_color`, `background_color`, `border_width`, `border_color`, `text_align`. Defaults are Arial, normal, left-aligned, black text and transparent background.

## Outputs

A visual widget; it produces no business-data result.

## Behavior and limitations

Its process method is empty. Text and styling explain the graph but do not establish execution dependencies, filter data or supply variable values.

## Examples

Place this widget near the relevant nodes. The canvas displays the label; pipeline data is unaffected.

Parameter values, without an MCP patch envelope:

```json
{
  "text_content": "Orders → validation → warehouse",
  "font_size": 18,
  "font_weight": "bold"
}
```

## Common errors

Missing computation: use a processing node rather than a widget. Invalid style values: inspect the current definition's allowed enums and numeric bounds.
