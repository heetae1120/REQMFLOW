from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
import tkinter as tk
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


def combobox_text_width(values, minimum: int = 0, maximum: int = 56) -> int:
    """Return a Tk character width that also accounts for wide Korean glyphs."""
    def units(value):
        return sum(2 if unicodedata.east_asian_width(character) in ('W','F') else 1
                   for character in str(value))
    longest=max((units(value) for value in values),default=0)
    return max(minimum,min(maximum,longest+5))


def widen_combobox_dropdown(widget, values=None, maximum: int = 96) -> None:
    """Size both the editable field and native popdown for long code/name values."""
    values = list(values if values is not None else widget.cget('values'))
    current=max(1,int(widget.cget('width') or 0))
    field_width=combobox_text_width(values,current,44)
    dropdown_width=combobox_text_width(values,field_width,maximum)
    try:
        if field_width > current:
            widget.configure(width=field_width)
    except Exception:
        pass
    try:
        popdown = widget.tk.call('ttk::combobox::PopdownWindow', str(widget))
        widget.tk.call(f'{popdown}.f.l', 'configure', '-width', dropdown_width, '-height', min(12, max(1, len(values))))
    except Exception:
        pass


def bind_wide_combobox(widget) -> None:
    """Attach one persistent, non-modal suggestion list to an editable combobox."""
    if getattr(widget,'_reqm_search_bound',False):
        return
    widget._reqm_search_bound=True

    def show_current(*_):
        post_combobox(widget,widget.cget('values'))

    def button_press(event):
        widen_combobox_dropdown(widget)
        element=widget.identify(event.x,event.y)
        if 'arrow' in str(element).casefold():
            widget.focus_force()
            widget.after_idle(show_current)
            return 'break'

    def move(delta):
        popup=getattr(widget,'_reqm_popup',None)
        if not popup or not popup.winfo_viewable():
            show_current();return 'break'
        values=getattr(widget,'_reqm_popup_values',[])
        if not values:return 'break'
        listbox=widget._reqm_popup_list
        selected=listbox.curselection()
        index=max(0,min(len(values)-1,(selected[0] if selected else (-1 if delta>0 else 0))+delta))
        listbox.selection_clear(0,'end');listbox.selection_set(index);listbox.activate(index);listbox.see(index)
        return 'break'

    def choose_active(_event=None):
        popup=getattr(widget,'_reqm_popup',None)
        if not popup or not popup.winfo_viewable():return
        selected=widget._reqm_popup_list.curselection()
        if not selected:return
        value=widget._reqm_popup_list.get(selected[0])
        widget.set(value);widget.icursor('end')
        popup.withdraw();widget.focus_force()
        widget.event_generate('<<ComboboxSelected>>')
        return 'break'

    def hide_later(*_):
        def hide():
            popup=getattr(widget,'_reqm_popup',None)
            if not popup or not popup.winfo_exists():return
            focus=str(widget.tk.call('focus'))
            if focus == str(widget) or focus.startswith(str(popup)):
                return
            popup.withdraw()
        widget.after(120,hide)

    widget.bind('<ButtonPress-1>',button_press,add='+')
    widget.bind('<FocusIn>',show_current,add='+')
    widget.bind('<FocusOut>',hide_later,add='+')
    widget.bind('<Down>',lambda _event:move(1),add='+')
    widget.bind('<Up>',lambda _event:move(-1),add='+')
    widget.bind('<Return>',choose_active,add='+')
    widget.bind('<Escape>',lambda _event:_hide_combobox_popup(widget),add='+')
    widget.bind('<Alt-Down>',lambda _event:(show_current(),'break')[1],add='+')


