from __future__ import annotations

import argparse
import json
import mimetypes
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union


FORMAT_ID = "school_system.qpaper"
FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
DEFAULT_SUFFIX = ".qpaper"
EMPTY_OPTION_IMAGES: Tuple[None, None, None, None] = (None, None, None, None)
QUESTION_TYPES = ("choice", "fill_blank", "essay")


PathLike = Union[str, Path]
ImageInput = Optional[Union["EmbeddedImage", PathLike]]


@dataclass(frozen=True)
class EmbeddedImage:
    """An image stored inside a qpaper file."""

    data: bytes
    filename: str
    media_type: str = "application/octet-stream"

    @classmethod
    def from_file(cls, path: PathLike) -> "EmbeddedImage":
        image_path = Path(path)
        if not image_path.is_file():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        media_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
        if not media_type.startswith("image/"):
            raise ValueError(f"Not an image file by extension/media type: {image_path}")

        return cls(
            data=image_path.read_bytes(),
            filename=image_path.name,
            media_type=media_type,
        )

    def save_to(self, path: PathLike) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(self.data)
        return output_path


@dataclass(frozen=True)
class Question:
    """One question: (t1, p1, t2, p2)."""

    t1: str
    p1: Optional[EmbeddedImage]
    t2: Tuple[str, str, str, str]
    p2: Tuple[
        Optional[EmbeddedImage],
        Optional[EmbeddedImage],
        Optional[EmbeddedImage],
        Optional[EmbeddedImage],
    ] = EMPTY_OPTION_IMAGES
    question_type: str = "choice"

    @classmethod
    def from_files(
        cls,
        t1: str,
        p1_path: ImageInput,
        t2: Sequence[str],
        p2_paths: Optional[Sequence[ImageInput]] = None,
        question_type: str = "choice",
    ) -> "Question":
        return cls(
            t1=t1,
            p1=_coerce_image(p1_path),
            t2=_normalize_option_text(t2),
            p2=_normalize_option_images(p2_paths),
            question_type=_normalize_question_type(question_type),
        )


@dataclass(frozen=True)
class Paper:
    title: str
    questions: Tuple[Question, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)


