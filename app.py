"""
Kitchen Agent — NiceGUI Frontend
----------------------------------
Central UI for all kitchen agent tools.

Run with:  .venv/Scripts/python app.py
Opens at:  http://localhost:8080
"""

import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))

from nicegui import ui, events

from db_init import init_db, get_connection
from cv_to_ingredients import identify_ingredients_async, resolve_uncertain_async, upsert_ingredients
from match_recipes import match_recipes
from update_stock import mark_recipe_cooked, mark_ingredients
from add_recipe import run as add_recipe_run
from build_shopping_list import build_list

try:
    from check_calendar import check_wfh
    CALENDAR_AVAILABLE = True
except Exception:
    CALENDAR_AVAILABLE = False

TMP_DIR = Path(".tmp")
TMP_DIR.mkdir(exist_ok=True)

# DB init runs once at startup — idempotent, won't touch existing data
init_db()

# ── Style constants ────────────────────────────────────────────────────────────
BG = "#0f0f1a"
CARD = "background: #1a1a2e; border-radius: 12px; padding: 1.25rem;"
CARD2 = "background: #2a2a4a; border-radius: 8px; padding: 0.75rem 1rem;"
ACCENT = "#e94560"
BLUE = "#3a5a8a"
GREEN = "#4caf50"
AMBER = "#ffb74d"
TEXT = "color: #e0e0f0;"
MUTED = "color: #a0a0b0; font-size: 0.85rem;"
LABEL = f"color: {ACCENT}; font-weight: 700; font-size: 1.05rem;"

CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}


def section_heading(text: str, icon_name: str):
    with ui.row().classes("items-center gap-2 mb-1"):
        ui.icon(icon_name, size="1.4rem").style(f"color: {ACCENT};")
        ui.label(text).style(LABEL)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — SCAN KITCHEN
# ══════════════════════════════════════════════════════════════════════════════

