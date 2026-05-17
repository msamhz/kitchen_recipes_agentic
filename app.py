"""
Kitchen Agent — NiceGUI Frontend
----------------------------------
Central UI for all kitchen agent tools.

Run with:  .venv/Scripts/python app.py
Opens at:  http://localhost:8181
"""

import asyncio
import os
import socket
import sys
import urllib3
from datetime import date, timedelta
from pathlib import Path

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))

from nicegui import ui, events, app as nicegui_app
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from db_init import init_db, get_connection
from cv_to_ingredients import identify_ingredients_async, resolve_uncertain_async, deduplicate_async, upsert_ingredients
from match_recipes import match_recipes
from update_stock import mark_recipe_cooked, mark_ingredients, get_required_ingredients
from add_recipe import run as add_recipe_run
from build_shopping_list import build_list
from generate_aliases import run_async as generate_aliases_async

try:
    from check_calendar import check_wfh
    CALENDAR_AVAILABLE = True
except Exception:
    CALENDAR_AVAILABLE = False

TMP_DIR = Path(".tmp")
TMP_DIR.mkdir(exist_ok=True)

# DB init runs once at startup — idempotent, won't touch existing data
init_db()

@nicegui_app.on_startup
async def _startup_aliases():
    await generate_aliases_async(new_only=True)

if sys.platform == "win32":
    # WinError 10054: remote closes HTTP connection during ProactorEventLoop socket teardown.
    # Purely cosmetic on Windows — suppress so it doesn't spam the console.
    def _suppress_proactor_pipe_errors(loop, context):
        exc = context.get("exception")
        if isinstance(exc, (ConnectionResetError, OSError)) and "connection_lost" in context.get("message", ""):
            return
        loop.default_exception_handler(context)

    @nicegui_app.on_startup
    async def _configure_loop():
        asyncio.get_event_loop().set_exception_handler(_suppress_proactor_pipe_errors)

