# Workflow: Add Recipe

## Objective
Ingest a new recipe from text, a URL, or a file and store it in `kitchen.db` with its ingredient list linked.

## When to Use
- Adding a dish you want to be able to cook
- Bulk-importing recipes at setup time
- Updating an existing recipe (re-running with the same recipe name overwrites it)

## Required Inputs
One of:
| Input | Description |
|---|---|
| `--text` | Recipe as plain text pasted directly |
| `--url` | URL of a recipe webpage |
| `--file` | Path to a `.txt` file containing the recipe |

## Steps

1. **From text:**
   ```
   .venv/Scripts/python tools/add_recipe.py --text "Chicken Fried Rice\n\nIngredients:\n- chicken breast\n- rice\n- soy sauce\n- egg\n- garlic\n\nInstructions: ..."
   ```

2. **From URL:**
   ```
   .venv/Scripts/python tools/add_recipe.py --url "https://www.recipepage.com/chicken-fried-rice"
   ```

3. **From file:**
   ```
   .venv/Scripts/python tools/add_recipe.py --file recipes/chicken_fried_rice.txt
   ```

## What Claude Extracts
- Recipe name
- Full instructions (as a single block)
- Ingredient list (base ingredient names only, e.g. "garlic" not "3 cloves of garlic")
- Optional flag per ingredient (only if explicitly marked optional in the recipe)

## Notes
- Ingredient names are normalized to lowercase. "Chicken Breast" and "chicken breast" are the same.
- If an ingredient doesn't exist in the DB yet, it is added with `in_stock=0` (out of stock by default).
- Re-running with the same recipe name updates the recipe and re-links ingredients.
- For optional garnishes or toppings, Claude marks them `is_optional=true` — they won't block a recipe from appearing in "can cook now".

## Output
- Recipe row written to `recipes` table.
- Ingredient rows written/updated in `ingredients` table.
- Link rows written to `recipe_ingredients` table.
- Console confirms recipe name and ingredient count.
