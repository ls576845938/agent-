from __future__ import annotations

from pathlib import Path


class GitMetadataError(ValueError):
    pass


def resolve_git_dirs(repo_root: Path) -> tuple[Path, Path]:
    dot_git = repo_root.resolve() / ".git"
    if dot_git.is_file():
        pointer = dot_git.read_text(encoding="utf-8").strip()
        if not pointer.startswith("gitdir: "):
            raise GitMetadataError("gitdir_pointer_invalid")
        raw = Path(pointer.removeprefix("gitdir: "))
        git_dir = raw.resolve() if raw.is_absolute() else (repo_root / raw).resolve()
    elif dot_git.is_dir():
        git_dir = dot_git
    else:
        raise GitMetadataError("git_directory_missing")

    common_file = git_dir / "commondir"
    if common_file.is_file():
        raw_common = Path(common_file.read_text(encoding="utf-8").strip())
        common_dir = raw_common.resolve() if raw_common.is_absolute() else (git_dir / raw_common).resolve()
    else:
        common_dir = git_dir.resolve()
    return git_dir, common_dir


def main_repository_root(repo_root: Path) -> Path:
    _, common_dir = resolve_git_dirs(repo_root)
    if common_dir.name != ".git":
        raise GitMetadataError(f"git_common_directory_unexpected:{common_dir}")
    return common_dir.parent


def read_ref_heads(repo_root: Path, *, prefix: str = "refs/heads/") -> dict[str, str]:
    _, common_dir = resolve_git_dirs(repo_root)
    refs: dict[str, str] = {}
    packed = common_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith(("#", "^")):
                continue
            value, separator, ref = line.partition(" ")
            if separator and ref.startswith(prefix):
                refs[ref] = value

    loose_root = common_dir / Path(prefix)
    if loose_root.is_dir():
        for path in loose_root.rglob("*"):
            if not path.is_file() or path.name.endswith(".lock"):
                continue
            ref = f"{prefix.rstrip('/')}/{path.relative_to(loose_root).as_posix()}"
            refs[ref] = _resolve_ref_value(common_dir, path.read_text(encoding="ascii").strip())
    return refs


def current_branch_head(repo_root: Path) -> tuple[str, str]:
    git_dir, common_dir = resolve_git_dirs(repo_root)
    value = (git_dir / "HEAD").read_text(encoding="ascii").strip()
    if not value.startswith("ref: "):
        return "HEAD", value
    ref = value.removeprefix("ref: ")
    return ref.removeprefix("refs/heads/"), _read_ref(common_dir, ref)


def _read_ref(common_dir: Path, ref: str) -> str:
    loose = common_dir / Path(ref)
    if loose.is_file():
        return _resolve_ref_value(common_dir, loose.read_text(encoding="ascii").strip())
    packed = common_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith(("#", "^")):
                continue
            value, separator, candidate = line.partition(" ")
            if separator and candidate == ref:
                return value
    raise GitMetadataError(f"git_ref_missing:{ref}")


def _resolve_ref_value(common_dir: Path, value: str) -> str:
    if value.startswith("ref: "):
        return _read_ref(common_dir, value.removeprefix("ref: "))
    return value