# ── Access logger middleware ───────────────────────────────────────────────────
class _AccessLog(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        ip = request.client.host if request.client else "?"
        path = request.url.path
        if not path.startswith("/_nicegui"):          # skip internal WS/asset noise
            print(f"[Access] {ip}  {request.method}  {path}")
        return await call_next(request)

nicegui_app.add_middleware(_AccessLog)

# ── Startup: print all LAN addresses ─────────────────────────────────────────
def _print_network_info():
    hostname = socket.gethostname()
    print(f"\n{'─'*52}")
    print(f"  Kitchen Agent  —  http://localhost:8181")
    try:
        addrs = socket.getaddrinfo(hostname, None)
        seen = set()
        for item in addrs:
            ip = item[4][0]
            if ip not in seen and not ip.startswith("127.") and ":" not in ip:
                print(f"  LAN              http://{ip}:8181")
                seen.add(ip)
    except Exception:
        pass
    print(f"{'─'*52}\n")

_print_network_info()

# ── Shared calendar cache (all browser sessions read from this) ───────────────
# Keyed by date. Populated on first load; resets when app.py restarts.
_wfh_global_cache: dict[date, bool] = {}

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
                    dest = TMP_DIR / e.file.name
                    dest.write_bytes(await e.file.read())
                    uploaded_paths.append(str(dest))
                    with file_list:
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("image", size="1rem").style(f"color: {GREEN};")
                            ui.label(e.file.name).style("color:#e0e0f0; font-size:0.85rem;")

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
        results_panel = ui.card().style(CARD).classes("w-full")
        results_panel.set_visibility(False)
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
                results_panel.set_visibility(False)
                uploaded_paths.clear(); checkbox_refs.clear(); extra_items.clear()
                checklist_col.clear(); extras_col.clear()
                scan_status.set_text("")
                asyncio.ensure_future(generate_aliases_async(new_only=True))

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=lambda: results_panel.set_visibility(False)).props("flat").style("color:#ff6b6b;")
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

                # Deduplicate against existing DB names (merges near-identical detected names)
                scan_status.set_text("Deduplicating ingredient names...")
                conn = get_connection()
                cur = conn.cursor()
                cur.execute("SELECT name FROM ingredients")
                existing_names = [r["name"] for r in cur.fetchall()]
                conn.close()
                final_candidates = await deduplicate_async(final_candidates, existing_names)

                with checklist_col:
                    for name in final_candidates:
                        cb = ui.checkbox(name, value=True).style("color:#e0e0f0;")
                        cb.props("color=positive keep-color")
                        checkbox_refs[name] = cb

                count_lbl.set_text(f"{len(final_candidates)} ingredient(s) detected")
                results_panel.set_visibility(True)
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
                    ).classes("w-full mt-2").style("color:#e0e0f0;")
                    recipe_url.set_visibility(False)

                    def toggle_method():
                        if input_method.value == "text":
                            recipe_text.set_visibility(True)
                            recipe_url.set_visibility(False)
                        else:
                            recipe_text.set_visibility(False)
                            recipe_url.set_visibility(True)

                    input_method.on_value_change(toggle_method)

                    add_status = ui.label("").style(MUTED + " margin-top:0.5rem;")

                    async def do_add():
                        if input_method.value == "text":
                            if not recipe_text.value.strip():
                                ui.notify("Paste some recipe text first.", color="warning")
                                return
                        else:
                            url_val = recipe_url.value.strip()
                            if not url_val:
                                ui.notify("Enter a URL first.", color="warning")
                                return
                            if not url_val.startswith(("http://", "https://")):
                                ui.notify("URL must start with http:// or https://", color="warning")
                                return

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
                            asyncio.create_task(generate_aliases_async(new_only=True))
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
                        SELECT r.id, r.name, r.source, r.created_at, r.difficulty, r.prep_time,
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
                                    with ui.column().classes("gap-1"):
                                        with ui.row().classes("items-center gap-2 flex-wrap"):
                                            ui.label(r["name"]).style(TEXT + " font-weight:600;")
                                            _diff_time_badges({"difficulty": r["difficulty"], "prep_time": r["prep_time"]})
                                        src = f" · {r['source'][:40]}..." if r["source"] else ""
                                        ui.label(f"{r['ing_count']} ingredients{src}").style(MUTED)
                                    with ui.row().classes("items-center gap-2"):
                                        ui.label(f"#{r['id']}").style("color:#3a5a8a; font-size:0.8rem;")

                                        def delete_recipe(rid=r["id"], rname=r["name"]):
                                            conn2 = get_connection()
                                            conn2.execute("DELETE FROM recipes WHERE id = ?", (rid,))
                                            conn2.commit()
                                            conn2.close()
                                            ui.notify(f"Deleted '{rname}'", color="warning")
                                            load_recipes()

                                        ui.button(icon="delete", on_click=delete_recipe).props("flat round dense").style("color:#ff6b6b; font-size:0.8rem;")

                load_recipes()
                ui.button("Refresh", icon="refresh", on_click=load_recipes).props("flat").style(f"color:#a0a0b0; margin-top:0.5rem;")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — TODAY'S MEALS
# ══════════════════════════════════════════════════════════════════════════════