def write_qpaper(
    output_path: PathLike,
    questions: Iterable[Question],
    title: str = "",
    metadata: Optional[Mapping[str, Any]] = None,
) -> Path:
    """Write questions and embedded images into one .qpaper file."""

    paper_path = Path(output_path)
    if paper_path.suffix == "":
        paper_path = paper_path.with_suffix(DEFAULT_SUFFIX)
    paper_path.parent.mkdir(parents=True, exist_ok=True)

    question_list = tuple(questions)
    assets: Dict[str, Dict[str, Any]] = {}
    manifest_questions: List[Dict[str, Any]] = []

    with zipfile.ZipFile(paper_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for question_index, question in enumerate(question_list, start=1):
            question_type = _normalize_question_type(question.question_type)
            option_texts = question.t2 if question_type == "choice" else ("", "", "", "")
            option_images = question.p2 if question_type == "choice" else EMPTY_OPTION_IMAGES
            p1_ref = _write_asset(archive, assets, question_index, "p1", question.p1)
            p2_refs = [
                _write_asset(archive, assets, question_index, f"p2_{option_index}", image)
                for option_index, image in enumerate(option_images, start=1)
            ]

            manifest_questions.append(
                {
                    "question_type": question_type,
                    "t1": question.t1,
                    "p1": p1_ref,
                    "t2": list(option_texts),
                    "p2": p2_refs,
                }
            )

        manifest = {
            "format": FORMAT_ID,
            "version": FORMAT_VERSION,
            "title": title,
            "metadata": dict(metadata or {}),
            "questions": manifest_questions,
            "assets": assets,
        }
        archive.writestr(
            MANIFEST_NAME,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    return paper_path


def read_qpaper(input_path: PathLike) -> Paper:
    """Read a .qpaper file and return all question text plus image bytes."""

    paper_path = Path(input_path)
    with zipfile.ZipFile(paper_path, "r") as archive:
        manifest = _read_manifest(archive)
        questions = []
        for entry in manifest["questions"]:
            t2 = _normalize_option_text(entry.get("t2", []))
            p2 = _normalize_loaded_option_images(
                _read_asset(archive, manifest, ref) for ref in _normalize_asset_refs(entry.get("p2", []))
            )
            questions.append(
                Question(
                    t1=_require_string(entry, "t1"),
                    p1=_read_asset(archive, manifest, entry.get("p1")),
                    t2=t2,
                    p2=p2,
                    question_type=_normalize_question_type(
                        entry.get("question_type") or entry.get("type") or _infer_question_type(t2, p2)
                    ),
                )
            )

        return Paper(
            title=str(manifest.get("title", "")),
            questions=tuple(questions),
            metadata=dict(manifest.get("metadata", {})),
        )


def extract_images(input_path: PathLike, output_dir: PathLike) -> List[Path]:
    """Extract embedded images for inspection or conversion."""

    paper = read_qpaper(input_path)
    base_dir = Path(output_dir)
    written: List[Path] = []

    for question_index, question in enumerate(paper.questions, start=1):
        question_dir = base_dir / f"q{question_index:04d}"
        if question.p1 is not None:
            written.append(question.p1.save_to(question_dir / _safe_filename("p1", question.p1)))

        for option_index, image in enumerate(question.p2, start=1):
            if image is not None:
                written.append(image.save_to(question_dir / _safe_filename(f"p2_{option_index}", image)))

    return written


def _coerce_image(image: ImageInput) -> Optional[EmbeddedImage]:
    if image is None:
        return None
    if isinstance(image, EmbeddedImage):
        return image
    return EmbeddedImage.from_file(image)


def _normalize_option_text(texts: Sequence[str]) -> Tuple[str, str, str, str]:
    if len(texts) != 4:
        raise ValueError("t2 must contain exactly 4 option texts, for example A/B/C/D.")
    return tuple(str(text) for text in texts)  # type: ignore[return-value]


def _normalize_option_images(
    images: Optional[Sequence[ImageInput]],
) -> Tuple[
    Optional[EmbeddedImage],
    Optional[EmbeddedImage],
    Optional[EmbeddedImage],
    Optional[EmbeddedImage],
]:
    if images is None:
        return EMPTY_OPTION_IMAGES
    if len(images) > 4:
        raise ValueError("p2 can contain at most 4 option images.")

    normalized = [_coerce_image(image) for image in images]
    normalized.extend([None] * (4 - len(normalized)))
    return tuple(normalized)  # type: ignore[return-value]


def _normalize_question_type(value: Any) -> str:
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
    if normalized is None:
        raise ValueError(f"Unsupported question type: {value!r}")
    return normalized


def _infer_question_type(
    t2: Sequence[str],
    p2: Sequence[Optional[EmbeddedImage]],
) -> str:
    if any(str(text).strip() for text in t2) or any(image is not None for image in p2):
        return "choice"
    return "fill_blank"


def _normalize_loaded_option_images(
    images: Iterable[Optional[EmbeddedImage]],
) -> Tuple[
    Optional[EmbeddedImage],
    Optional[EmbeddedImage],
    Optional[EmbeddedImage],
    Optional[EmbeddedImage],
]:
    image_list = list(images)
    if len(image_list) != 4:
        raise ValueError("Manifest p2 must contain exactly 4 option image references.")
    return tuple(image_list)  # type: ignore[return-value]


def _normalize_asset_refs(refs: Sequence[Optional[str]]) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    if len(refs) > 4:
        raise ValueError("Manifest p2 contains more than 4 option image references.")
    ref_list = list(refs)
    ref_list.extend([None] * (4 - len(ref_list)))
    return tuple(ref_list)  # type: ignore[return-value]


def _write_asset(
    archive: zipfile.ZipFile,
    assets: Dict[str, Dict[str, Any]],
    question_index: int,
    slot: str,
    image: Optional[EmbeddedImage],
) -> Optional[str]:
    if image is None:
        return None

    extension = Path(image.filename).suffix.lower()
    if not extension:
        extension = mimetypes.guess_extension(image.media_type) or ".bin"

    asset_path = f"assets/q{question_index:04d}/{slot}{extension}"
    archive.writestr(asset_path, image.data)
    assets[asset_path] = {
        "filename": image.filename,
        "media_type": image.media_type,
        "size": len(image.data),
    }
    return asset_path


def _read_manifest(archive: zipfile.ZipFile) -> Dict[str, Any]:
    try:
        manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
    except KeyError as exc:
        raise ValueError(f"Missing {MANIFEST_NAME}; this is not a qpaper file.") from exc

    if manifest.get("format") != FORMAT_ID:
        raise ValueError(f"Unsupported qpaper format: {manifest.get('format')!r}")
    if manifest.get("version") != FORMAT_VERSION:
        raise ValueError(f"Unsupported qpaper version: {manifest.get('version')!r}")
    if not isinstance(manifest.get("questions"), list):
        raise ValueError("Manifest questions must be a list.")
    if not isinstance(manifest.get("assets", {}), dict):
        raise ValueError("Manifest assets must be a dictionary.")
    return manifest


def _read_asset(
    archive: zipfile.ZipFile,
    manifest: Mapping[str, Any],
    ref: Optional[str],
) -> Optional[EmbeddedImage]:
    if ref is None:
        return None

    assets = manifest.get("assets", {})
    if not isinstance(assets, Mapping):
        raise ValueError("Manifest assets must be a dictionary.")

    asset_meta = assets.get(ref, {})
    if not isinstance(asset_meta, Mapping):
        asset_meta = {}

    try:
        data = archive.read(ref)
    except KeyError as exc:
        raise ValueError(f"Missing embedded image asset: {ref}") from exc

    filename = str(asset_meta.get("filename") or Path(ref).name)
    media_type = str(asset_meta.get("media_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream")
    return EmbeddedImage(data=data, filename=filename, media_type=media_type)


def _require_string(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Question field {key!r} must be a string.")
    return value


def _safe_filename(prefix: str, image: EmbeddedImage) -> str:
    original = Path(image.filename).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", original).strip("._")
    if not cleaned:
        cleaned = "image" + (mimetypes.guess_extension(image.media_type) or ".bin")
    return f"{prefix}_{cleaned}"


def _inspect_qpaper(input_path: PathLike) -> str:
    paper = read_qpaper(input_path)
    lines = [f"title: {paper.title}", f"questions: {len(paper.questions)}"]
    for index, question in enumerate(paper.questions, start=1):
        option_image_count = sum(1 for image in question.p2 if image is not None)
        lines.append(
            f"q{index}: type={question.question_type}, t1={len(question.t1)} chars, "
            f"p1={'yes' if question.p1 else 'no'}, "
            f"t2=4 options, p2={option_image_count} images"
        )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read or extract .qpaper files.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="print a qpaper summary")
    inspect_parser.add_argument("file")

    extract_parser = subparsers.add_parser("extract", help="extract embedded images")
    extract_parser.add_argument("file")
    extract_parser.add_argument("output_dir")

    args = parser.parse_args(argv)
    if args.command == "inspect":
        print(_inspect_qpaper(args.file))
        return 0
    if args.command == "extract":
        written = extract_images(args.file, args.output_dir)
        for path in written:
            print(path)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
