# Workflow: Daily Recipe Suggestions

## Objective
Present a filtered list of cookable recipes based on current kitchen stock and whether today is a WFH day. After selection, update the stock.

## When to Use
- Each morning to decide what to cook
- Any time you want to see what's cookable from current stock

## Steps

1. **Run the daily agent**
   ```
   .venv/Scripts/python tools/daily_suggestions.py
   ```

2. **The agent will:**
   - Check Google Calendar for WFH signals on today's date
   - Query the DB for recipe matches (deterministic)
   - Display filtered recipe list:
     - **Always shown**: recipes where ALL required ingredients are in stock
     - **WFH only**: recipes where some required ingredients are missing (you can shop)
   - Prompt you to select a recipe
   - Show cooking instructions
   - Ask to confirm stock deduction

3. **Select a recipe** by entering its number, or press Enter to skip.

4. **After cooking**, confirm stock update — required ingredients are marked `in_stock=0`.

## Override Flags
| Flag | Effect |
|---|---|
| `--force-wfh` | Treat today as WFH regardless of calendar |
| `--skip-calendar` | Skip calendar check, use strictest filter (non-WFH mode) |

```
.venv/Scripts/python tools/daily_suggestions.py --force-wfh
.venv/Scripts/python tools/daily_suggestions.py --skip-calendar
```

## WFH Detection Logic
The calendar tool looks for these keywords in event titles/descriptions:

| Signal | Keywords |
|---|---|
| WFH (show shop-first recipes) | `wfh`, `work from home`, `working from home`, `remote`, `home office` |
| Office (hide shop-first recipes) | `office`, `onsite`, `on-site`, `on site`, `in office` |

If no events are found today, defaults to **non-WFH** (strictest — only cook-now recipes shown).

## Recipe Filtering Rules
| Condition | Shown |
|---|---|
| All required ingredients in stock | Always |
| Missing optional ingredients only | Always (noted in display) |
| Missing 1+ required ingredients | Only on WFH days |
| Missing 1+ required ingredients | Hidden on non-WFH days |

## After Cooking
- Required ingredients are marked `in_stock=0`
- Optional ingredients are left unchanged
- Run CV tool or manual stock update to restock before next use

## Troubleshooting
- **Calendar auth error**: Run `python tools/check_calendar.py` once to complete OAuth flow
- **No recipes shown**: Check stock with `python tools/update_stock.py --list`, add recipes with `add_recipe.py`
- **Wrong WFH detection**: Add a calendar event with "WFH" in the title for today, or use `--force-wfh`