def post_combobox(widget, values, delay: int = 0) -> None:
    """Update and show related choices without moving focus from the text field."""
    values=list(values)
    widget.configure(values=values)
    widen_combobox_dropdown(widget,values)
    if not values:
        _hide_combobox_popup(widget)
        return
    try:focused=str(widget.tk.call('focus')) == str(widget)
    except Exception:focused=False
    if not focused:return
    popup=getattr(widget,'_reqm_popup',None)
    if not popup or not popup.winfo_exists():
        popup=tk.Toplevel(widget.winfo_toplevel())
        popup.withdraw();popup.overrideredirect(True);popup.transient(widget.winfo_toplevel())
        frame=tk.Frame(popup,bg='#CBD5E1',padx=1,pady=1);frame.pack(fill='both',expand=True)
        listbox=tk.Listbox(
            frame,exportselection=False,activestyle='dotbox',relief='flat',borderwidth=0,
            bg='#FFFFFF',fg='#172033',selectbackground='#2563EB',selectforeground='#FFFFFF',
            font=tkfont.nametofont('TkDefaultFont'),highlightthickness=0,
        )
        scrollbar=tk.Scrollbar(frame,orient='vertical',command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        listbox.pack(side='left',fill='both',expand=True);scrollbar.pack(side='right',fill='y')
        widget._reqm_popup=popup;widget._reqm_popup_list=listbox
        def choose(event):
            index=listbox.nearest(event.y)
            if index < 0:return
            value=listbox.get(index)
            widget.set(value);widget.icursor('end')
            popup.withdraw();widget.focus_force()
            widget.event_generate('<<ComboboxSelected>>')
        listbox.bind('<ButtonRelease-1>',choose)
        listbox.bind('<Return>',lambda _event:choose(type('Event',(),{'y':listbox.bbox('active')[1] if listbox.bbox('active') else 0})()))
        widget.bind('<Destroy>',lambda _event:popup.destroy() if popup.winfo_exists() else None,add='+')
    listbox=widget._reqm_popup_list
    listbox.delete(0,'end')
    for value in values:listbox.insert('end',value)
    widget._reqm_popup_values=values
    font=tkfont.nametofont('TkDefaultFont')
    width=max(widget.winfo_width(),min(960,max((font.measure(str(value)) for value in values),default=0)+48))
    rows=min(12,max(1,len(values)));height=rows*(font.metrics('linespace')+7)+4
    x=widget.winfo_rootx();y=widget.winfo_rooty()+widget.winfo_height()
    screen_width=widget.winfo_screenwidth();screen_height=widget.winfo_screenheight()
    x=max(0,min(x,screen_width-width-8))
    if y+height>screen_height-8:y=max(0,widget.winfo_rooty()-height)
    popup.geometry(f'{width}x{height}+{x}+{y}')
    popup.deiconify();popup.lift()
    try:popup.attributes('-topmost',True)
    except tk.TclError:pass


def _hide_combobox_popup(widget):
    popup=getattr(widget,'_reqm_popup',None)
    if popup and popup.winfo_exists():popup.withdraw()
    return 'break'


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


def tree_sort_value(value):
    """Return a stable value that sorts numbers naturally and text case-insensitively."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    number = text.replace(",", "")
    try:
        return 0, Decimal(number)
    except InvalidOperation:
        return 1, text.casefold()


def bind_tree_sorting(tree) -> None:
    """Make every heading toggle ascending/descending without losing selections."""
    labels = {column: str(tree.heading(column, "text") or column) for column in tree["columns"]}
    state = {"column": "", "descending": False}

    def sort(column):
        descending = not state["descending"] if state["column"] == column else False
        rows = list(tree.get_children(""))
        rows.sort(key=lambda item: tree_sort_value(tree.set(item, column)), reverse=descending)
        for index, item in enumerate(rows):
            tree.move(item, "", index)
        state.update(column=column, descending=descending)
        for name, label in labels.items():
            suffix = " ▼" if name == column and descending else (" ▲" if name == column else "")
            tree.heading(name, text=label + suffix)

    for column in tree["columns"]:
        tree.heading(column, command=lambda selected=column: sort(selected))
    tree._reqm_sort = sort


def bind_desktop_drag(tree) -> None:
    """Drag across rows to select a range; middle-button drag pans the table."""
    state = {"anchor": "", "x": 0, "y": 0, "dragging": False, "pointer_y": 0, "job": None}

    def select_to(row):
        anchor = state.get("anchor")
        if not anchor or not row:
            return
        children = list(tree.get_children(""))
        try:
            start, end = children.index(anchor), children.index(row)
        except ValueError:
            return
        low, high = sorted((start, end))
        tree.selection_set(children[low:high + 1])

    def edge_scroll():
        state["job"] = None
        if not state["dragging"] or not tree.winfo_exists():
            return
        height = tree.winfo_height()
        y = state["pointer_y"]
        direction = -1 if y < 22 else (1 if y > height - 22 else 0)
        if direction:
            tree.yview_scroll(direction, "units")
            row = tree.identify_row(2 if direction < 0 else max(2, height - 2))
            select_to(row)
            state["job"] = tree.after(55, edge_scroll)

    def press(event):
        row = tree.identify_row(event.y)
        state["anchor"] = row
        state["dragging"] = bool(row)
        state["pointer_y"] = event.y
        if not row:
            tree.selection_remove(tree.selection())

    def drag(event):
        state["pointer_y"] = event.y
        if state["dragging"] and state["job"] is None:
            edge_scroll()
        row = tree.identify_row(event.y)
        if not row and event.y < 0:
            row = tree.identify_row(2)
        elif not row and event.y > tree.winfo_height():
            row = tree.identify_row(max(2, tree.winfo_height() - 2))
        select_to(row)

    def release(_event):
        state["dragging"] = False
        if state["job"] is not None:
            try:
                tree.after_cancel(state["job"])
            except Exception:
                pass
            state["job"] = None

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
    tree.bind("<ButtonRelease-1>", release, add="+")
    tree.bind("<ButtonPress-2>", pan_start, add="+")
    tree.bind("<B2-Motion>", pan_move, add="+")
    tree.bind("<ButtonRelease-2>", pan_end, add="+")
