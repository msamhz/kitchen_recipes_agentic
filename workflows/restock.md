# Workflow: Restock Kitchen

## Objective
Update the ingredient DB after buying groceries. Take a photo of new purchases (on the table or in the fridge) and sync the DB.

## When to Use
- After returning from grocery shopping
- After a WFH day where you bought missing ingredients

## Two Restock Scenarios

### Scenario A: Partial restock (bought specific items, not replacing everything)
Use `--mode update` — only the items in the photo will be set to `in_stock=1`. Everything else unchanged.

```
.venv/Scripts/python tools/cv_to_ingredients.py --image path/to/groceries.jpg --mode update
```

### Scenario B: Full restock (photo represents your entire current kitchen stock)
Use `--mode restock` — ALL ingredients are first set to `in_stock=0`, then detected items set to `in_stock=1`. This is a clean replacement of your stock state.

```
.venv/Scripts/python tools/cv_to_ingredients.py --image path/to/full_fridge.jpg --mode restock
```

## Recommended Photo Tips
- Good lighting, no motion blur
- For fridge: open fully and capture all shelves in one or two shots
- For countertop items: lay ingredients flat and spread them out
- Include packaging labels in frame where possible — helps Claude identify brands/items

## Multiple Photos (e.g. fridge + pantry)
Take photos separately and run `update` mode for each. Only use `restock` on the last photo if it captures everything remaining.

```
.venv/Scripts/python tools/cv_to_ingredients.py --image fridge.jpg --mode update
.venv/Scripts/python tools/cv_to_ingredients.py --image pantry.jpg --mode update
```

## Verify After Restock
```
.venv/Scripts/python tools/update_stock.py --list
```

## Manual Corrections
If the CV tool missed an item or got one wrong:
```
# Add missing item
.venv/Scripts/python tools/update_stock.py --in "miso paste"

# Remove incorrectly detected item
.venv/Scripts/python tools/update_stock.py --out "mystery item"
```

## After Restocking
Run the daily suggestion agent to see what you can now cook:
```
.venv/Scripts/python tools/daily_suggestions.py
```
