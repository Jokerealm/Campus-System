from __future__ import annotations

import base64
import io
import mimetypes
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, List, Optional, Sequence, Tuple

from qpaper import EmbeddedImage, Question, extract_images, read_qpaper, write_qpaper

try:
    from PIL import Image, ImageTk
except Exception:  # Pillow is optional. The editor still works without it.
    Image = None
    ImageTk = None


OPTION_LABELS = ("A", "B", "C", "D")
QUESTION_TYPE_LABELS = {
    "choice": "选择题",
    "fill_blank": "填空题",
    "essay": "大题",
}
QUESTION_TYPE_BY_LABEL = {label: value for value, label in QUESTION_TYPE_LABELS.items()}
QUESTION_TYPE_DISPLAY_VALUES = tuple(QUESTION_TYPE_LABELS.values())
IMAGE_FILE_TYPES = (
    ("图片文件", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
    ("PNG", "*.png"),
    ("JPEG", "*.jpg *.jpeg"),
    ("GIF", "*.gif"),
    ("所有文件", "*.*"),
)


@dataclass
class EditableQuestion:
    question_type: str = "choice"
    t1: str = ""
    p1: Optional[EmbeddedImage] = None
    t2: List[str] = field(default_factory=lambda: ["", "", "", ""])
    p2: List[Optional[EmbeddedImage]] = field(default_factory=lambda: [None, None, None, None])

    @classmethod
    def from_question(cls, question: Question) -> "EditableQuestion":
        return cls(
            question_type=normalize_gui_question_type(getattr(question, "question_type", "choice"), question.t2, question.p2),
            t1=question.t1,
            p1=question.p1,
            t2=list(question.t2),
            p2=list(question.p2),
        )

    def to_question(self) -> Question:
        if len(self.t2) != 4 or len(self.p2) != 4:
            raise ValueError("每道题必须有 4 个选项文本槽位和 4 个选项图片槽位。")
        if self.question_type == "choice":
            t2 = tuple(self.t2)
            p2 = tuple(self.p2)
        else:
            t2 = ("", "", "", "")
            p2 = (None, None, None, None)
        return Question(
            t1=self.t1,
            p1=self.p1,
            t2=t2,  # type: ignore[arg-type]
            p2=p2,  # type: ignore[arg-type]
            question_type=self.question_type,
        )

    def clone(self) -> "EditableQuestion":
        return EditableQuestion(
            question_type=self.question_type,
            t1=self.t1,
            p1=self.p1,
            t2=list(self.t2),
            p2=list(self.p2),
        )


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner_window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.inner.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._resize_inner)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    def _update_scroll_region(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_inner(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.inner_window, width=event.width)

    def _bind_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class ImageSlot(ttk.LabelFrame):
    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        on_change: Callable[[], None],
        max_preview_size: Tuple[int, int] = (240, 150),
    ) -> None:
        super().__init__(parent, text=title, padding=8)
        self.on_change = on_change
        self.max_preview_size = max_preview_size
        self.image: Optional[EmbeddedImage] = None
        self._photo = None
        self._enabled = True

        self.preview = ttk.Label(
            self,
            text="无图片",
            anchor="center",
            justify="center",
            relief="solid",
            width=28,
        )
        self.preview.grid(row=0, column=0, columnspan=3, sticky="nsew", pady=(0, 6))

        self.info_var = tk.StringVar(value="未设置")
        self.info = ttk.Label(self, textvariable=self.info_var, wraplength=260, justify="left")
        self.info.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 6))

        self.choose_button = ttk.Button(self, text="添加/替换", command=self.choose_image)
        self.clear_button = ttk.Button(self, text="删除", command=self.clear_image)
        self.export_button = ttk.Button(self, text="导出", command=self.export_image)
        self.choose_button.grid(row=2, column=0, sticky="ew", padx=(0, 4))
        self.clear_button.grid(row=2, column=1, sticky="ew", padx=4)
        self.export_button.grid(row=2, column=2, sticky="ew", padx=(4, 0))

        for col in range(3):
            self.columnconfigure(col, weight=1)

    def set_image(self, image: Optional[EmbeddedImage], notify: bool = False) -> None:
        self.image = image
        self._refresh()
        if notify:
            self.on_change()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        state = "normal" if enabled else "disabled"
        self.choose_button.configure(state=state)
        self.clear_button.configure(state=state)
        self.export_button.configure(state=state)

    def choose_image(self) -> None:
        if not self._enabled:
            return
        file_name = filedialog.askopenfilename(title="选择图片", filetypes=IMAGE_FILE_TYPES)
        if not file_name:
            return
        try:
            self.set_image(EmbeddedImage.from_file(file_name), notify=True)
        except Exception as exc:
            messagebox.showerror("图片读取失败", str(exc))

    def clear_image(self) -> None:
        if not self._enabled:
            return
        if self.image is None:
            return
        self.set_image(None, notify=True)

    def export_image(self) -> None:
        if not self._enabled or self.image is None:
            return
        extension = Path(self.image.filename).suffix or mimetypes.guess_extension(self.image.media_type) or ".bin"
        file_name = filedialog.asksaveasfilename(
            title="导出图片",
            initialfile=self.image.filename or f"image{extension}",
            defaultextension=extension,
            filetypes=(("图片文件", f"*{extension}"), ("所有文件", "*.*")),
        )
        if not file_name:
            return
        try:
            self.image.save_to(file_name)
        except Exception as exc:
            messagebox.showerror("图片导出失败", str(exc))

    def _refresh(self) -> None:
        self._photo = None
        if self.image is None:
            self.preview.configure(image="", text="无图片")
            self.info_var.set("未设置")
            return

        self.info_var.set(
            f"{self.image.filename}\n{self.image.media_type}, {len(self.image.data)} bytes"
        )
        preview, message = make_preview_image(self.image, self.max_preview_size)
        if preview is None:
            self.preview.configure(image="", text=message)
            return

        self._photo = preview
        self.preview.configure(image=self._photo, text="")