def scan_tab():
    uploaded_paths: list[str] = []
    checkbox_refs: dict[str, ui.checkbox] = {}
    extra_items: list[str] = []

    with ui.column().classes("w-full gap-4"):
        section_heading("Scan Kitchen", "photo_camera")

        with ui.row().classes("w-full gap-4 items-start flex-wrap"):

            # ── Upload card ──────────────────────────────────────────────────
            with ui.card().style(CARD).classes("flex-1 min-w-72"):
                ui.label("Upload Photos").style(TEXT + " font-weight:600;")
                ui.label("Drop one or more photos (fridge, pantry, counter)").style(MUTED)

                file_list = ui.column().classes("w-full gap-1 mt-2")

                async def handle_upload(e: events.UploadEventArguments):
                    dest = TMP_DIR / e.name
                    dest.write_bytes(e.content.read())
                    uploaded_paths.append(str(dest))
                    with file_list:
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("image", size="1rem").style(f"color: {GREEN};")
                            ui.label(e.name).style("color:#e0e0f0; font-size:0.85rem;")

                ui.upload(
                    multiple=True,
                    auto_upload=True,
                    on_upload=handle_upload,
                ).props("accept='.jpg,.jpeg,.png,.webp' flat bordered").classes("w-full mt-2")

            # ── Mode + controls card ─────────────────────────────────────────
            with ui.card().style(CARD).classes("min-w-52"):
                ui.label("Scan Mode").style(TEXT + " font-weight:600;")
                mode = ui.radio(
                    options={"update": "Update  (add to stock)", "restock": "Restock  (replace all)"},
                    value="update",
                ).style("color:#e0e0f0;")

                ui.separator().style("background:#2a2a4a; margin:0.5rem 0;")

                scan_btn = ui.button("Scan Now", icon="search").props("unelevated").style(
                    f"background:{ACCENT}; color:white; width:100%; border-radius:8px;"
                )
                scan_status = ui.label("").style(MUTED)

        # ── Results panel (hidden until scan completes) ──────────────────────
        results_panel = ui.card().style(CARD + " display:none;").classes("w-full")
        with results_panel:
            with ui.row().classes("items-center justify-between w-full mb-2"):
                ui.label("Review Detected Ingredients").style(TEXT + " font-weight:600;")
                count_lbl = ui.label("").style(MUTED)

            checklist_col = ui.column().classes("w-full gap-1")
            extras_col = ui.column().classes("w-full gap-1 mt-1")

            ui.separator().style("background:#2a2a4a; margin:0.5rem 0;")
            ui.label("Add missing ingredient").style(MUTED)

            with ui.row().classes("w-full gap-2"):
                add_input = ui.input(placeholder="e.g. fish sauce, tofu...").classes("flex-1").style("color:#e0e0f0;")

                def add_extra():
                    name = add_input.value.strip().lower()
                    if not name or name in extra_items:
                        return
                    extra_items.append(name)
                    with extras_col:
                        with ui.row().classes("items-center gap-2 px-2 py-1 rounded").style("background:#1e3a2a;"):
                            ui.icon("add_circle", size="1rem").style(f"color:{GREEN};")
                            ui.label(name).style("color:#e0e0f0; font-size:0.9rem; flex:1;")
                    add_input.value = ""

                add_input.on("keydown.enter", add_extra)
                ui.button("Add", on_click=add_extra).props("flat").style(f"color:{GREEN};")

            ui.separator().style("background:#2a2a4a; margin:0.5rem 0;")

            def on_confirm():
                final = [n for n, cb in checkbox_refs.items() if cb.value] + extra_items
                if not final:
                    ui.notify("Nothing selected.", color="warning")
                    return
                upsert_ingredients(final, mode=mode.value)
                ui.notify(f"Saved {len(final)} ingredient(s)!", color="positive")
                results_panel.style(CARD + " display:none;")
                uploaded_paths.clear(); checkbox_refs.clear(); extra_items.clear()
                checklist_col.clear(); extras_col.clear()
                scan_status.set_text("")

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=lambda: results_panel.style(CARD + " display:none;")).props("flat").style("color:#ff6b6b;")
                ui.button("Confirm & Save", icon="check", on_click=on_confirm).props("unelevated").style(
                    f"background:{ACCENT}; color:white; border-radius:8px;"
                )

        # ── Scan logic ───────────────────────────────────────────────────────
        async def do_scan():
            if not uploaded_paths:
                ui.notify("Upload at least one image first.", color="warning")
                return

            scan_btn.disable()
            scan_status.set_text("Scanning images in parallel...")
            checkbox_refs.clear(); extra_items.clear()
            checklist_col.clear(); extras_col.clear()

            try:
                all_results = await asyncio.gather(*[identify_ingredients_async(p) for p in uploaded_paths])

                all_ingredients, all_uncertain = [], []
                for r in all_results:
                    all_ingredients.extend(r.get("ingredients", []))
                    all_uncertain.extend(r.get("uncertain", []))

                seen: dict[str, dict] = {}
                for item in all_ingredients:
                    key = item["name"].strip().lower()
                    if key not in seen or CONFIDENCE_RANK.get(item.get("confidence", "low"), 0) > CONFIDENCE_RANK.get(seen[key].get("confidence", "low"), 0):
                        seen[key] = item

                confirmed, to_resolve = [], []
                for item in seen.values():
                    if item["confidence"] in ("high", "medium"):
                        confirmed.append(item["name"].strip().lower())
                    else:
                        to_resolve.append(item.get("notes", item["name"]))

                deduped_uncertain: list[str] = []
                seen_u: set[str] = set()
                for desc in all_uncertain:
                    if desc.lower() not in seen_u:
                        seen_u.add(desc.lower()); deduped_uncertain.append(desc)
                to_resolve.extend(deduped_uncertain)

                if to_resolve:
                    scan_status.set_text(f"Resolving {len(to_resolve)} uncertain items...")
                    resolved = await asyncio.gather(*[resolve_uncertain_async(d) for d in to_resolve])
                    confirmed.extend([r for r in resolved if r])

                final_candidates = sorted(set(confirmed))

                with checklist_col:
                    for name in final_candidates:
                        cb = ui.checkbox(name, value=True).style("color:#e0e0f0;")
                        cb.props("color=positive keep-color")
                        checkbox_refs[name] = cb

                count_lbl.set_text(f"{len(final_candidates)} ingredient(s) detected")
                results_panel.style(CARD)
                scan_status.set_text(f"Done — review and confirm below")

            except Exception as e:
                ui.notify(f"Scan error: {e}", color="negative")
                scan_status.set_text(f"Error: {e}")
            finally:
                scan_btn.enable()

        scan_btn.on("click", do_scan)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — RECIPES
