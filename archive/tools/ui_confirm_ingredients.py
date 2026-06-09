"""
Ingredient Confirmation UI (NiceGUI)
--------------------------------------
Shows CV-detected ingredients as a checklist.
User can uncheck wrong items and add missed ones before committing to DB.

Called by scan_kitchen.py after CV detection, before DB write.
Can also run standalone for manual stock editing.

Usage (standalone):
    python tools/ui_confirm_ingredients.py
    python tools/ui_confirm_ingredients.py --detected "garlic" "eggs" "soy sauce"
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from db_init import init_db, get_connection

from nicegui import ui


def run_confirmation_ui(
    detected: list[str],
    mode: str = "update",
    on_confirm=None,
) -> list[str]:
    """
    Launch the confirmation UI. Blocks until user clicks Confirm or Cancel.
    Returns the final confirmed ingredient list (or empty list if cancelled).
    """
    confirmed_result = []
    app_done = False

    # State: checkboxes keyed by ingredient name
    checks: dict[str, bool] = {name: True for name in detected}

    @ui.page("/")
    def page():
        nonlocal app_done

        ui.query("body").style("background: #1a1a2e; font-family: 'Inter', sans-serif;")

        with ui.column().classes("w-full max-w-2xl mx-auto p-6 gap-4"):

            # Header
            with ui.row().classes("items-center gap-3"):
                ui.icon("kitchen", size="2rem").style("color: #e94560;")
                ui.label("Confirm Kitchen Ingredients").style(
                    "color: #e94560; font-size: 1.5rem; font-weight: 700;"
                )

            ui.label(
                f"Claude detected {len(detected)} ingredient(s) from your photos. "
                "Uncheck anything wrong, then add anything missing."
            ).style("color: #a0a0b0; font-size: 0.9rem;")

            ui.separator().style("background: #2a2a4a;")

            # Detected ingredients checklist
            ui.label("Detected ingredients").style(
                "color: #ffffff; font-weight: 600; font-size: 1rem;"
            )

            checkbox_widgets = {}
            with ui.column().classes("w-full gap-1"):
                for name in sorted(checks.keys()):
                    with ui.row().classes("items-center gap-2 w-full px-2 py-1 rounded").style(
                        "background: #2a2a4a;"
                    ):
                        cb = ui.checkbox(name, value=True).style("color: #e0e0f0;")
                        cb.props("color=positive keep-color")
                        checkbox_widgets[name] = cb

            ui.separator().style("background: #2a2a4a;")

            # Add missing ingredients
            ui.label("Add missing ingredients").style(
                "color: #ffffff; font-weight: 600; font-size: 1rem;"
            )

            extra_items: list[str] = []
            extra_column = ui.column().classes("w-full gap-1")

            def add_extra(name: str):
                name = name.strip().lower()
                if not name or name in [e.lower() for e in extra_items]:
                    return
                extra_items.append(name)
                with extra_column:
                    with ui.row().classes("items-center gap-2 w-full px-2 py-1 rounded").style(
                        "background: #1e3a2a;"
                    ):
                        ui.icon("add_circle", size="1.2rem").style("color: #4caf50;")
                        ui.label(name).style("color: #e0e0f0; flex: 1;")
                        def remove(n=name):
                            extra_items.remove(n)
                            ui.notify(f"Removed: {n}", color="warning")
                            # Refresh page to reflect removal
                            ui.navigate.reload()
                        ui.button(icon="close", on_click=remove).props(
                            "flat round dense size=sm"
                        ).style("color: #ff6b6b;")
                new_input.value = ""

            with ui.row().classes("w-full gap-2"):
                new_input = ui.input(placeholder="e.g. fish sauce, tofu...").classes("flex-1").style(
                    "background: #2a2a4a; color: #e0e0f0; border-radius: 8px;"
                )
                new_input.on("keydown.enter", lambda: add_extra(new_input.value))
                ui.button("Add", on_click=lambda: add_extra(new_input.value)).props(
                    "unelevated"
                ).style("background: #3a5a8a; color: white; border-radius: 8px;")

            ui.separator().style("background: #2a2a4a;")

            # Mode indicator
            mode_color = "#4caf50" if mode == "restock" else "#3a8aff"
            mode_label = "RESTOCK (replaces all stock)" if mode == "restock" else "UPDATE (adds to existing stock)"
            with ui.row().classes("items-center gap-2"):
                ui.icon("info", size="1rem").style(f"color: {mode_color};")
                ui.label(f"Mode: {mode_label}").style(f"color: {mode_color}; font-size: 0.85rem;")

            # Action buttons
            with ui.row().classes("w-full justify-end gap-3 mt-2"):

                def on_cancel():
                    nonlocal app_done
                    confirmed_result.clear()
                    app_done = True
                    ui.notify("Cancelled — nothing saved.", color="negative")
                    ui.timer(1.0, lambda: app.shutdown(), once=True)

                def on_confirm_click():
                    nonlocal app_done
                    final = [
                        name for name, cb in checkbox_widgets.items() if cb.value
                    ] + extra_items
                    confirmed_result.extend(final)
                    app_done = True
                    ui.notify(f"Saved {len(final)} ingredient(s)!", color="positive")
                    ui.timer(1.0, lambda: app.shutdown(), once=True)

                ui.button("Cancel", on_click=on_cancel).props("flat").style(
                    "color: #ff6b6b;"
                )
                ui.button("Confirm & Save", on_click=on_confirm_click).props(
                    "unelevated"
                ).style("background: #e94560; color: white; border-radius: 8px; padding: 0.5rem 1.5rem;")

    from nicegui import app
    ui.run(title="Kitchen Ingredients", port=8765, reload=False, show=True)
    return confirmed_result


def run_standalone(detected: list[str], mode: str = "update"):
    """Run UI, then write confirmed ingredients to DB."""
    init_db()
    confirmed = run_confirmation_ui(detected, mode=mode)
    if not confirmed:
        print("[UI] Cancelled — DB not updated.")
        return

    conn = get_connection()
    cur = conn.cursor()

    if mode == "restock":
        cur.execute("UPDATE ingredients SET in_stock = 0, last_updated = datetime('now')")

    for name in confirmed:
        cur.execute(
            """
            INSERT INTO ingredients (name, in_stock, last_updated)
            VALUES (?, 1, datetime('now'))
            ON CONFLICT(name) DO UPDATE SET in_stock = 1, last_updated = datetime('now')
            """,
            (name.strip().lower(),),
        )

    conn.commit()
    conn.close()
    print(f"[DB] Saved {len(confirmed)} ingredient(s) (mode={mode})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingredient Confirmation UI")
    parser.add_argument("--detected", nargs="*", default=[], help="Pre-populate checklist with these items")
    parser.add_argument("--mode", choices=["update", "restock"], default="update")
    args = parser.parse_args()
    run_standalone(detected=args.detected, mode=args.mode)
