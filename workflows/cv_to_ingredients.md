# Workflow: CV to Ingredients DB

## Objective
Take a photo of kitchen contents (counter, fridge, pantry) and update the `ingredients` table in `kitchen.db` with what's visible.

## When to Use
- First-time kitchen setup
- After grocery shopping (use `--mode restock` if the photo represents your FULL current stock)
- Spot-checking what's available without a full restock

## Required Inputs
| Input | Description |
|---|---|
| `--image` | Path to the photo file (JPG, PNG, WebP) |
| `--mode` | `update` (add detected items) or `restock` (replace all stock with photo contents) |

## Steps

1. **Run the CV tool**
   ```
   .venv/Scripts/python tools/cv_to_ingredients.py --image path/to/photo.jpg --mode update
   ```
   For a full restock (photo = entire current kitchen):
   ```
   .venv/Scripts/python tools/cv_to_ingredients.py --image path/to/photo.jpg --mode restock
   ```

2. **Review output** — the tool prints each identified ingredient with confidence level. Items with low confidence are auto-resolved via Claude. Items that cannot be resolved are skipped.

3. **Verify DB** (optional)
   ```
   .venv/Scripts/python tools/update_stock.py --list
   ```

## Mode Behavior
| Mode | Effect |
|---|---|
| `update` | Sets detected items to `in_stock=1`. Leaves everything else unchanged. |
| `restock` | First sets ALL ingredients to `in_stock=0`, then sets detected items to `in_stock=1`. Use this when the photo represents your complete current stock. |

## Edge Cases
- **Blurry or partial labels**: Claude attempts to resolve via context. If it can't, item is skipped — add manually with `python tools/update_stock.py --in "item name"`.
- **Multiple photos**: Run the tool once per photo, all in `update` mode. Use `restock` only on the final photo if it represents the full kitchen.
- **Unknown packaged goods**: Claude will identify by package appearance or brand recognition. If wrong, correct manually.

## Output
- `kitchen.db` `ingredients` table updated with `in_stock=1` for all identified items.
- Console log of every accepted and skipped item.