# ══════════════════════════════════════════════════════════════════════════════

def recipes_tab():
    with ui.column().classes("w-full gap-4"):
        section_heading("Recipes", "menu_book")

        with ui.tabs().classes("w-full") as rtabs:
            t_add = ui.tab("Add Recipe", icon="add_circle")
            t_view = ui.tab("All Recipes", icon="list")

        with ui.tab_panels(rtabs, value=t_add).classes("w-full"):

            # ── Add recipe panel ─────────────────────────────────────────────
            with ui.tab_panel(t_add):
                with ui.card().style(CARD).classes("w-full"):
                    ui.label("Recipe source").style(TEXT + " font-weight:600;")
                    input_method = ui.radio(
                        options={"text": "Paste text", "url": "From URL"},
                        value="text",
                    ).style("color:#e0e0f0;")

                    recipe_text = ui.textarea(
                        placeholder="Paste recipe here — name, ingredients, instructions..."
                    ).classes("w-full mt-2").style("color:#e0e0f0; min-height:160px;")

                    recipe_url = ui.input(
                        placeholder="https://..."
                    ).classes("w-full mt-2").style("color:#e0e0f0; display:none;")

                    def toggle_method():
                        if input_method.value == "text":
                            recipe_text.style("color:#e0e0f0; min-height:160px;")
                            recipe_url.style("color:#e0e0f0; display:none;")
                        else:
                            recipe_text.style("color:#e0e0f0; display:none;")
                            recipe_url.style("color:#e0e0f0;")

                    input_method.on_value_change(toggle_method)

                    add_status = ui.label("").style(MUTED + " margin-top:0.5rem;")

                    async def do_add():
                        add_btn.disable()
                        add_status.set_text("Parsing recipe via Claude...")
                        try:
                            if input_method.value == "text":
                                rid = await asyncio.to_thread(add_recipe_run, text=recipe_text.value)
                            else:
                                rid = await asyncio.to_thread(add_recipe_run, url=recipe_url.value.strip())
                            ui.notify(f"Recipe saved! (id={rid})", color="positive")
                            add_status.set_text(f"Saved as recipe #{rid}")
                            recipe_text.value = ""
                            recipe_url.value = ""
                        except Exception as e:
                            ui.notify(f"Error: {e}", color="negative")
                            add_status.set_text(f"Error: {e}")
                        finally:
                            add_btn.enable()

                    add_btn = ui.button("Add Recipe", icon="save", on_click=do_add).props("unelevated").style(
                        f"background:{ACCENT}; color:white; border-radius:8px; margin-top:0.75rem;"
                    )

            # ── View all recipes panel ────────────────────────────────────────
            with ui.tab_panel(t_view):
                recipes_col = ui.column().classes("w-full gap-2")

                def load_recipes():
                    recipes_col.clear()
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT r.id, r.name, r.source, r.created_at,
                               COUNT(ri.ingredient_id) as ing_count
                        FROM recipes r
                        LEFT JOIN recipe_ingredients ri ON ri.recipe_id = r.id
                        GROUP BY r.id ORDER BY r.name
                    """)
                    rows = cur.fetchall()
                    conn.close()

                    with recipes_col:
                        if not rows:
                            ui.label("No recipes yet. Add one!").style(MUTED)
                            return
                        for r in rows:
                            with ui.card().style(CARD2).classes("w-full"):
                                with ui.row().classes("items-center justify-between w-full"):
                                    with ui.column().classes("gap-0"):
                                        ui.label(r["name"]).style(TEXT + " font-weight:600;")
                                        src = f" · {r['source'][:40]}..." if r["source"] else ""
                                        ui.label(f"{r['ing_count']} ingredients{src}").style(MUTED)
                                    ui.label(f"#{r['id']}").style("color:#3a5a8a; font-size:0.8rem;")

                load_recipes()
                ui.button("Refresh", icon="refresh", on_click=load_recipes).props("flat").style(f"color:#a0a0b0; margin-top:0.5rem;")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — TODAY'S MEALS
# ══════════════════════════════════════════════════════════════════════════════

def today_tab():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week_days = [monday + timedelta(days=i) for i in range(7)]
    DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    selected_date = {"value": today}
    wfh_state = {"value": False}

    with ui.column().classes("w-full gap-4"):
        section_heading("Today's Meals", "today")

        # ── Week date selector ───────────────────────────────────────────────
        with ui.card().style(CARD).classes("w-full"):
            ui.label("Select day").style(MUTED)

            day_buttons: dict[date, ui.button] = {}

            def style_day_btn(d: date):
                is_selected = d == selected_date["value"]
                is_today = d == today
                if is_selected:
                    return f"background:{ACCENT}; color:white; border-radius:8px; min-width:52px;"
                elif is_today:
                    return f"background:#2a2a4a; color:{ACCENT}; border-radius:8px; min-width:52px; border:1px solid {ACCENT};"
                else:
                    return "background:#2a2a4a; color:#a0a0b0; border-radius:8px; min-width:52px;"

            async def select_day(d: date):
                selected_date["value"] = d
                # Re-style all buttons
                for dd, btn in day_buttons.items():
                    btn.style(style_day_btn(dd))
                await check_and_load(d)

            with ui.row().classes("gap-2 flex-wrap"):
                for i, d in enumerate(week_days):
                    label = f"{DAY_NAMES[i]}\n{d.day}"
                    btn = ui.button(label, on_click=lambda _, day=d: asyncio.ensure_future(select_day(day)))
                    btn.style(style_day_btn(d))
                    btn.props("unelevated")
                    day_buttons[d] = btn

            ui.separator().style("background:#2a2a4a; margin:0.5rem 0;")

            # WFH status row
            with ui.row().classes("items-center gap-4 flex-wrap"):
                wfh_toggle = ui.switch("WFH", value=False).style("color:#e0e0f0;")
                wfh_toggle.on_value_change(lambda e: wfh_state.update({"value": e.value}) or load_suggestions())
                cal_lbl = ui.label("Checking calendar...").style(MUTED)

        # ── Suggestions ──────────────────────────────────────────────────────
        suggestions_col = ui.column().classes("w-full gap-3")

        def load_suggestions():
            suggestions_col.clear()
            results = match_recipes()
            wfh = wfh_toggle.value

            with suggestions_col:
                with ui.column().classes("w-full gap-2"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("check_circle", size="1.2rem").style(f"color:{GREEN};")
                        ui.label(f"Cook Now  ({len(results['can_cook'])})").style(f"color:{GREEN}; font-weight:700;")
                    if results["can_cook"]:
                        for r in results["can_cook"]:
                            _recipe_card(r, cookable=True, refresh_fn=load_suggestions)
                    else:
                        ui.label("No cookable recipes — scan your kitchen or add recipes.").style(MUTED)

                if wfh:
                    ui.separator().style("background:#2a2a4a;")
                    with ui.column().classes("w-full gap-2"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("shopping_cart", size="1.2rem").style(f"color:{AMBER};")
                            ui.label(f"Can Cook If You Shop  ({len(results['can_shop'])})").style(f"color:{AMBER}; font-weight:700;")
                        if results["can_shop"]:
                            for r in results["can_shop"]:
                                _recipe_card(r, cookable=False, refresh_fn=load_suggestions)
                        else:
                            ui.label("Nothing missing — you're fully stocked!").style(MUTED)

        # ── Calendar check + auto-load ────────────────────────────────────────
        async def check_and_load(target: date):
            cal_lbl.set_text("Checking calendar...")
            if CALENDAR_AVAILABLE:
                try:
                    is_wfh = await asyncio.to_thread(check_wfh, target)
                    wfh_toggle.set_value(is_wfh)
                    wfh_state["value"] = is_wfh
                    day_label = "today" if target == today else target.strftime("%a %d %b")
                    cal_lbl.set_text(f"{'WFH' if is_wfh else 'Office'} — {day_label}")
                except Exception:
                    cal_lbl.set_text("Calendar unavailable — toggle manually")
            else:
                cal_lbl.set_text("No calendar — toggle WFH manually")
            load_suggestions()

        # Auto-run on page load
        ui.timer(0.5, lambda: asyncio.ensure_future(check_and_load(today)), once=True)


def _recipe_card(recipe: dict, cookable: bool, refresh_fn):
    with ui.card().style(CARD2).classes("w-full"):
        with ui.row().classes("items-start justify-between w-full gap-2"):
            with ui.column().classes("gap-1 flex-1"):
                ui.label(recipe["name"]).style(TEXT + " font-weight:600; font-size:1rem;")

                if recipe.get("missing_required"):
                    ui.label(f"Buy: {', '.join(recipe['missing_required'])}").style(f"color:{AMBER}; font-size:0.85rem;")

                if recipe.get("missing_optional"):
                    ui.label(f"Optional missing: {', '.join(recipe['missing_optional'])}").style(MUTED)

            if cookable:
                def mark_cooked(rid=recipe["id"], rname=recipe["name"]):
                    mark_recipe_cooked(rid)
                    ui.notify(f"'{rname}' cooked — stock updated.", color="positive")
                    refresh_fn()

                ui.button("Mark Cooked", icon="done_all", on_click=mark_cooked).props("unelevated").style(
                    f"background:{GREEN}; color:white; border-radius:8px; white-space:nowrap;"
                )

        # Expandable instructions
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT instructions FROM recipes WHERE id = ?", (recipe["id"],))
        row = cur.fetchone()
        conn.close()
        if row and row["instructions"]:
            with ui.expansion("Instructions", icon="receipt_long").style("color:#a0a0b0; width:100%; margin-top:0.25rem;"):
                ui.label(row["instructions"]).style("color:#c0c0d0; font-size:0.88rem; white-space:pre-wrap;")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — STOCK & SHOPPING
# ══════════════════════════════════════════════════════════════════════════════

def stock_tab():
    with ui.column().classes("w-full gap-4"):
        section_heading("Stock & Shopping", "inventory_2")

        with ui.row().classes("w-full gap-4 items-start flex-wrap"):

            # ── Ingredient list ──────────────────────────────────────────────
            with ui.card().style(CARD).classes("flex-1 min-w-72"):
                with ui.row().classes("items-center justify-between w-full mb-2"):
                    ui.label("Current Stock").style(TEXT + " font-weight:600;")
                    ui.button(icon="refresh", on_click=lambda: load_stock()).props("flat round dense").style("color:#a0a0b0;")

                stock_col = ui.column().classes("w-full gap-1")

                def load_stock():
                    stock_col.clear()
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("SELECT id, name, in_stock FROM ingredients ORDER BY name")
                    rows = cur.fetchall()
                    conn.close()

                    in_s = [r for r in rows if r["in_stock"]]
                    out_s = [r for r in rows if not r["in_stock"]]

                    with stock_col:
                        if not rows:
                            ui.label("No ingredients yet — scan your kitchen!").style(MUTED)
                            return

                        if in_s:
                            ui.label(f"IN STOCK  ({len(in_s)})").style(f"color:{GREEN}; font-size:0.78rem; font-weight:700; margin-top:0.25rem;")
                            for r in in_s:
                                _ingredient_row(r, True, load_stock)

                        if out_s:
                            ui.label(f"OUT OF STOCK  ({len(out_s)})").style("color:#ff6b6b; font-size:0.78rem; font-weight:700; margin-top:0.75rem;")
                            for r in out_s:
                                _ingredient_row(r, False, load_stock)

                # Add manually
                ui.separator().style("background:#2a2a4a; margin:0.5rem 0;")
                ui.label("Add ingredient manually").style(MUTED)
                with ui.row().classes("w-full gap-2"):
                    manual = ui.input(placeholder="e.g. miso paste").classes("flex-1").style("color:#e0e0f0;")

                    def add_manual():
                        name = manual.value.strip().lower()
                        if not name:
                            return
                        upsert_ingredients([name], mode="update")
                        manual.value = ""
                        load_stock()
                        ui.notify(f"Added: {name}", color="positive")

                    manual.on("keydown.enter", add_manual)
                    ui.button("Add", on_click=add_manual).props("unelevated").style(
                        f"background:{BLUE}; color:white; border-radius:8px;"
                    )

                load_stock()

            # ── Shopping list ────────────────────────────────────────────────
            with ui.card().style(CARD).classes("min-w-64"):
                with ui.row().classes("items-center justify-between w-full mb-2"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("shopping_cart", size="1.2rem").style(f"color:{AMBER};")
                        ui.label("Shopping List").style(TEXT + " font-weight:600;")
                    ui.button(icon="refresh", on_click=lambda: load_shopping()).props("flat round dense").style("color:#a0a0b0;")

                shopping_col = ui.column().classes("w-full gap-1")

                def load_shopping():
                    shopping_col.clear()
                    data = build_list()
                    items = data["items"]
                    recipes = data["recipes"]

                    with shopping_col:
                        if not items:
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("check_circle", size="1rem").style(f"color:{GREEN};")
                                ui.label("Nothing to buy — all recipes are cookable!").style(MUTED)
                            return

                        if recipes:
                            ui.label(f"For: {', '.join(recipes[:2])}{'…' if len(recipes) > 2 else ''}").style(MUTED)

                        ui.separator().style("background:#2a2a4a; margin:0.25rem 0;")

                        for item in items:
                            with ui.row().classes("items-start gap-2 py-1"):
                                ui.icon("radio_button_unchecked", size="1rem").style(f"color:{AMBER}; flex-shrink:0; margin-top:2px;")
                                with ui.column().classes("gap-0"):
                                    ui.label(item["ingredient"]).style("color:#e0e0f0; font-size:0.9rem;")
                                    ui.label(f"→ {', '.join(item['needed_for'])}").style(MUTED)

                load_shopping()


def _ingredient_row(row, in_stk: bool, refresh_fn):
    bg = "#2a2a4a" if in_stk else "#1e1e2e"
    with ui.row().classes("items-center gap-2 px-2 py-1 rounded w-full").style(f"background:{bg};"):
        ui.icon("check" if in_stk else "close", size="0.9rem").style(
            f"color:{GREEN if in_stk else '#ff6b6b'};"
        )
        ui.label(row["name"]).style("color:#e0e0f0; flex:1; font-size:0.88rem;")

        def toggle(name=row["name"], cur=in_stk):
            mark_ingredients([name], in_stock=not cur)
            refresh_fn()

        ui.button(
            "Remove" if in_stk else "Restore",
            on_click=toggle,
        ).props("flat dense").style(
            f"color:{'#ff6b6b' if in_stk else GREEN}; font-size:0.75rem; padding:0 0.25rem;"
        )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PAGE
# ══════════════════════════════════════════════════════════════════════════════

@ui.page("/")
def main_page():
    ui.query("body").style(f"background:{BG}; font-family:'Inter',sans-serif;")

    with ui.header().style("background:#1a1a2e; padding:0.6rem 1.5rem; border-bottom:1px solid #2a2a4a; box-shadow:none;"):
        with ui.row().classes("items-center gap-3"):
            ui.icon("kitchen", size="1.6rem").style(f"color:{ACCENT};")
            ui.label("Kitchen Agent").style("color:#e0e0f0; font-size:1.2rem; font-weight:700;")
            ui.label("AI-powered kitchen management").style("color:#a0a0b0; font-size:0.8rem; margin-left:0.5rem;")

    with ui.tabs().classes("w-full").style("background:#1a1a2e; border-bottom:2px solid #2a2a4a;") as tabs:
        t_scan = ui.tab("Scan Kitchen", icon="photo_camera")
        t_recipes = ui.tab("Recipes", icon="menu_book")
        t_today = ui.tab("Today's Meals", icon="today")
        t_stock = ui.tab("Stock & Shopping", icon="inventory_2")

    with ui.tab_panels(tabs, value=t_scan).classes("w-full").style(f"background:{BG}; padding:1.5rem;"):
        with ui.tab_panel(t_scan):
            scan_tab()
        with ui.tab_panel(t_recipes):
            recipes_tab()
        with ui.tab_panel(t_today):
            today_tab()
        with ui.tab_panel(t_stock):
            stock_tab()


ui.run(
    title="Kitchen Agent",
    port=8080,
    reload=False,
    show=True,
    dark=True,
    favicon="🍳",
)
