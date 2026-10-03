from __future__ import annotations

import re
import tkinter.font as tkfont


SEARCH_GROUPS = (
    ("주문", "주문번호", "상품주문번호", "오더", "order"),
    ("상품", "상품명", "제품", "품목", "item", "product"),
    ("옵션", "규격", "선택", "option"),
    ("수량", "개수", "주문수", "qty", "quantity"),
    ("금액", "가격", "결제", "판매가", "합계", "amount", "price"),
    ("수령인", "수취인", "받는분", "받는사람", "recipient"),
    ("연락처", "전화", "휴대폰", "핸드폰", "phone", "mobile"),
    ("주소", "배송지", "우편번호", "postcode", "address"),
    ("배송", "택배", "운송장", "송장", "tracking"),
    ("이벤트", "행사", "프로모션", "event"),
    ("중복", "동일", "duplicate"),
    ("검토", "확인", "오류", "누락", "review"),
)


def search_suggestions(query: str, values, limit: int = 12) -> list[str]:
    """Return direct values first, then related vocabulary without changing the typed text."""
    query = query.strip().casefold()
    if not query:
        return []
    words = [str(value).strip() for value in values if str(value).strip()]
    direct = []
    for value in words:
        if query in value.casefold() and value not in direct:
            direct.append(value)
    related = []
    for group in SEARCH_GROUPS:
        folded = [word.casefold() for word in group]
        if any(query in word or word in query for word in folded):
            related.extend(word for word in group if query not in word.casefold())
    result = []
    for value in [*direct, *related]:
        if value not in result:
            result.append(value)
        if len(result) >= limit:
            break
    return result


def filter_combobox_choices(query: str, values) -> list[str]:
    """Filter an editable combobox using every space-separated search term."""
    terms = [term.casefold() for term in str(query).split() if term]
    return [value for value in values if all(term in str(value).casefold() for term in terms)]


def widen_combobox_dropdown(widget, values=None, maximum: int = 72) -> None:
    """Size the native ttk popdown for long code/name values."""
    values = list(values if values is not None else widget.cget('values'))
    longest = max((len(str(value)) for value in values), default=0)
    width = max(int(widget.cget('width') or 0), min(maximum, longest + 3))
    try:
        popdown = widget.tk.call('ttk::combobox::PopdownWindow', str(widget))
        widget.tk.call(f'{popdown}.f.l', 'configure', '-width', width, '-height', min(12, max(1, len(values))))
    except Exception:
        pass


def bind_wide_combobox(widget) -> None:
    """Also widen a combobox when its arrow is opened manually."""
    widget.bind('<ButtonPress-1>', lambda _event:widen_combobox_dropdown(widget), add='+')


def post_combobox(widget, values, delay: int = 380) -> None:
    """Update choices now, then open once after typing pauses.

    Re-posting a ttk combobox on every KeyRelease interrupts Korean IME
    composition.  A short debounce preserves composition while keeping the
    automatic suggestion list.
    """
    widget.configure(values=values)
    pending = getattr(widget, '_reqm_post_job', None)
    if pending:
        try:
            widget.after_cancel(pending)
        except Exception:
            pass
        widget._reqm_post_job = None
    if not values:
        return

    def open_choices():
        widget._reqm_post_job = None
        if not widget.winfo_exists() or widget.focus_get() != widget:
            return
        try:
            popdown = widget.tk.call('ttk::combobox::PopdownWindow', str(widget))
            if not int(widget.tk.call('winfo', 'ismapped', popdown)):
                widget.tk.call('ttk::combobox::Post', str(widget))
            widen_combobox_dropdown(widget, values)
        except Exception:
            widget.event_generate('<Down>')

    if widget.focus_get() == widget:
        widget._reqm_post_job = widget.after(delay, open_choices)


def autosize_tree(tree, *, minimum: int = 58, maximum: int = 420) -> None:
    font = tkfont.nametofont("TkDefaultFont")
    heading_font = tkfont.nametofont("TkHeadingFont")
    for column in tree["columns"]:
        heading = str(tree.heading(column, "text") or column)
        width = heading_font.measure(heading) + 28
        for item_id in tree.get_children(""):
            value = str(tree.set(item_id, column) or "")
            value = re.sub(r"\s+", " ", value)
            width = max(width, font.measure(value) + 24)
        tree.column(column, width=max(minimum, min(maximum, width)), stretch=False)


def bind_desktop_drag(tree) -> None:
    """Drag across rows to select a range; middle-button drag pans the table."""
    state = {"anchor": "", "x": 0, "y": 0}

    def press(event):
        row = tree.identify_row(event.y)
        state["anchor"] = row
        if not row:
            tree.selection_remove(tree.selection())

    def drag(event):
        anchor = state.get("anchor")
        row = tree.identify_row(event.y)
        if not anchor or not row:
            if event.y < 12:
                tree.yview_scroll(-1, "units")
            elif event.y > tree.winfo_height() - 12:
                tree.yview_scroll(1, "units")
            return
        children = list(tree.get_children(""))
        try:
            start, end = children.index(anchor), children.index(row)
        except ValueError:
            return
        low, high = sorted((start, end))
        tree.selection_set(children[low:high + 1])

    def pan_start(event):
        state["x"], state["y"] = event.x, event.y
        tree.configure(cursor="fleur")
        return "break"

    def pan_move(event):
        dx, dy = state["x"] - event.x, state["y"] - event.y
        if abs(dx) >= 4:
            tree.xview_scroll(int(dx / 4), "units")
            state["x"] = event.x
        if abs(dy) >= 4:
            tree.yview_scroll(int(dy / 4), "units")
            state["y"] = event.y
        return "break"

    def pan_end(_event):
        tree.configure(cursor="")
        return "break"

    tree.bind("<ButtonPress-1>", press, add="+")
    tree.bind("<B1-Motion>", drag, add="+")
    tree.bind("<ButtonPress-2>", pan_start, add="+")
    tree.bind("<B2-Motion>", pan_move, add="+")
    tree.bind("<ButtonRelease-2>", pan_end, add="+")