class QuestionPreview(ttk.LabelFrame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text="题目预览", padding=8)
        self.question: Optional[EditableQuestion] = None
        self.question_number: Optional[int] = None
        self._photos = []
        self._redraw_id: Optional[str] = None

        self.canvas = tk.Canvas(
            self,
            bg="white",
            height=260,
            highlightthickness=1,
            highlightbackground="#d9d9d9",
        )
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas.bind("<Configure>", lambda _event: self._schedule_redraw())

    def render(self, question: EditableQuestion, question_number: Optional[int]) -> None:
        self.question = question
        self.question_number = question_number
        self._schedule_redraw()

    def show_empty(self) -> None:
        self.question = None
        self.question_number = None
        self._schedule_redraw()

    def _schedule_redraw(self) -> None:
        if self._redraw_id is not None:
            self.after_cancel(self._redraw_id)
        self._redraw_id = self.after(80, self._draw)

    def _draw_legacy_unused(self) -> None:
        self._redraw_id = None
        self.canvas.delete("all")
        self._photos.clear()

        width = max(self.canvas.winfo_width(), 720)
        height = max(self.canvas.winfo_height(), 260)
        padding = 20
        content_width = width - padding * 2

        if self.question is None:
            self.canvas.create_text(
                padding,
                padding,
                anchor="nw",
                text="当前没有题目。点击“添加题目”创建第一道题。",
                fill="#666666",
                font=("Microsoft YaHei UI", 12),
                width=content_width,
            )
            self.canvas.configure(scrollregion=(0, 0, width, height))
            return

        question = self.question
        y = padding
        number_prefix = f"{self.question_number}. " if self.question_number is not None else ""
        stem = number_prefix + (question.t1.strip() or "[题干文字为空]")

        image_gap = 18
        stem_image_size = (min(330, max(210, int(content_width * 0.36))), 190)
        p1_size = self._image_display_size(question.p1, stem_image_size)
        stem_text_width = content_width
        if p1_size is not None:
            stem_text_width = max(280, content_width - p1_size[0] - image_gap)

        stem_bottom = self._draw_text(
            padding,
            y,
            stem,
            width=stem_text_width,
            font=("Microsoft YaHei UI", 13),
            fill="#111111",
        )
        image_bottom = y
        if p1_size is not None:
            image_x = padding + content_width - p1_size[0]
            image_bottom = self._draw_image(question.p1, image_x, y, stem_image_size, "题干图片无法预览")

        y = max(stem_bottom, image_bottom) + 18
        self.canvas.create_line(padding, y, padding + content_width, y, fill="#eeeeee")
        y += 14

        for index, label in enumerate(OPTION_LABELS):
            option_text = question.t2[index].strip() or "[选项文字为空]"
            option_image = question.p2[index]
            option_image_size = (190, 115)
            display_size = self._image_display_size(option_image, option_image_size)
            text_width = content_width - 18
            if display_size is not None:
                text_width = max(260, content_width - display_size[0] - image_gap - 18)

            row_y = y
            text_bottom = self._draw_text(
                padding + 12,
                row_y,
                f"{label}. {option_text}",
                width=text_width,
                font=("Microsoft YaHei UI", 12),
                fill="#222222",
            )
            image_bottom = row_y
            if display_size is not None:
                image_x = padding + content_width - display_size[0]
                image_bottom = self._draw_image(option_image, image_x, row_y, option_image_size, f"{label} 选项图片无法预览")

            y = max(text_bottom, image_bottom) + 13

        bottom = max(y + padding, height)
        self.canvas.configure(scrollregion=(0, 0, width, bottom))

    def _draw_text(
        self,
        x: int,
        y: int,
        text: str,
        width: int,
        font: Tuple[str, int],
        fill: str,
    ) -> int:
        text_id = self.canvas.create_text(
            x,
            y,
            anchor="nw",
            text=text,
            width=width,
            fill=fill,
            font=font,
            justify="left",
        )
        bbox = self.canvas.bbox(text_id)
        return bbox[3] if bbox is not None else y + 24

    def _image_display_size(self, image: Optional[EmbeddedImage], max_size: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        if image is None:
            return None
        preview, _message = make_preview_image(image, max_size)
        if preview is None:
            return max_size
        self._photos.append(preview)
        return preview.width(), preview.height()

    def _draw_image(
        self,
        image: Optional[EmbeddedImage],
        x: int,
        y: int,
        max_size: Tuple[int, int],
        fallback_text: str,
    ) -> int:
        if image is None:
            return y

        preview, _message = make_preview_image(image, max_size)
        if preview is None:
            width, height = max_size
            self.canvas.create_rectangle(x, y, x + width, y + height, outline="#bbbbbb", fill="#f7f7f7")
            self.canvas.create_text(
                x + width / 2,
                y + height / 2,
                anchor="center",
                text=fallback_text,
                fill="#777777",
                font=("Microsoft YaHei UI", 10),
                width=width - 16,
            )
            return y + height

        self._photos.append(preview)
        self.canvas.create_image(x, y, anchor="nw", image=preview)
        return y + preview.height()

    def _draw(self) -> None:
        self._redraw_id = None
        self.canvas.delete("all")
        self._photos.clear()

        width = max(self.canvas.winfo_width(), 760)
        height = max(self.canvas.winfo_height(), 260)
        padding = 22
        content_width = width - padding * 2

        if self.question is None:
            self.canvas.create_text(
                padding,
                padding,
                anchor="nw",
                text="当前没有题目。点击“添加题目”创建第一道题。",
                fill="#666666",
                font=("Microsoft YaHei UI", 12),
                width=content_width,
            )
            self.canvas.configure(scrollregion=(0, 0, width, height))
            return

        question = self.question
        number_prefix = f"{self.question_number}. " if self.question_number is not None else ""
        stem = number_prefix + (question.t1.strip() or "[题干文字为空]")
        y = self._draw_stem(question, stem, padding, padding, content_width) + 16

        if question.question_type == "choice":
            y = self._draw_choice_options(question, padding, y, content_width)

        bottom = max(y + padding, height)
        self.canvas.configure(scrollregion=(0, 0, width, bottom))

    def _draw_stem(
        self,
        question: EditableQuestion,
        stem: str,
        x: int,
        y: int,
        width: int,
    ) -> int:
        image_gap = 18
        stem_font = ("SimSun", 16)
        prepared = self._make_preview(
            question.p1,
            (min(340, max(220, int(width * 0.36))), 190),
        )

        if prepared is not None and width >= 700:
            image_width = prepared[1]
            text_width = max(320, width - image_width - image_gap)
            text_bottom = self._draw_text(
                x,
                y,
                stem,
                width=text_width,
                font=stem_font,
                fill="#111111",
            )
            image_bottom = self._draw_prepared_image(
                prepared,
                x + width - image_width,
                y,
                "题干图片无法预览",
            )
            return max(text_bottom, image_bottom)

        text_bottom = self._draw_text(
            x,
            y,
            stem,
            width=width,
            font=stem_font,
            fill="#111111",
        )
        if prepared is None:
            return text_bottom

        image_x = x + max(0, (width - prepared[1]) // 2)
        return self._draw_prepared_image(prepared, image_x, text_bottom + 10, "题干图片无法预览")

    def _draw_choice_options(
        self,
        question: EditableQuestion,
        x: int,
        y: int,
        width: int,
    ) -> int:
        options = []
        for index, label in enumerate(OPTION_LABELS):
            text = question.t2[index].strip()
            image = question.p2[index]
            if text or image is not None:
                options.append((label, text, image))

        if not options:
            self._draw_text(
                x,
                y,
                "[选择题选项为空]",
                width=width,
                font=("Microsoft YaHei UI", 11),
                fill="#777777",
            )
            return y + 28

        has_image = any(image is not None for _label, _text, image in options)
        if width >= 760:
            columns = min(4, len(options)) if has_image else min(2, len(options))
        elif width >= 520:
            columns = min(2, len(options))
        else:
            columns = 1

        col_width = width // columns
        row_gap = 14 if has_image else 8
        index = 0
        while index < len(options):
            row_bottom = y
            for column in range(columns):
                if index >= len(options):
                    break
                label, text, image = options[index]
                option_x = x + column * col_width
                option_width = col_width - 14
                row_bottom = max(
                    row_bottom,
                    self._draw_option(option_x, y, option_width, label, text, image),
                )
                index += 1
            y = row_bottom + row_gap
        return y

    def _draw_option(
        self,
        x: int,
        y: int,
        width: int,
        label: str,
        text: str,
        image: Optional[EmbeddedImage],
    ) -> int:
        label_font = ("SimSun", 16)
        text_font = ("SimSun", 15)
        prepared = self._make_preview(image, (max(70, width - 38), 118)) if image is not None else None

        if prepared is not None and not text:
            image_height = prepared[2]
            label_y = y + max(0, (image_height - 26) // 2)
            label_id = self.canvas.create_text(
                x,
                label_y,
                anchor="nw",
                text=f"{label}.",
                fill="#111111",
                font=label_font,
            )
            label_box = self.canvas.bbox(label_id)
            image_x = (label_box[2] + 7) if label_box is not None else x + 34
            return self._draw_prepared_image(prepared, image_x, y, f"{label} 选项图片无法预览")

        text_value = f"{label}. {text}" if text else f"{label}."
        text_bottom = self._draw_text(
            x,
            y,
            text_value,
            width=width,
            font=text_font,
            fill="#111111",
        )
        if prepared is None:
            return text_bottom

        image_x = x + 30
        image_y = text_bottom + 5
        return self._draw_prepared_image(prepared, image_x, image_y, f"{label} 选项图片无法预览")

    def _make_preview(
        self,
        image: Optional[EmbeddedImage],
        max_size: Tuple[int, int],
    ):
        if image is None:
            return None
        preview, _message = make_preview_image(image, max_size)
        if preview is None:
            return (None, max_size[0], max_size[1])
        return (preview, preview.width(), preview.height())

    def _draw_prepared_image(
        self,
        prepared_image,
        x: int,
        y: int,
        fallback_text: str,
    ) -> int:
        photo, width, height = prepared_image
        if photo is None:
            self.canvas.create_rectangle(x, y, x + width, y + height, outline="#bbbbbb", fill="#f7f7f7")
            self.canvas.create_text(
                x + width / 2,
                y + height / 2,
                anchor="center",
                text=fallback_text,
                fill="#777777",
                font=("Microsoft YaHei UI", 10),
                width=width - 16,
            )
            return y + height

        self._photos.append(photo)
        self.canvas.create_image(x, y, anchor="nw", image=photo)
        return y + height


class QPaperEditor:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("QPaper 试卷编辑器")
        self.root.geometry("1180x780")
        self.root.minsize(980, 640)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.file_path: Optional[Path] = None
        self.questions: List[EditableQuestion] = []
        self.current_index: Optional[int] = None
        self.loading = False
        self.dirty = False
        self.preview_update_id: Optional[str] = None

        self.title_var = tk.StringVar()
        self.question_type_var = tk.StringVar(value=QUESTION_TYPE_LABELS["choice"])
        self.status_var = tk.StringVar()
        self.title_var.trace_add("write", self._on_title_change)

        self._build_menu()
        self._build_layout()
        self.new_file()

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="新建", command=self.new_file, accelerator="Ctrl+N")
        file_menu.add_command(label="打开...", command=self.open_file, accelerator="Ctrl+O")
        file_menu.add_command(label="保存", command=self.save_file, accelerator="Ctrl+S")
        file_menu.add_command(label="另存为...", command=self.save_file_as, accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="导出全部图片...", command=self.export_all_images)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.close)
        menu.add_cascade(label="文件", menu=file_menu)
        self.root.configure(menu=menu)

        self.root.bind("<Control-n>", lambda _event: self.new_file())
        self.root.bind("<Control-o>", lambda _event: self.open_file())
        self.root.bind("<Control-s>", lambda _event: self.save_file())
        self.root.bind("<Control-S>", lambda _event: self.save_file_as())

    def _build_layout(self) -> None:
        main = ttk.Frame(self.root, padding=8)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        toolbar = ttk.Frame(main)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(toolbar, text="新建", command=self.new_file).pack(side="left")
        ttk.Button(toolbar, text="打开", command=self.open_file).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="保存", command=self.save_file).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="另存为", command=self.save_file_as).pack(side="left", padx=(6, 0))
        ttk.Label(toolbar, textvariable=self.status_var).pack(side="right")

        content = ttk.PanedWindow(main, orient="horizontal")
        content.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        left = ttk.Frame(content, padding=(0, 0, 8, 0))
        right = ttk.Frame(content)
        content.add(left, weight=0)
        content.add(right, weight=1)

        self._build_question_list(left)
        self._build_editor(right)

    def _build_question_list(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="题目列表").grid(row=0, column=0, columnspan=2, sticky="w")

        self.question_list = tk.Listbox(parent, width=28, exportselection=False)
        self.question_list.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(6, 6))
        self.question_list.bind("<<ListboxSelect>>", self._on_question_select)

        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.question_list.yview)
        scrollbar.grid(row=1, column=2, sticky="ns", pady=(6, 6))
        self.question_list.configure(yscrollcommand=scrollbar.set)

        ttk.Button(parent, text="添加题目", command=self.add_question).grid(row=2, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(parent, text="复制题目", command=self.duplicate_question).grid(row=2, column=1, sticky="ew", padx=(4, 0))
        ttk.Button(parent, text="上移", command=self.move_question_up).grid(row=3, column=0, sticky="ew", padx=(0, 4), pady=(6, 0))
        ttk.Button(parent, text="下移", command=self.move_question_down).grid(row=3, column=1, sticky="ew", padx=(4, 0), pady=(6, 0))
        ttk.Button(parent, text="删除题目", command=self.delete_question).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(1, weight=1)

    def _build_editor(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        parent.rowconfigure(2, weight=0)

        title_frame = ttk.Frame(parent)
        title_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(title_frame, text="试卷标题").grid(row=0, column=0, sticky="w")
        self.title_entry = ttk.Entry(title_frame, textvariable=self.title_var)
        self.title_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(title_frame, text="题型").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.question_type_combo = ttk.Combobox(
            title_frame,
            textvariable=self.question_type_var,
            values=QUESTION_TYPE_DISPLAY_VALUES,
            state="readonly",
            width=10,
        )
        self.question_type_combo.grid(row=0, column=3, sticky="ew", padx=(8, 0))
        self.question_type_combo.bind("<<ComboboxSelected>>", self._on_question_type_change)
        title_frame.columnconfigure(1, weight=1)

        scroll = ScrollableFrame(parent)
        scroll.grid(row=1, column=0, sticky="nsew")
        editor = scroll.inner
        editor.columnconfigure(0, weight=1)

        stem_frame = ttk.LabelFrame(editor, text="t1 / p1：题干", padding=10)
        stem_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        stem_frame.columnconfigure(0, weight=2)
        stem_frame.columnconfigure(1, weight=1)

        ttk.Label(stem_frame, text="题干文字 t1").grid(row=0, column=0, sticky="w")
        self.t1_text = tk.Text(stem_frame, height=7, wrap="word", undo=True)
        self.t1_text.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        self.t1_text.bind("<<Modified>>", self._on_text_modified)
        self.p1_slot = ImageSlot(stem_frame, "题干图片 p1", self._on_image_change, max_preview_size=(300, 180))
        self.p1_slot.grid(row=1, column=1, sticky="nsew")

        self.options_frame = ttk.LabelFrame(editor, text="t2 / p2：选项（仅选择题）", padding=10)
        self.options_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.options_frame.columnconfigure(0, weight=1)

        self.option_texts: List[tk.Text] = []
        self.option_slots: List[ImageSlot] = []
        for row, label in enumerate(OPTION_LABELS):
            option_frame = ttk.Frame(self.options_frame)
            option_frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
            option_frame.columnconfigure(1, weight=2)
            option_frame.columnconfigure(2, weight=1)

            ttk.Label(option_frame, text=f"{label} 选项文字").grid(row=0, column=0, sticky="nw", padx=(0, 8))
            text = tk.Text(option_frame, height=4, wrap="word", undo=True)
            text.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
            text.bind("<<Modified>>", self._on_text_modified)
            self.option_texts.append(text)

            slot = ImageSlot(option_frame, f"{label} 选项图片", self._on_image_change, max_preview_size=(220, 130))
            slot.grid(row=0, column=2, sticky="nsew")
            self.option_slots.append(slot)

        self.question_preview = QuestionPreview(parent)
        self.question_preview.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def new_file(self) -> None:
        if not self._confirm_discard_or_save():
            return
        self.file_path = None
        self.questions = [EditableQuestion()]
        self.current_index = 0
        self._set_title("")
        self.dirty = False
        self._refresh_question_list()
        self._load_current_question()
        self._update_window_title()
        self._set_status("新建试卷")

    def open_file(self) -> None:
        if not self._confirm_discard_or_save():
            return
        file_name = filedialog.askopenfilename(
            title="打开 QPaper 文件",
            filetypes=(("QPaper 文件", "*.qpaper"), ("所有文件", "*.*")),
        )
        if not file_name:
            return
        try:
            paper = read_qpaper(file_name)
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))
            return

        self.file_path = Path(file_name)
        self.questions = [EditableQuestion.from_question(question) for question in paper.questions]
        self.current_index = 0 if self.questions else None
        self._set_title(paper.title)
        self.dirty = False
        self._refresh_question_list()
        self._load_current_question()
        self._update_window_title()
        self._set_status(f"已打开：{self.file_path.name}")

    def save_file(self) -> bool:
        if self.file_path is None:
            return self.save_file_as()
        return self._save_to_path(self.file_path)

    def save_file_as(self) -> bool:
        initial_file = self.file_path.name if self.file_path else "untitled.qpaper"
        file_name = filedialog.asksaveasfilename(
            title="保存 QPaper 文件",
            initialfile=initial_file,
            defaultextension=".qpaper",
            filetypes=(("QPaper 文件", "*.qpaper"), ("所有文件", "*.*")),
        )
        if not file_name:
            return False
        self.file_path = Path(file_name)
        return self._save_to_path(self.file_path)

    def _save_to_path(self, path: Path) -> bool:
        self._save_editor_to_current()
        try:
            write_qpaper(path, [question.to_question() for question in self.questions], title=self.title_var.get())
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            return False

        self.dirty = False
        self._refresh_question_list()
        self._update_window_title()
        self._set_status(f"已保存：{path.name}")
        return True

    def export_all_images(self) -> None:
        if self.file_path is None or self.dirty:
            if not self.save_file():
                return
        if self.file_path is None:
            return
        output_dir = filedialog.askdirectory(title="选择图片导出目录")
        if not output_dir:
            return
        try:
            written = extract_images(self.file_path, output_dir)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        messagebox.showinfo("导出完成", f"已导出 {len(written)} 张图片。")

    def add_question(self) -> None:
        self._save_editor_to_current()
        self.questions.append(EditableQuestion())
        self.current_index = len(self.questions) - 1
        self._mark_dirty()
        self._refresh_question_list()
        self._load_current_question()

    def duplicate_question(self) -> None:
        if self.current_index is None:
            return
        self._save_editor_to_current()
        self.questions.insert(self.current_index + 1, self.questions[self.current_index].clone())
        self.current_index += 1
        self._mark_dirty()
        self._refresh_question_list()
        self._load_current_question()

    def delete_question(self) -> None:
        if self.current_index is None:
            return
        if not messagebox.askyesno("删除题目", "确定删除当前题目吗？"):
            return
        del self.questions[self.current_index]
        if not self.questions:
            self.current_index = None
        else:
            self.current_index = min(self.current_index, len(self.questions) - 1)
        self._mark_dirty()
        self._refresh_question_list()
        self._load_current_question()

    def move_question_up(self) -> None:
        if self.current_index is None or self.current_index == 0:
            return
        self._save_editor_to_current()
        index = self.current_index
        self.questions[index - 1], self.questions[index] = self.questions[index], self.questions[index - 1]
        self.current_index -= 1
        self._mark_dirty()
        self._refresh_question_list()
        self._load_current_question()

    def move_question_down(self) -> None:
        if self.current_index is None or self.current_index >= len(self.questions) - 1:
            return
        self._save_editor_to_current()
        index = self.current_index
        self.questions[index + 1], self.questions[index] = self.questions[index], self.questions[index + 1]
        self.current_index += 1
        self._mark_dirty()
        self._refresh_question_list()
        self._load_current_question()

    def close(self) -> None:
        if self._confirm_discard_or_save():
            self.root.destroy()

    def _on_question_select(self, _event: tk.Event) -> None:
        selection = self.question_list.curselection()
        if not selection:
            return
        new_index = selection[0]
        if new_index == self.current_index:
            return
        self._save_editor_to_current()
        self.current_index = new_index
        self._load_current_question()

    def _load_current_question(self) -> None:
        self.loading = True
        try:
            if self.current_index is None:
                self.question_type_var.set(QUESTION_TYPE_LABELS["choice"])
                self._replace_text(self.t1_text, "")
                self.p1_slot.set_image(None)
                for text in self.option_texts:
                    self._replace_text(text, "")
                for slot in self.option_slots:
                    slot.set_image(None)
                self._set_editor_enabled(False)
                self._update_question_preview()
                return

            self._set_editor_enabled(True)
            question = self.questions[self.current_index]
            self.question_type_var.set(QUESTION_TYPE_LABELS.get(question.question_type, QUESTION_TYPE_LABELS["choice"]))
            self._sync_question_type_ui()
            self._replace_text(self.t1_text, question.t1)
            self.p1_slot.set_image(question.p1)
            for index, text in enumerate(self.option_texts):
                self._replace_text(text, question.t2[index])
            for index, slot in enumerate(self.option_slots):
                slot.set_image(question.p2[index])
            self.question_list.selection_clear(0, tk.END)
            self.question_list.selection_set(self.current_index)
            self.question_list.see(self.current_index)
            self._update_question_preview()
        finally:
            self.loading = False

    def _save_editor_to_current(self) -> None:
        if self.current_index is None or self.loading:
            return
        self.questions[self.current_index] = self._collect_current_question()
        self._refresh_question_label(self.current_index)

    def _collect_current_question(self) -> EditableQuestion:
        return EditableQuestion(
            question_type=self._current_question_type(),
            t1=self._text_value(self.t1_text),
            p1=self.p1_slot.image,
            t2=[self._text_value(text) for text in self.option_texts],
            p2=[slot.image for slot in self.option_slots],
        )

    def _refresh_question_list(self) -> None:
        self.question_list.delete(0, tk.END)
        for index, question in enumerate(self.questions):
            self.question_list.insert(tk.END, self._question_label(index, question))
        if self.current_index is not None:
            self.question_list.selection_set(self.current_index)
            self.question_list.see(self.current_index)
        self._update_question_preview()

    def _refresh_question_label(self, index: int) -> None:
        if index < 0 or index >= len(self.questions):
            return
        self.question_list.delete(index)
        self.question_list.insert(index, self._question_label(index, self.questions[index]))
        if self.current_index is not None:
            self.question_list.selection_set(self.current_index)

    def _question_label(self, index: int, question: EditableQuestion) -> str:
        summary = " ".join(question.t1.split())
        if not summary:
            summary = "空题干"
        if len(summary) > 18:
            summary = summary[:18] + "..."
        image_count = int(question.p1 is not None)
        if question.question_type == "choice":
            image_count += sum(1 for image in question.p2 if image is not None)
        type_label = QUESTION_TYPE_LABELS.get(question.question_type, "选择题")
        return f"{index + 1}. [{type_label}] {summary} ({image_count}图)"

    def _set_editor_enabled(self, enabled: bool) -> None:
        text_state = "normal" if enabled else "disabled"
        self.question_type_combo.configure(state="readonly" if enabled else "disabled")
        self.t1_text.configure(state=text_state)
        for text in self.option_texts:
            text.configure(state=text_state)
        self.p1_slot.set_enabled(enabled)
        for slot in self.option_slots:
            slot.set_enabled(enabled)
        self._sync_question_type_ui()

    def _replace_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.edit_modified(False)

    def _text_value(self, widget: tk.Text) -> str:
        return widget.get("1.0", "end-1c")

    def _current_question_type(self) -> str:
        return QUESTION_TYPE_BY_LABEL.get(self.question_type_var.get(), "choice")

    def _sync_question_type_ui(self) -> None:
        if not hasattr(self, "options_frame"):
            return
        if self.current_index is None or self._current_question_type() != "choice":
            self.options_frame.grid_remove()
            return
        self.options_frame.grid()

    def _on_question_type_change(self, _event: tk.Event) -> None:
        if self.loading:
            return
        self._sync_question_type_ui()
        self._mark_dirty()
        self._save_editor_to_current()
        self._schedule_question_preview_update()

    def _on_text_modified(self, event: tk.Event) -> None:
        widget = event.widget
        if not isinstance(widget, tk.Text):
            return
        if not widget.edit_modified():
            return
        widget.edit_modified(False)
        if self.loading:
            return
        self._mark_dirty()
        self._save_editor_to_current()
        self._schedule_question_preview_update()

    def _on_image_change(self) -> None:
        if self.loading:
            return
        self._mark_dirty()
        self._save_editor_to_current()
        self._schedule_question_preview_update()

    def _on_title_change(self, *_args: object) -> None:
        if self.loading:
            return
        self._mark_dirty()

    def _mark_dirty(self) -> None:
        if not self.dirty:
            self.dirty = True
            self._update_window_title()

    def _set_title(self, value: str) -> None:
        self.loading = True
        try:
            self.title_var.set(value)
        finally:
            self.loading = False

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _update_window_title(self) -> None:
        name = self.file_path.name if self.file_path else "未命名.qpaper"
        dirty_mark = "*" if self.dirty else ""
        self.root.title(f"{dirty_mark}{name} - QPaper 试卷编辑器")

    def _confirm_discard_or_save(self) -> bool:
        if not self.dirty:
            return True
        result = messagebox.askyesnocancel("未保存的修改", "当前试卷有未保存修改，是否先保存？")
        if result is None:
            return False
        if result:
            return self.save_file()
        return True

    def _schedule_question_preview_update(self) -> None:
        if self.preview_update_id is not None:
            self.root.after_cancel(self.preview_update_id)
        self.preview_update_id = self.root.after(150, self._update_question_preview)

    def _update_question_preview(self) -> None:
        self.preview_update_id = None
        if self.current_index is None:
            self.question_preview.show_empty()
        else:
            question = self._collect_current_question()
            self.question_preview.render(question, self.current_index + 1)