def today_tab():
    today = date.today()
    week_days = [today + timedelta(days=i) for i in range(7)]

    selected_date = {"value": today}
    wfh_cache: dict[date, bool] = {}
    diff_filter: dict = {"value": _ALL_DIFFS.copy()}  # reset per WFH state

    with ui.column().classes("w-full gap-4"):
        section_heading("Today's Meals", "today")

        # ── Week date selector ───────────────────────────────────────────────
        with ui.card().style(CARD).classes("w-full"):
            ui.label("Select day").style(MUTED)

            def style_day_btn(d: date):
                is_selected = d == selected_date["value"]
                wfh = wfh_cache.get(d)
                if wfh is True:
                    color, bg_dim = GREEN, "#1e3a2a"
                elif wfh is False:
                    color, bg_dim = AMBER, "#3a2e1a"
                else:
                    color, bg_dim = BLUE, "#2a2a4a"
                if is_selected:
                    return (f"background:{color} !important; color:white !important;"
                            f" border-radius:8px; min-width:56px; font-weight:700;")
                else:
                    return (f"background:{bg_dim} !important; color:{color} !important;"
                            f" border-radius:8px; min-width:56px; border:1px solid {color}66;")

            btn_container = ui.row().classes("gap-2 flex-wrap")

            def rebuild_buttons():
                btn_container.clear()
                with btn_container:
                    for d in week_days:
                        (
                            ui.button(f"{d.strftime('%a')}\n{d.day}", on_click=lambda day=d: select_day(day), color=None)
                            .style(style_day_btn(d))
                            .props("unelevated")
                        )

            rebuild_buttons()

            async def select_day(d: date):
                selected_date["value"] = d
                rebuild_buttons()
                wfh = wfh_cache.get(d)
                if wfh is not None:
                    wfh_toggle.set_value(wfh)
                    diff_filter["value"] = _ALL_DIFFS.copy() if wfh else {"easy"}
                    day_label = "today" if d == today else d.strftime("%a %d %b")
                    cal_lbl.set_text(f"{'WFH' if wfh else 'Office'} — {day_label}")
                load_suggestions()

            ui.separator().style("background:#2a2a4a; margin:0.5rem 0;")

            with ui.row().classes("items-center gap-4 flex-wrap"):
                wfh_toggle = ui.switch("WFH", value=False).style("color:#e0e0f0;")

                def _on_wfh_change(e):
                    diff_filter["value"] = _ALL_DIFFS.copy() if e.value else {"easy"}
                    load_suggestions()

                wfh_toggle.on_value_change(_on_wfh_change)
                cal_lbl = ui.label("Checking calendar for the week...").style(MUTED)

        # ── Suggestions ──────────────────────────────────────────────────────
        suggestions_col = ui.column().classes("w-full gap-3")

        def load_suggestions():
            suggestions_col.clear()
            results = match_recipes()
            wfh = wfh_toggle.value
            allowed = diff_filter["value"]

            def _apply(recipes):
                filtered = [r for r in recipes
                            if r.get("difficulty") in allowed or r.get("difficulty") is None]
                return _sort_recipes(filtered)

            can_cook = _apply(results["can_cook"])
            can_shop = _apply(results["can_shop"])

            with suggestions_col:
                # ── Filter chips ─────────────────────────────────────────────
                with ui.row().classes("items-center gap-1 flex-wrap"):
                    ui.label("Difficulty:").style(MUTED + " font-size:0.78rem;")
                    for diff in ("easy", "medium", "hard"):
                        is_active = diff in allowed
                        fg, bg = _DIFF_STYLE[diff]
                        chip_style = (
                            f"background:{fg} !important; color:white !important;"
                            if is_active else
                            f"background:#1e1e2e !important; color:{fg} !important; border:1px solid {fg}55;"
                        ) + " border-radius:6px; font-size:0.78rem; padding:0 0.6rem; min-height:28px;"

                        def _toggle(d=diff):
                            if d in diff_filter["value"] and len(diff_filter["value"]) > 1:
                                diff_filter["value"].discard(d)
                            else:
                                diff_filter["value"].add(d)
                            load_suggestions()

                        ui.button(diff.capitalize(), on_click=_toggle, color=None).props("unelevated dense").style(chip_style)

                # ── Cook Now ─────────────────────────────────────────────────
                with ui.column().classes("w-full gap-2"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("check_circle", size="1.2rem").style(f"color:{GREEN};")
                        ui.label(f"Cook Now  ({len(can_cook)})").style(f"color:{GREEN}; font-weight:700;")
                    if can_cook:
                        for r in can_cook:
                            _recipe_card(r, cookable=True, refresh_fn=load_suggestions)
                    else:
                        ui.label("No cookable recipes match the current filter.").style(MUTED)

                # ── Can Shop ─────────────────────────────────────────────────
                ui.separator().style("background:#2a2a4a;")
                with ui.column().classes("w-full gap-2"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("shopping_cart", size="1.2rem").style(f"color:{AMBER};")
                        ui.label(f"Can Cook If You Shop  ({len(can_shop)})").style(f"color:{AMBER}; font-weight:700;")
                    if can_shop:
                        for r in can_shop:
                            _recipe_card(r, cookable=False, refresh_fn=load_suggestions)
                    else:
                        ui.label("Nothing missing — you're fully stocked!").style(MUTED)

        # ── Parallel calendar check for all 7 days ───────────────────────────
        async def check_all_days():
            if not CALENDAR_AVAILABLE:
                cal_lbl.set_text("No calendar — toggle WFH manually")
                load_suggestions()
                return
            for d in week_days:
                if d in _wfh_global_cache:
                    wfh_cache[d] = _wfh_global_cache[d]
                    rebuild_buttons()
                    if d == today:
                        wfh_toggle.set_value(wfh_cache[d])
                        cal_lbl.set_text(f"{'WFH' if wfh_cache[d] else 'Office'} — today (cached)")
                    continue
                try:
                    result = await asyncio.to_thread(check_wfh, d)
                    _wfh_global_cache[d] = result
                    wfh_cache[d] = result
                    rebuild_buttons()
                    if d == today:
                        wfh_toggle.set_value(result)
                        cal_lbl.set_text(f"{'WFH' if result else 'Office'} — today")
                except Exception as e:
                    print(f"[Calendar] Error checking {d}: {e}")
            load_suggestions()

        ui.timer(0.5, check_all_days, once=True)


_DIFF_STYLE = {
    "easy":   (GREEN,   "#1e3a2a"),
    "medium": (AMBER,   "#3a2e1a"),
    "hard":   ("#ff6b6b", "#3a1a1a"),
}
_TIME_LABEL = {"under_10": "<10 min", "10_to_20": "10–20 min", "over_20": ">20 min"}
_DIFF_ORDER = {"easy": 0, "medium": 1, "hard": 2}
_TIME_ORDER = {"under_10": 0, "10_to_20": 1, "over_20": 2}
_ALL_DIFFS = {"easy", "medium", "hard"}


def _sort_recipes(recipes: list) -> list:
    return sorted(recipes, key=lambda r: (
        _DIFF_ORDER.get(r.get("difficulty"), 3),
        _TIME_ORDER.get(r.get("prep_time"), 3),
    ))


def _diff_time_badges(recipe: dict):
    diff = recipe.get("difficulty")
    time = recipe.get("prep_time")
    if diff and diff in _DIFF_STYLE:
        fg, bg = _DIFF_STYLE[diff]
        ui.label(diff.capitalize()).style(
            f"background:{bg}; color:{fg}; border:1px solid {fg}55;"
            " border-radius:4px; padding:1px 6px; font-size:0.72rem; font-weight:600;"
        )
    if time and time in _TIME_LABEL:
        ui.label(_TIME_LABEL[time]).style(
            "background:#2a2a4a; color:#4a9eff; border:1px solid #3a5a8a55;"
            " border-radius:4px; padding:1px 6px; font-size:0.72rem;"
        )


def _recipe_card(recipe: dict, cookable: bool, refresh_fn):
    with ui.card().style(CARD2).classes("w-full"):
        with ui.row().classes("items-start justify-between w-full gap-2"):
            with ui.column().classes("gap-1 flex-1"):
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    ui.label(recipe["name"]).style(TEXT + " font-weight:600; font-size:1rem;")
                    _diff_time_badges(recipe)

                if recipe.get("have"):
                    ui.label(f"Have: {', '.join(recipe['have'])}").style(f"color:{GREEN}; font-size:0.82rem;")

                if recipe.get("missing_required"):
                    ui.label(f"Buy: {', '.join(recipe['missing_required'])}").style(f"color:{AMBER}; font-size:0.82rem;")

                if recipe.get("missing_optional"):
                    ui.label(f"Optional: {', '.join(recipe['missing_optional'])}").style(MUTED + " font-size:0.82rem;")

            if cookable:
                def open_cooked_dialog(rid=recipe["id"], rname=recipe["name"]):
                    ingredients = get_required_ingredients(rid)

                    with ui.dialog() as dlg, ui.card().style(CARD + " min-width:340px; max-width:480px;"):
                        ui.label(f"Mark as cooked: {rname}").style(TEXT + " font-weight:600; font-size:1rem;")
                        ui.label("Untick items you still have remaining:").style(MUTED + " font-size:0.82rem; margin-bottom:0.25rem;")

                        checks: dict[str, dict] = {}
                        for ing in ingredients:
                            dname = ing["display_name"]
                            sname = ing["stocked_name"]
                            cb = ui.checkbox(dname, value=bool(sname)).style("color:#e0e0f0;")
                            if not sname:
                                cb.props("disable")
                            checks[dname] = {"cb": cb, "stocked_name": sname}

                        with ui.row().classes("w-full justify-end gap-2 mt-2"):
                            ui.button("Cancel", on_click=dlg.close).props("flat").style("color:#a0a0b0;")

                            def confirm(d=dlg, rn=rname, c=checks):
                                to_deplete = [
                                    info["stocked_name"]
                                    for info in c.values()
                                    if info["cb"].value and info["stocked_name"]
                                ]
                                if to_deplete:
                                    mark_ingredients(to_deplete, in_stock=False)
                                ui.notify(f"'{rn}' cooked — {len(to_deplete)} item(s) removed from stock.", color="positive")
                                d.close()
                                refresh_fn()

                            ui.button("Confirm", icon="done_all", on_click=confirm).props("unelevated").style(
                                f"background:{GREEN}; color:white; border-radius:8px;"
                            )

                    dlg.open()

                ui.button("Mark Cooked", icon="done_all", on_click=open_cooked_dialog).props("unelevated").style(
                    f"background:{GREEN}; color:white; border-radius:8px; white-space:nowrap;"
                )

        # Expandable instructions
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT instructions, source FROM recipes WHERE id = ?", (recipe["id"],))
        row = cur.fetchone()
        conn.close()
        if row and row["instructions"]:
            with ui.expansion("Instructions", icon="receipt_long").style("color:#a0a0b0; width:100%; margin-top:0.25rem;"):
                if row["source"]:
                    ui.link(row["source"], row["source"], new_tab=True).style(
                        "color:#4a9eff; font-size:0.8rem; word-break:break-all; display:block; margin-bottom:0.5rem;"
                    )
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
                            with ui.column().classes("w-full gap-1").style("max-height:260px; overflow-y:auto;"):
                                for r in in_s:
                                    _ingredient_row(r, True, load_stock)

                        if out_s:
                            ui.label(f"OUT OF STOCK  ({len(out_s)})").style("color:#ff6b6b; font-size:0.78rem; font-weight:700; margin-top:0.75rem;")
                            with ui.column().classes("w-full gap-1").style("max-height:200px; overflow-y:auto;"):
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
                active_recipe: dict = {"value": None}  # None = all recipes

                def load_shopping():
                    shopping_col.clear()
                    all_data = build_list()
                    all_recipe_names = all_data["recipes"]

                    with shopping_col:
                        if not all_data["items"]:
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("check_circle", size="1rem").style(f"color:{GREEN};")
                                ui.label("Nothing to buy — all recipes are cookable!").style(MUTED)
                            return

                        # Recipe filter chips — shown only when >1 recipe needs shopping
                        if len(all_recipe_names) > 1:
                            ui.label("Filter by recipe:").style(MUTED + " font-size:0.78rem;")
                            with ui.row().classes("gap-1 flex-wrap mb-1"):
                                def _make_chip(rname):
                                    is_active = active_recipe["value"] == rname
                                    chip_style = (
                                        f"background:{ACCENT} !important; color:white !important;"
                                        if is_active else
                                        f"background:#2a2a4a !important; color:#a0a0b0 !important;"
                                    ) + " border-radius:6px; font-size:0.78rem; padding:0 0.5rem;"

                                    def _toggle(rn=rname):
                                        active_recipe["value"] = None if active_recipe["value"] == rn else rn
                                        load_shopping()

                                    ui.button(rname, on_click=_toggle, color=None).props("unelevated dense").style(chip_style)

                                for rn in all_recipe_names:
                                    _make_chip(rn)

                        # Items scoped to active filter
                        data = build_list(recipe_filter=[active_recipe["value"]]) if active_recipe["value"] else all_data
                        items = data["items"]

                        ui.separator().style("background:#2a2a4a; margin:0.25rem 0;")

                        for item in items:
                            with ui.row().classes("items-start gap-2 py-1"):
                                ui.icon("radio_button_unchecked", size="1rem").style(f"color:{AMBER}; flex-shrink:0; margin-top:2px;")
                                with ui.column().classes("gap-0"):
                                    ui.label(item["ingredient"]).style("color:#e0e0f0; font-size:0.9rem;")
                                    if not active_recipe["value"]:
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
    port=8181,
    reload=False,
    show=True,
    dark=True,
    favicon="🍳",
)
