"""
Kitchen Agent — NiceGUI Frontend
----------------------------------
Central UI for all kitchen agent tools.

Run with:  .venv/Scripts/python app.py
Opens at:  http://localhost:8181
"""

import asyncio
import os
import re
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
from normalise import normalise_batch_async, normalise_ingredient_async, get_existing_ingredient_names
from shelf_life import get_default_expiry, get_storage_guess, STORAGE_OPTIONS

try:
    from check_calendar import check_wfh
    CALENDAR_AVAILABLE = True
except Exception:
    CALENDAR_AVAILABLE = False

TMP_DIR = Path(".tmp")
TMP_DIR.mkdir(exist_ok=True)

init_db()

@nicegui_app.on_startup
async def _startup_aliases():
    await generate_aliases_async(new_only=True)

if sys.platform == "win32":
    def _suppress_proactor_pipe_errors(loop, context):
        exc = context.get("exception")
        if isinstance(exc, (ConnectionResetError, OSError)) and "connection_lost" in context.get("message", ""):
            return
        loop.default_exception_handler(context)

    @nicegui_app.on_startup
    async def _configure_loop():
        asyncio.get_event_loop().set_exception_handler(_suppress_proactor_pipe_errors)

class _AccessLog(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        ip = request.client.host if request.client else "?"
        path = request.url.path
        if not path.startswith("/_nicegui"):
            print(f"[Access] {ip}  {request.method}  {path}")
        return await call_next(request)

nicegui_app.add_middleware(_AccessLog)

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

_wfh_global_cache: dict[date, bool] = {}

# ── Style constants ────────────────────────────────────────────────────────────
BG      = "#faf7f2"
CARD    = ("background:#ffffff; border-radius:12px; padding:1.25rem;"
           " border:1px solid #e4ddd4; box-shadow:0 2px 8px rgba(60,40,20,0.07);")
CARD2   = ("background:#fdf9f5; border-radius:8px; padding:0.75rem 1rem;"
           " border:1px solid #e8e2d8;")
ACCENT  = "#c4603a"
BLUE    = "#4a7a9b"
GREEN   = "#5c8a6e"
AMBER   = "#b07830"
TEXT    = "color:#2d2420;"
MUTED   = "color:#9a8a7a; font-size:0.85rem;"
SERIF   = "font-family:'Playfair Display',Georgia,serif;"
LABEL   = f"color:{ACCENT}; font-weight:700; font-size:1.05rem; {SERIF}"

PASTEL_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=DM+Sans:wght@400;500;600&display=swap');

body {
  background: #faf7f2 !important;
  font-family: 'DM Sans', sans-serif !important;
  color: #2d2420 !important;
}

/* ── Header ── */
.q-header {
  background: #ffffff !important;
  border-bottom: 1px solid #e4ddd4 !important;
  box-shadow: 0 1px 6px rgba(60,40,20,0.08) !important;
}

/* ── Tabs ── */
.q-tabs { background: #ffffff !important; border-bottom: 1px solid #e4ddd4 !important; }
.q-tab-panels { background: #faf7f2 !important; }
.q-tab__indicator { background: #c4603a !important; height: 3px !important; }
.q-tab--active .q-tab__label,
.q-tab--active .q-icon { color: #c4603a !important; }
.q-tab:not(.q-tab--active) .q-tab__label,
.q-tab:not(.q-tab--active) .q-icon { color: #9a8a7a !important; }

/* ── Card hover lift ── */
.q-card {
  transition: transform 0.22s ease, box-shadow 0.22s ease !important;
}
.q-card:hover {
  transform: translateY(-4px) !important;
  box-shadow: 0 10px 28px rgba(60,40,20,0.13) !important;
}

/* ── Inner sub-cards: gentler lift ── */
.lift-gentle {
  transition: transform 0.18s ease, box-shadow 0.18s ease !important;
}
.lift-gentle:hover {
  transform: translateY(-2px) !important;
  box-shadow: 0 6px 18px rgba(60,40,20,0.10) !important;
}

/* ── Buttons ── */
.q-btn { border-radius: 8px !important; transition: filter 0.15s ease, transform 0.12s ease !important; }
.q-btn:hover { filter: brightness(0.93); transform: translateY(-1px); }

/* ── Tabs inside recipes section ── */
.q-expansion-item__container { background: transparent !important; }

/* ── Dialog ── */
.q-dialog__backdrop { background: rgba(60,40,20,0.40) !important; }
.q-dialog .q-card {
  background: #ffffff !important;
  border: 1px solid #e4ddd4 !important;
  border-radius: 12px !important;
  box-shadow: 0 12px 40px rgba(60,40,20,0.18) !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: #f0ebe3; border-radius: 4px; }
::-webkit-scrollbar-thumb { background: #c8bfb0; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #a89888; }

/* ── Input fields ── */
.q-field__native, .q-field__input { color: #2d2420 !important; }
.q-field { border-radius: 8px !important; }

/* ── Checkbox / radio ── */
.q-radio__inner, .q-checkbox__inner { color: #c4603a !important; }

/* ── Separator ── */
.q-separator { background: #e4ddd4 !important; }
"""

CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}


def section_heading(text: str, icon_name: str):
    with ui.row().classes("items-center gap-2 mb-2"):
        ui.icon(icon_name, size="1.4rem").style(f"color:{ACCENT};")
        ui.label(text).style(LABEL)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — SCAN KITCHEN
# ══════════════════════════════════════════════════════════════════════════════

def scan_tab():
    uploaded_paths: list[str] = []
    checkbox_refs: dict[str, ui.checkbox] = {}
    extra_items: list[str] = []
    scanned_expiry_dates: dict[str, str | None] = {}
    storage_refs: dict[str, "ui.select"] = {}
    expiry_refs: dict[str, "ui.input"] = {}

    with ui.column().classes("w-full gap-4"):
        section_heading("Scan Kitchen", "photo_camera")

        with ui.row().classes("w-full gap-4 items-start flex-wrap"):

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
                            ui.icon("image", size="1rem").style(f"color:{GREEN};")
                            ui.label(e.file.name).style("color:#5a4a3a; font-size:0.85rem;")

                uploader = ui.upload(
                    multiple=True,
                    auto_upload=True,
                    on_upload=handle_upload,
                ).props("accept='.jpg,.jpeg,.png,.webp' flat bordered").classes("w-full mt-2")

            with ui.card().style(CARD).classes("min-w-52"):
                ui.label("Scan Mode").style(TEXT + " font-weight:600;")
                mode = ui.radio(
                    options={"update": "Update  (add to stock)", "restock": "Restock  (replace all)"},
                    value="update",
                ).style("color:#5a4a3a;")

                ui.separator().classes("my-2")

                scan_btn = ui.button("Scan Now", icon="search").props("unelevated").style(
                    f"background:{ACCENT}; color:white; width:100%; border-radius:8px; font-weight:600;"
                )
                scan_status = ui.label("").style(MUTED)

                async def clear_images():
                    uploaded_paths.clear()
                    file_list.clear()
                    await uploader.run_method("reset")
                    scan_status.set_text("")
                    log_panel.set_visibility(False)
                    scan_log.clear()
                    results_panel.set_visibility(False)
                    checkbox_refs.clear()
                    extra_items.clear()
                    scanned_expiry_dates.clear()
                    storage_refs.clear()
                    expiry_refs.clear()

                ui.button("Clear images", icon="clear_all", on_click=clear_images).props("flat").style(
                    f"color:#9a8a7a; width:100%; margin-top:0.25rem; font-size:0.82rem;"
                )

        # Live backend log — shown while scanning/saving
        log_panel = ui.card().style(CARD2).classes("w-full")
        log_panel.set_visibility(False)
        with log_panel:
            with ui.row().classes("items-center gap-2 mb-1"):
                ui.icon("terminal", size="1rem").style(f"color:{AMBER};")
                ui.label("Backend Log").style(f"color:{AMBER}; font-weight:600; font-size:0.85rem;")
            scan_log = ui.log(max_lines=60).classes("w-full").style(
                "font-family:monospace; font-size:0.78rem; color:#5a4a3a;"
                " background:#fdf6ec; border-radius:6px; padding:0.5rem;"
                " min-height:80px; max-height:220px; overflow-y:auto;"
            )

        results_panel = ui.card().style(CARD).classes("w-full")
        results_panel.set_visibility(False)
        with results_panel:
            with ui.row().classes("items-center justify-between w-full mb-2"):
                ui.label("Review Detected Ingredients").style(TEXT + " font-weight:600;")
                count_lbl = ui.label("").style(MUTED)

            checklist_col = ui.column().classes("w-full gap-1")
            extras_col = ui.column().classes("w-full gap-1 mt-1")

            ui.separator().classes("my-2")
            ui.label("Add missing ingredient").style(MUTED)

            with ui.row().classes("w-full gap-2"):
                add_input = ui.input(placeholder="e.g. fish sauce, tofu...").classes("flex-1").style("color:#2d2420;")

                def add_extra():
                    name = add_input.value.strip().lower()
                    if not name or name in extra_items:
                        return
                    extra_items.append(name)
                    with extras_col:
                        with ui.row().classes("items-center gap-2 px-3 py-1 rounded-lg").style(
                            f"background:#eef6f0; border:1px solid {GREEN}44;"
                        ):
                            ui.icon("add_circle", size="1rem").style(f"color:{GREEN};")
                            ui.label(name).style("color:#2d3a2d; font-size:0.9rem; flex:1;")
                    add_input.value = ""

                add_input.on("keydown.enter", add_extra)
                ui.button("Add", on_click=add_extra).props("flat").style(f"color:{GREEN}; font-weight:600;")

            ui.separator().classes("my-2")

            async def on_confirm():
                # Checklist items are already normalised — just filter checked ones
                confirmed_from_scan = [n for n, cb in checkbox_refs.items() if cb.value]
                # Extra manually-typed items need normalisation
                extra_normalised: list[str] = []
                if extra_items:
                    scan_log.clear()
                    log_panel.set_visibility(True)
                    scan_log.push(f"Normalising {len(extra_items)} manually added item(s)...")
                    extra_normalised = await normalise_batch_async(extra_items, log_fn=scan_log.push)

                final = confirmed_from_scan + extra_normalised
                if not final:
                    ui.notify("Nothing selected.", color="warning")
                    return

                log_panel.set_visibility(True)
                scan_log.push(f"Saving {len(final)} ingredient(s)...")

                # Collect expiry/storage metadata from UI refs
                item_meta: dict[str, dict] = {}
                for name in confirmed_from_scan:
                    stor = storage_refs.get(name)
                    exp = expiry_refs.get(name)
                    item_meta[name] = {
                        "storage_location": stor.value if stor else None,
                        "expiry_date": (exp.value.strip() or None) if exp else None,
                    }

                # Check stock status per ingredient before writing
                conn = get_connection()
                cur = conn.cursor()
                for name in final:
                    cur.execute("SELECT in_stock FROM ingredients WHERE name = ?", (name,))
                    row = cur.fetchone()
                    if row is None:
                        scan_log.push(f"[Stock]  {name}  —  added to stock")
                    elif row["in_stock"]:
                        scan_log.push(f"[Stock]  {name}  —  already in stock")
                    else:
                        scan_log.push(f"[Stock]  {name}  —  was out of stock, restocked")
                conn.close()

                upsert_ingredients(final, mode=mode.value, metadata=item_meta)
                scan_log.push(f"Done — {len(final)} ingredient(s) saved.")
                ui.notify(f"Saved {len(final)} ingredient(s)!", color="positive")
                results_panel.set_visibility(False)
                uploaded_paths.clear(); checkbox_refs.clear(); extra_items.clear()
                scanned_expiry_dates.clear(); storage_refs.clear(); expiry_refs.clear()
                checklist_col.clear(); extras_col.clear()
                scan_status.set_text("")
                asyncio.ensure_future(generate_aliases_async(new_only=True))

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=lambda: results_panel.set_visibility(False)).props("flat").style("color:#9a8a7a;")
                ui.button("Confirm & Save", icon="check", on_click=on_confirm).props("unelevated").style(
                    f"background:{ACCENT}; color:white; border-radius:8px; font-weight:600;"
                )

        async def do_scan():
            if not uploaded_paths:
                ui.notify("Upload at least one image first.", color="warning")
                return

            scan_btn.disable()
            scan_log.clear()
            log_panel.set_visibility(True)
            scan_status.set_text("Scanning images in parallel...")
            checkbox_refs.clear(); extra_items.clear()
            checklist_col.clear(); extras_col.clear()

            try:
                scan_log.push(f"Analysing {len(uploaded_paths)} image(s) with Claude Vision...")
                all_results = await asyncio.gather(*[identify_ingredients_async(p) for p in uploaded_paths])

                all_ingredients, all_uncertain = [], []
                for i, r in enumerate(all_results):
                    found = r.get("ingredients", [])
                    uncertain = r.get("uncertain", [])
                    scan_log.push(
                        f"[Image {i+1}]  {len(found)} ingredient(s) detected"
                        + (f", {len(uncertain)} uncertain" if uncertain else "")
                    )
                    all_ingredients.extend(found)
                    all_uncertain.extend(uncertain)

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
                    scan_status.set_text(f"Resolving {len(to_resolve)} uncertain item(s)...")
                    scan_log.push(f"Resolving {len(to_resolve)} uncertain item(s)...")
                    resolved_results = await asyncio.gather(
                        *[resolve_uncertain_async(d) for d in to_resolve]
                    )
                    for desc, res in zip(to_resolve, resolved_results):
                        if res:
                            scan_log.push(f"[Resolve]  '{desc}'  →  {res}")
                            confirmed.append(res)
                        else:
                            scan_log.push(f"[Resolve]  '{desc}'  —  could not identify, skipped")

                final_candidates = sorted(set(confirmed))

                scan_status.set_text("Deduplicating ingredient names...")
                scan_log.push(f"Deduplicating {len(final_candidates)} candidate(s)...")
                conn = get_connection()
                cur = conn.cursor()
                cur.execute("SELECT name FROM ingredients")
                existing_names = [r["name"] for r in cur.fetchall()]
                conn.close()
                final_candidates = await deduplicate_async(final_candidates, existing_names)

                # Save CV-extracted expiry dates keyed by pre-norm name before normalising
                pre_norm_expiry: dict[str, str | None] = {
                    name: seen.get(name, {}).get("expiry_date")
                    for name in final_candidates
                }

                scan_log.push(f"Normalising {len(final_candidates)} ingredient name(s)...")
                final_candidates = await normalise_batch_async(final_candidates, log_fn=scan_log.push)

                scan_log.push(f"{len(final_candidates)} unique ingredient(s) after normalisation — ready to review")

                scanned_expiry_dates.clear()
                for name in final_candidates:
                    scanned_expiry_dates[name] = pre_norm_expiry.get(name)

                _STORAGE_LABELS = {"fridge": "Fridge", "freezer": "Freezer", "pantry": "Pantry", "counter": "Counter"}

                with checklist_col:
                    for name in final_candidates:
                        cv_date: str | None = scanned_expiry_dates.get(name)
                        storage_guess = get_storage_guess(name)
                        kb_date = get_default_expiry(name, storage_guess)
                        pre_fill = cv_date or (kb_date.isoformat() if kb_date else "")
                        date_src = " (from label)" if cv_date else (" (estimated)" if pre_fill else "")

                        with ui.row().classes("w-full items-center gap-2 px-2 py-1 rounded-lg").style(
                            "background:#fafaf8; border:1px solid #e4ddd4;"
                        ):
                            cb = ui.checkbox(value=True).props("color=positive keep-color dense")
                            ui.label(name).style("color:#2d2420; font-size:0.9rem; flex:1; min-width:0;")

                            stor_sel = ui.select(
                                options=_STORAGE_LABELS,
                                value=storage_guess,
                            ).props("dense outlined").style("min-width:100px; max-width:110px; font-size:0.82rem;")

                            exp_inp = ui.input(
                                value=pre_fill,
                                placeholder="YYYY-MM-DD",
                            ).props("dense outlined").style(
                                "width:122px; font-size:0.82rem;"
                            )
                            if date_src:
                                exp_inp.tooltip(f"Expiry{date_src}")

                            def _on_storage_change(e, inp=exp_inp, n=name):
                                if not scanned_expiry_dates.get(n):
                                    kb = get_default_expiry(n, e.value)
                                    inp.set_value(kb.isoformat() if kb else "")

                            stor_sel.on_value_change(_on_storage_change)

                            checkbox_refs[name] = cb
                            storage_refs[name] = stor_sel
                            expiry_refs[name] = exp_inp

                count_lbl.set_text(f"{len(final_candidates)} ingredient(s) detected")
                results_panel.set_visibility(True)
                scan_status.set_text("Done — review and confirm below")

            except Exception as e:
                ui.notify(f"Scan error: {e}", color="negative")
                scan_status.set_text(f"Error: {e}")
                scan_log.push(f"ERROR: {e}")
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

            with ui.tab_panel(t_add):
                with ui.card().style(CARD).classes("w-full"):
                    ui.label("Recipe source").style(TEXT + " font-weight:600;")
                    input_method = ui.radio(
                        options={"text": "Paste text", "url": "From URL"},
                        value="text",
                    ).style("color:#5a4a3a;")

                    recipe_text = ui.textarea(
                        placeholder="Paste recipe here — name, ingredients, instructions..."
                    ).classes("w-full mt-2").style("color:#2d2420; min-height:160px;")

                    recipe_url = ui.input(placeholder="https://...").classes("w-full mt-2").style("color:#2d2420;")
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
                        f"background:{ACCENT}; color:white; border-radius:8px; font-weight:600; margin-top:0.75rem;"
                    )

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
                            with ui.card().style(CARD2).classes("w-full lift-gentle"):
                                with ui.row().classes("items-center justify-between w-full"):
                                    with ui.column().classes("gap-1"):
                                        with ui.row().classes("items-center gap-2 flex-wrap"):
                                            ui.label(r["name"]).style(TEXT + " font-weight:600;")
                                            _diff_time_badges({"difficulty": r["difficulty"], "prep_time": r["prep_time"]})
                                        src = f" · {r['source'][:40]}..." if r["source"] else ""
                                        ui.label(f"{r['ing_count']} ingredients{src}").style(MUTED)
                                    with ui.row().classes("items-center gap-2"):
                                        ui.label(f"#{r['id']}").style("color:#c8bfb0; font-size:0.8rem;")

                                        ui.button(icon="edit", on_click=lambda rid=r["id"]: open_edit_dialog(rid, load_recipes)).props("flat round dense").style(f"color:{ACCENT}; opacity:0.7;")

                                        def delete_recipe(rid=r["id"], rname=r["name"]):
                                            conn2 = get_connection()
                                            conn2.execute("DELETE FROM recipes WHERE id = ?", (rid,))
                                            conn2.commit()
                                            conn2.close()
                                            ui.notify(f"Deleted '{rname}'", color="warning")
                                            load_recipes()

                                        ui.button(icon="delete", on_click=delete_recipe).props("flat round dense").style("color:#d08080; font-size:0.8rem;")

                load_recipes()
                ui.button("Refresh", icon="refresh", on_click=load_recipes).props("flat").style(f"color:#9a8a7a; margin-top:0.5rem;")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — TODAY'S MEALS
# ══════════════════════════════════════════════════════════════════════════════

def today_tab():
    today = date.today()
    week_days = [today + timedelta(days=i) for i in range(7)]

    selected_date = {"value": today}
    wfh_cache: dict[date, bool] = {}
    diff_filter: dict = {"value": _ALL_DIFFS.copy()}

    with ui.column().classes("w-full gap-4"):
        section_heading("Today's Meals", "today")

        with ui.card().style(CARD).classes("w-full"):
            ui.label("Select day").style(MUTED)

            def style_day_btn(d: date):
                is_selected = d == selected_date["value"]
                wfh = wfh_cache.get(d)
                if wfh is True:
                    color, bg_dim = GREEN, "#eef6f0"
                elif wfh is False:
                    color, bg_dim = AMBER, "#fdf3e4"
                else:
                    color, bg_dim = BLUE, "#edf2f7"
                if is_selected:
                    return (f"background:{color} !important; color:white !important;"
                            f" border-radius:10px; min-width:56px; font-weight:700;"
                            f" box-shadow:0 3px 10px {color}55;")
                else:
                    return (f"background:{bg_dim} !important; color:{color} !important;"
                            f" border-radius:10px; min-width:56px; border:1px solid {color}44;")

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

            ui.separator().classes("my-2")

            with ui.row().classes("items-center gap-4 flex-wrap"):
                wfh_toggle = ui.switch("WFH", value=False).style("color:#5a4a3a;")

                def _on_wfh_change(e):
                    diff_filter["value"] = _ALL_DIFFS.copy() if e.value else {"easy"}
                    load_suggestions()

                wfh_toggle.on_value_change(_on_wfh_change)
                cal_lbl = ui.label("Checking calendar for the week...").style(MUTED)

                async def refresh_calendar():
                    # Drop the global cache for the whole week so fresh API calls are made
                    for d in week_days:
                        _wfh_global_cache.pop(d, None)
                        wfh_cache.pop(d, None)
                    cal_lbl.set_text("Refreshing calendar...")
                    await check_all_days()

                ui.button(icon="refresh", on_click=refresh_calendar).props("flat round dense").style(
                    f"color:{ACCENT}; opacity:0.7;"
                ).tooltip("Re-fetch calendar (clears cached WFH status)")

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
                # Filter chips
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    ui.label("Difficulty:").style(MUTED + " font-size:0.78rem;")
                    for diff in ("easy", "medium", "hard"):
                        is_active = diff in allowed
                        fg, bg = _DIFF_STYLE[diff]
                        chip_style = (
                            f"background:{fg} !important; color:white !important; font-weight:600;"
                            if is_active else
                            f"background:{bg} !important; color:{fg} !important; border:1px solid {fg}55;"
                        ) + " border-radius:20px; font-size:0.78rem; padding:0 0.75rem; min-height:28px;"

                        def _toggle(d=diff):
                            if d in diff_filter["value"] and len(diff_filter["value"]) > 1:
                                diff_filter["value"].discard(d)
                            else:
                                diff_filter["value"].add(d)
                            load_suggestions()

                        ui.button(diff.capitalize(), on_click=_toggle, color=None).props("unelevated dense").style(chip_style)

                # Cook Now
                with ui.column().classes("w-full gap-2"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("check_circle", size="1.2rem").style(f"color:{GREEN};")
                        ui.label(f"Cook Now  ({len(can_cook)})").style(f"color:{GREEN}; font-weight:700; {SERIF} font-size:1rem;")
                    if can_cook:
                        for r in can_cook:
                            _recipe_card(r, cookable=True, refresh_fn=load_suggestions)
                    else:
                        ui.label("No cookable recipes match the current filter.").style(MUTED)

                # Can Shop
                ui.separator().classes("my-1")
                with ui.column().classes("w-full gap-2"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("shopping_cart", size="1.2rem").style(f"color:{AMBER};")
                        ui.label(f"Can Cook If You Shop  ({len(can_shop)})").style(f"color:{AMBER}; font-weight:700; {SERIF} font-size:1rem;")
                    if can_shop:
                        for r in can_shop:
                            _recipe_card(r, cookable=False, refresh_fn=load_suggestions)
                    else:
                        ui.label("Nothing missing — you're fully stocked!").style(MUTED)

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
    "easy":   (GREEN,   "#eef6f0"),
    "medium": (AMBER,   "#fdf3e4"),
    "hard":   ("#c4504a", "#fdf0f0"),
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
            " border-radius:20px; padding:1px 8px; font-size:0.72rem; font-weight:600;"
        )
    if time and time in _TIME_LABEL:
        ui.label(_TIME_LABEL[time]).style(
            f"background:#edf2f7; color:{BLUE}; border:1px solid {BLUE}33;"
            " border-radius:20px; padding:1px 8px; font-size:0.72rem;"
        )


_STEP_RE = re.compile(r'^\s*(\d+)[.)]\s*(.+)')


def _format_steps_ui(instructions: str):
    """Renders instructions as indented numbered steps when detected, else wrapped paragraphs."""
    lines = [l.strip() for l in instructions.strip().splitlines() if l.strip()]
    matches = [_STEP_RE.match(l) for l in lines]
    numbered = sum(1 for m in matches if m)

    if numbered >= max(2, len(lines) * 0.5):
        for line, m in zip(lines, matches):
            if m:
                with ui.row().classes("items-start gap-3 py-1"):
                    ui.label(m.group(1) + ".").style(
                        f"color:{ACCENT}; font-weight:700; min-width:1.6rem; flex-shrink:0;"
                        f" {SERIF} font-size:0.88rem; padding-top:1px;"
                    )
                    ui.label(m.group(2)).style("color:#5a4a3a; font-size:0.88rem; line-height:1.55; flex:1;")
            else:
                ui.label(line).style("color:#9a8a7a; font-size:0.82rem; font-style:italic; padding-left:2rem;")
    else:
        ui.label(instructions.strip()).style(
            "color:#5a4a3a; font-size:0.88rem; white-space:pre-wrap; line-height:1.6;"
        )


def open_edit_dialog(rid: int, refresh_fn):
    """Full recipe edit dialog — name, instructions, ingredients with optional flag."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, instructions, source FROM recipes WHERE id = ?", (rid,))
    recipe_row = cur.fetchone()
    cur.execute(
        """
        SELECT i.id, i.name, ri.is_optional
        FROM recipe_ingredients ri
        JOIN ingredients i ON i.id = ri.ingredient_id
        WHERE ri.recipe_id = ?
        ORDER BY ri.is_optional, i.name
        """,
        (rid,),
    )
    ingredients = [
        {"id": r["id"], "name": r["name"], "is_optional": bool(r["is_optional"])}
        for r in cur.fetchall()
    ]
    conn.close()

    with ui.dialog() as dlg, ui.card().style(
        "width:min(640px,92vw); padding:1.5rem; max-height:88vh; overflow-y:auto;"
    ):
        ui.label("Edit Recipe").style(TEXT + f" font-weight:700; font-size:1.15rem; {SERIF}")

        name_input = ui.input("Recipe Name", value=recipe_row["name"]).classes("w-full mt-2").style("color:#2d2420;")

        ui.label("Instructions").style(MUTED + " font-size:0.78rem; margin-top:1rem;")
        instructions_area = ui.textarea(value=recipe_row["instructions"]).classes("w-full").style(
            "color:#2d2420; min-height:150px;"
        )

        source_input = ui.input(
            "Source URL (optional)", value=recipe_row["source"] or ""
        ).classes("w-full mt-1").style("color:#2d2420;")

        ui.separator().classes("my-3")

        with ui.row().classes("items-center justify-between w-full mb-1"):
            ui.label("Ingredients").style(f"color:{ACCENT}; font-weight:700; {SERIF} font-size:1rem;")
            ui.label("Check 'Optional' for garnishes / nice-to-haves").style(MUTED + " font-size:0.72rem;")

        ing_rows: list[dict] = []
        ing_col = ui.column().classes("w-full gap-2")

        def add_ingredient_row(name: str = "", is_optional: bool = False):
            row_data: dict = {"name_input": None, "optional_cb": None, "deleted": False}
            with ing_col:
                with ui.row().classes("items-center gap-2 w-full") as row_el:
                    row_data["name_input"] = (
                        ui.input(placeholder="ingredient name", value=name)
                        .classes("flex-1")
                        .style("color:#2d2420;")
                    )
                    row_data["optional_cb"] = ui.checkbox("Optional", value=is_optional).style(
                        "color:#5a4a3a; white-space:nowrap;"
                    )

                    def _remove(rd=row_data, el=row_el):
                        rd["deleted"] = True
                        el.set_visibility(False)

                    ui.button(icon="remove_circle_outline", on_click=_remove).props("flat round dense").style(
                        "color:#d08080;"
                    )
            ing_rows.append(row_data)

        for ing in ingredients:
            add_ingredient_row(ing["name"], ing["is_optional"])

        ui.button("+ Add Ingredient", icon="add", on_click=lambda: add_ingredient_row()).props("flat").style(
            f"color:{ACCENT}; font-weight:600; margin-top:0.25rem;"
        )

        ui.separator().classes("my-3")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dlg.close).props("flat").style("color:#9a8a7a;")

            def _save(d=dlg):
                new_name = name_input.value.strip()
                new_instr = instructions_area.value.strip()
                new_source = source_input.value.strip() or None

                if not new_name:
                    ui.notify("Recipe name cannot be empty.", color="warning")
                    return

                new_ings = [
                    {"name": rd["name_input"].value.strip().lower(), "is_optional": rd["optional_cb"].value}
                    for rd in ing_rows
                    if not rd["deleted"] and rd["name_input"].value.strip()
                ]
                if not new_ings:
                    ui.notify("Add at least one ingredient.", color="warning")
                    return

                conn2 = get_connection()
                cur2 = conn2.cursor()
                cur2.execute(
                    "UPDATE recipes SET name=?, instructions=?, source=? WHERE id=?",
                    (new_name, new_instr, new_source, rid),
                )
                cur2.execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (rid,))
                for ing_data in new_ings:
                    cur2.execute(
                        "INSERT INTO ingredients (name, in_stock) VALUES (?, 0) ON CONFLICT(name) DO NOTHING",
                        (ing_data["name"],),
                    )
                    cur2.execute("SELECT id FROM ingredients WHERE name=?", (ing_data["name"],))
                    ing_id = cur2.fetchone()["id"]
                    cur2.execute(
                        "INSERT INTO recipe_ingredients (recipe_id, ingredient_id, is_optional) VALUES (?, ?, ?)",
                        (rid, ing_id, 1 if ing_data["is_optional"] else 0),
                    )
                conn2.commit()
                conn2.close()
                ui.notify("Recipe updated!", color="positive")
                d.close()
                refresh_fn()

            ui.button("Save Changes", icon="save", on_click=_save).props("unelevated").style(
                f"background:{ACCENT}; color:white; border-radius:8px; font-weight:600;"
            )

    dlg.open()


def _recipe_card(recipe: dict, cookable: bool, refresh_fn):
    with ui.card().style(CARD2).classes("w-full lift-gentle"):
        with ui.row().classes("items-start justify-between w-full gap-2"):
            with ui.column().classes("gap-1 flex-1"):
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    ui.label(recipe["name"]).style(TEXT + f" font-weight:700; font-size:1rem; {SERIF}")
                    _diff_time_badges(recipe)

                if recipe.get("have"):
                    ui.label(f"Have: {', '.join(recipe['have'])}").style(f"color:{GREEN}; font-size:0.82rem;")

                if recipe.get("missing_required"):
                    ui.label(f"Buy: {', '.join(recipe['missing_required'])}").style(f"color:{AMBER}; font-size:0.82rem;")

                if recipe.get("missing_optional"):
                    ui.label(f"Optional: {', '.join(recipe['missing_optional'])}").style(MUTED + " font-size:0.82rem;")

            # Edit button always visible
            ui.button(icon="edit", on_click=lambda rid=recipe["id"]: open_edit_dialog(rid, refresh_fn)).props(
                "flat round dense"
            ).style(f"color:{ACCENT}; opacity:0.7;")

            if cookable:
                def open_cooked_dialog(rid=recipe["id"], rname=recipe["name"]):
                    ingredients = get_required_ingredients(rid)

                    with ui.dialog() as dlg, ui.card().style("min-width:340px; max-width:480px; padding:1.5rem;"):
                        ui.label(f"Mark as cooked").style(TEXT + f" font-weight:700; font-size:1.1rem; {SERIF}")
                        ui.label(rname).style(f"color:{ACCENT}; font-size:0.95rem; margin-bottom:0.5rem;")
                        ui.label("Untick items you still have remaining:").style(MUTED + " font-size:0.82rem; margin-bottom:0.25rem;")

                        checks: dict[str, dict] = {}
                        for ing in ingredients:
                            dname = ing["display_name"]
                            sname = ing["stocked_name"]
                            cb = ui.checkbox(dname, value=bool(sname)).style("color:#2d2420;")
                            if not sname:
                                cb.props("disable")
                            checks[dname] = {"cb": cb, "stocked_name": sname}

                        with ui.row().classes("w-full justify-end gap-2 mt-3"):
                            ui.button("Cancel", on_click=dlg.close).props("flat").style("color:#9a8a7a;")

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
                                f"background:{GREEN}; color:white; border-radius:8px; font-weight:600;"
                            )

                    dlg.open()

                ui.button("Mark Cooked", icon="done_all", on_click=open_cooked_dialog).props("unelevated").style(
                    f"background:{GREEN}; color:white; border-radius:8px; font-weight:600; white-space:nowrap;"
                )

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT instructions, source FROM recipes WHERE id = ?", (recipe["id"],))
        row = cur.fetchone()
        conn.close()
        if row and row["instructions"]:
            with ui.expansion("Instructions", icon="receipt_long").style("color:#9a8a7a; width:100%; margin-top:0.25rem;"):
                if row["source"]:
                    ui.link(row["source"], row["source"], new_tab=True).style(
                        f"color:{BLUE}; font-size:0.8rem; word-break:break-all; display:block; margin-bottom:0.5rem;"
                    )
                _format_steps_ui(row["instructions"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — STOCK & SHOPPING
# ══════════════════════════════════════════════════════════════════════════════

def stock_tab():
    with ui.column().classes("w-full gap-4"):
        section_heading("Stock & Shopping", "inventory_2")

        with ui.row().classes("w-full gap-4 items-start flex-wrap"):

            with ui.card().style(CARD).classes("flex-1 min-w-72"):
                with ui.row().classes("items-center justify-between w-full mb-2"):
                    ui.label("Current Stock").style(TEXT + " font-weight:600;")
                    ui.button(icon="refresh", on_click=lambda: load_stock()).props("flat round dense").style("color:#9a8a7a;")

                # Search input
                with ui.row().classes("w-full items-center gap-1 mb-1"):
                    ui.icon("search", size="1.1rem").style(f"color:{AMBER}; flex-shrink:0;")
                    stock_search = ui.input(placeholder="Search ingredients...").classes("flex-1").style(
                        "color:#2d2420; font-size:0.9rem;"
                    )
                    clear_btn = ui.button(icon="close").props("flat round dense").style(
                        "color:#9a8a7a; opacity:0;"
                    )

                stock_col = ui.column().classes("w-full gap-1")

                def load_stock(query: str = ""):
                    stock_col.clear()
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT id, name, in_stock, expiry_date, storage_location FROM ingredients ORDER BY name"
                    )
                    rows = cur.fetchall()
                    conn.close()

                    q = query.strip().lower()
                    if q:
                        rows = [r for r in rows if q in r["name"].lower()]

                    in_s = [r for r in rows if r["in_stock"]]
                    out_s = [r for r in rows if not r["in_stock"]]

                    with stock_col:
                        if not rows and not q:
                            ui.label("No ingredients yet — scan your kitchen!").style(MUTED)
                            return
                        if not rows and q:
                            ui.label(f'No results for "{q}"').style(MUTED)
                            return

                        # Pass current query into the refresh callback so toggling
                        # stock status doesn't reset the search filter.
                        refresh = lambda: load_stock(stock_search.value.strip())

                        if in_s:
                            ui.label(f"In Stock  ({len(in_s)})").style(f"color:{GREEN}; font-size:0.78rem; font-weight:700; margin-top:0.25rem;")
                            with ui.column().classes("w-full gap-1").style("max-height:260px; overflow-y:auto;"):
                                for r in in_s:
                                    _ingredient_row(r, True, refresh)
                        elif q:
                            ui.label("No in-stock matches").style(MUTED + " font-size:0.78rem;")

                        if out_s:
                            ui.label(f"Out of Stock  ({len(out_s)})").style("color:#c4504a; font-size:0.78rem; font-weight:700; margin-top:0.75rem;")
                            with ui.column().classes("w-full gap-1").style("max-height:200px; overflow-y:auto;"):
                                for r in out_s:
                                    _ingredient_row(r, False, refresh)
                        elif q and in_s:
                            ui.label("No out-of-stock matches").style(MUTED + " font-size:0.78rem; margin-top:0.5rem;")

                def on_search(e):
                    q = e.value.strip()
                    clear_btn.style(f"color:#9a8a7a; opacity:{'1' if q else '0'};")
                    load_stock(q)

                def on_clear():
                    stock_search.set_value("")
                    clear_btn.style("color:#9a8a7a; opacity:0;")
                    load_stock()

                stock_search.on_value_change(on_search)
                clear_btn.on("click", on_clear)

                ui.separator().classes("my-2")
                ui.label("Add ingredient manually").style(MUTED)
                with ui.row().classes("w-full gap-2"):
                    manual = ui.input(placeholder="e.g. miso paste").classes("flex-1").style("color:#2d2420;")

                    async def add_manual():
                        name = manual.value.strip().lower()
                        if not name:
                            return
                        existing = get_existing_ingredient_names()
                        canonical = await normalise_ingredient_async(name, existing)
                        if canonical != name:
                            ui.notify(f"Normalised to: {canonical}", color="info")
                        upsert_ingredients([canonical], mode="update")
                        manual.value = ""
                        load_stock(stock_search.value.strip())
                        ui.notify(f"Added: {canonical}", color="positive")

                    manual.on("keydown.enter", add_manual)
                    ui.button("Add", on_click=add_manual).props("unelevated").style(
                        f"background:{BLUE}; color:white; border-radius:8px; font-weight:600;"
                    )

                load_stock()

            with ui.card().style(CARD).classes("min-w-64"):
                with ui.row().classes("items-center justify-between w-full mb-2"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("shopping_cart", size="1.2rem").style(f"color:{AMBER};")
                        ui.label("Shopping List").style(TEXT + " font-weight:600;")
                    ui.button(icon="refresh", on_click=lambda: load_shopping()).props("flat round dense").style("color:#9a8a7a;")

                shopping_col = ui.column().classes("w-full gap-1")
                active_recipe: dict = {"value": None}

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

                        if len(all_recipe_names) > 1:
                            ui.label("Filter by recipe:").style(MUTED + " font-size:0.78rem;")
                            with ui.row().classes("gap-1 flex-wrap mb-1"):
                                def _make_chip(rname):
                                    is_active = active_recipe["value"] == rname
                                    chip_style = (
                                        f"background:{ACCENT} !important; color:white !important; font-weight:600;"
                                        if is_active else
                                        f"background:#f5f0ea !important; color:#9a8a7a !important; border:1px solid #e4ddd4;"
                                    ) + " border-radius:20px; font-size:0.78rem; padding:0 0.6rem;"

                                    def _toggle(rn=rname):
                                        active_recipe["value"] = None if active_recipe["value"] == rn else rn
                                        load_shopping()

                                    ui.button(rname, on_click=_toggle, color=None).props("unelevated dense").style(chip_style)

                                for rn in all_recipe_names:
                                    _make_chip(rn)

                        data = build_list(recipe_filter=[active_recipe["value"]]) if active_recipe["value"] else all_data
                        items = data["items"]

                        ui.separator().classes("my-1")

                        for item in items:
                            with ui.row().classes("items-start gap-2 py-1"):
                                ui.icon("radio_button_unchecked", size="1rem").style(f"color:{AMBER}; flex-shrink:0; margin-top:2px;")
                                with ui.column().classes("gap-0"):
                                    ui.label(item["ingredient"]).style("color:#2d2420; font-size:0.9rem;")
                                    if not active_recipe["value"]:
                                        ui.label(f"→ {', '.join(item['needed_for'])}").style(MUTED)

                load_shopping()


def _ingredient_row(row, in_stk: bool, refresh_fn):
    from shelf_life import STORAGE_OPTIONS
    bg = "#f5f9f6" if in_stk else "#fdf6f6"
    border = f"border:1px solid {GREEN}44;" if in_stk else "border:1px solid #e8c8c8;"

    expiry_str: str | None = row["expiry_date"] if "expiry_date" in row.keys() else None
    storage_str: str | None = row["storage_location"] if "storage_location" in row.keys() else None

    # Determine expiry label and colour
    expiry_color = "#9a8a7a"
    expiry_label = ""
    if expiry_str:
        try:
            exp_date = date.fromisoformat(expiry_str)
            days_left = (exp_date - date.today()).days
            if days_left < 0:
                expiry_label = f"exp {expiry_str} (expired)"
                expiry_color = "#c4504a"
            elif days_left <= 7:
                expiry_label = f"exp {expiry_str} ({days_left}d)"
                expiry_color = "#b87d2a"
            else:
                expiry_label = f"exp {expiry_str}"
                expiry_color = "#5a7a5a"
        except ValueError:
            expiry_label = f"exp {expiry_str}"

    with ui.row().classes("items-center gap-2 px-2 py-1 rounded w-full").style(f"background:{bg}; {border}"):
        ui.icon("check" if in_stk else "close", size="0.9rem").style(
            f"color:{GREEN if in_stk else '#c4504a'};"
        )
        ui.label(row["name"]).style("color:#2d2420; font-size:0.88rem; min-width:0;")

        # Expiry badge
        if expiry_label:
            ui.label(expiry_label).style(
                f"color:{expiry_color}; font-size:0.72rem; flex:1; min-width:0; "
                "white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"
            )
        else:
            ui.element("div").style("flex:1;")

        # Edit expiry/storage button
        def open_edit(n=row["name"], cur_exp=expiry_str, cur_stor=storage_str):
            _STOR_LABELS = {"fridge": "Fridge", "freezer": "Freezer", "pantry": "Pantry", "counter": "Counter"}
            with ui.dialog() as dlg, ui.card().style("min-width:280px; padding:1.25rem;"):
                ui.label(n).style("font-weight:600; color:#2d2420; margin-bottom:0.5rem;")
                stor_sel = ui.select(
                    options=_STOR_LABELS,
                    value=cur_stor or "pantry",
                    label="Storage",
                ).classes("w-full")
                exp_inp = ui.input(
                    label="Expiry date (YYYY-MM-DD)",
                    value=cur_exp or "",
                    placeholder="YYYY-MM-DD",
                ).classes("w-full mt-2")

                def save_edit():
                    new_exp = exp_inp.value.strip() or None
                    new_stor = stor_sel.value
                    conn = get_connection()
                    conn.execute(
                        "UPDATE ingredients SET expiry_date=?, storage_location=? WHERE name=?",
                        (new_exp, new_stor, n),
                    )
                    conn.commit()
                    conn.close()
                    dlg.close()
                    refresh_fn()

                def clear_expiry():
                    exp_inp.set_value("")

                with ui.row().classes("gap-2 mt-3 justify-end"):
                    ui.button("Clear date", on_click=clear_expiry).props("flat").style("color:#9a8a7a; font-size:0.8rem;")
                    ui.button("Cancel", on_click=dlg.close).props("flat").style("color:#9a8a7a;")
                    ui.button("Save", on_click=save_edit).props("unelevated").style(
                        f"background:{GREEN}; color:white; border-radius:6px;"
                    )
            dlg.open()

        ui.button(icon="edit_calendar", on_click=open_edit).props("flat round dense").style(
            "color:#9a8a7a; font-size:0.8rem; opacity:0.7;"
        ).tooltip("Edit expiry / storage")

        def toggle(name=row["name"], cur=in_stk):
            mark_ingredients([name], in_stock=not cur)
            refresh_fn()

        ui.button(
            "Remove" if in_stk else "Restore",
            on_click=toggle,
        ).props("flat dense").style(
            f"color:{'#c4504a' if in_stk else GREEN}; font-size:0.75rem; padding:0 0.25rem;"
        )

        if not in_stk:
            def delete(name=row["name"]):
                conn = get_connection()
                conn.execute("DELETE FROM ingredients WHERE name = ?", (name,))
                conn.commit()
                conn.close()
                from ingredient_index import get_index
                get_index().remove(name)
                refresh_fn()

            ui.button(icon="delete_outline", on_click=delete).props("flat round dense").style(
                "color:#c4504a; opacity:0.6; font-size:0.8rem;"
            ).tooltip("Permanently delete")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PAGE
# ══════════════════════════════════════════════════════════════════════════════

@ui.page("/")
def main_page():
    ui.add_css(PASTEL_CSS)
    ui.query("body").style(f"background:{BG};")

    with ui.header(elevated=False).style("padding:0.6rem 1.5rem; min-height:56px;"):
        with ui.row().classes("items-center gap-3"):
            ui.icon("local_fire_department", size="1.6rem").style(f"color:{ACCENT};")
            with ui.column().classes("gap-0"):
                ui.label("Kitchen Agent").style(f"color:#2d2420; font-size:1.15rem; font-weight:700; {SERIF} line-height:1.2;")
                ui.label("AI-powered kitchen management").style("color:#9a8a7a; font-size:0.72rem;")

    with ui.tabs().classes("w-full") as tabs:
        t_scan    = ui.tab("Scan Kitchen",    icon="photo_camera")
        t_recipes = ui.tab("Recipes",         icon="menu_book")
        t_today   = ui.tab("Today's Meals",   icon="today")
        t_stock   = ui.tab("Stock & Shopping", icon="inventory_2")

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
    dark=False,
    favicon="🍳",
)