def make_preview_image(image: EmbeddedImage, max_size: Tuple[int, int]):
    if Image is not None and ImageTk is not None:
        try:
            with Image.open(io.BytesIO(image.data)) as opened:
                opened.thumbnail(max_size)
                preview = opened.copy()
            return ImageTk.PhotoImage(preview), ""
        except Exception:
            pass

    if image.media_type not in {"image/png", "image/gif"}:
        return None, "无法预览\n可安装 Pillow 支持更多格式"

    try:
        encoded = base64.b64encode(image.data).decode("ascii")
        preview = tk.PhotoImage(data=encoded)
        scale = max(
            1,
            (preview.width() + max_size[0] - 1) // max_size[0],
            (preview.height() + max_size[1] - 1) // max_size[1],
        )
        if scale > 1:
            preview = preview.subsample(scale, scale)
        return preview, ""
    except Exception:
        return None, "图片数据无法预览"


def normalize_gui_question_type(
    value: object,
    t2: Sequence[str],
    p2: Sequence[Optional[EmbeddedImage]],
) -> str:
    aliases = {
        "choice": "choice",
        "选择": "choice",
        "选择题": "choice",
        "single_choice": "choice",
        "multiple_choice": "choice",
        "fill": "fill_blank",
        "fill_blank": "fill_blank",
        "blank": "fill_blank",
        "填空": "fill_blank",
        "填空题": "fill_blank",
        "essay": "essay",
        "subjective": "essay",
        "大题": "essay",
        "解答题": "essay",
    }
    key = str(value).strip()
    normalized = aliases.get(key) or aliases.get(key.lower())
    if normalized is not None:
        return normalized
    if any(str(text).strip() for text in t2) or any(image is not None for image in p2):
        return "choice"
    return "fill_blank"


def main() -> None:
    root = tk.Tk()
    QPaperEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
