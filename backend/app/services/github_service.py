import httpx
from github import Github

from app.agents.models import RepositoryContext, RepositoryFile
from app.config import settings

DEFAULT_CONTEXT_FILES = [
    "backend/app/main.py",
    "backend/app/models.py",
    "backend/app/database.py",
    "README.md",
    "backend/app/routes/sentry.py",
    "backend/app/agents/models.py",
    "backend/app/agents/investigation_agent.py",
    "backend/app/agents/github_agent.py",
    "backend/app/agents/patch_agent.py",
    "backend/app/agents/validation_agent.py",
    "frontend/src/App.tsx",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
]


def load_repository_context(
    repo_full_name: str,
    default_branch: str = "main",
    files_to_inspect: list[str] | None = None,
    max_chars_per_file: int = 4000,
    include_defaults: bool = True,
    source_root: str | None = None,
) -> RepositoryContext:
    repo_full_name = _normalize_repo_full_name(repo_full_name)
    default_branch = default_branch.strip() or "main"
    defaults = DEFAULT_CONTEXT_FILES if include_defaults else []
    paths = _dedupe([*(files_to_inspect or []), *defaults])
    root = (settings.repo_source_root if source_root is None else source_root).strip("/")

    github_token = settings.github_token.strip() if settings.github_token else None

    if not github_token:
        # Public repos can still be read without a token through raw.githubusercontent.com,
        # which is not subject to the 60 requests/hour unauthenticated API limit.
        return _load_public_files(repo_full_name, default_branch, paths, root, max_chars_per_file)

    try:
        gh = Github(github_token)
        repo = gh.get_repo(repo_full_name)
    except Exception as exc:
        return RepositoryContext(
            repo_full_name=repo_full_name,
            default_branch=default_branch,
            summary=(
                f"Failed to load repository metadata for {repo_full_name} "
                f"on branch {default_branch}: {exc}"
            ),
            files=[],
        )

    loaded_files: list[RepositoryFile] = []

    for path in paths:
        try:
            contents = repo.get_contents(_repo_path(root, path), ref=default_branch)
        except Exception:
            continue

        if isinstance(contents, list):
            continue

        try:
            text = contents.decoded_content.decode("utf-8", errors="replace")
        except Exception:
            continue

        truncated = len(text) > max_chars_per_file
        loaded_files.append(
            RepositoryFile(
                path=path,
                content=text[:max_chars_per_file],
                truncated=truncated,
            )
        )

    return RepositoryContext(
        repo_full_name=repo_full_name,
        default_branch=default_branch,
        summary=(
            f"Loaded {len(loaded_files)} repository files from {repo_full_name} "
            f"on branch {default_branch}."
        ),
        files=loaded_files,
    )


def _repo_path(root: str, path: str) -> str:
    return f"{root}/{path}" if root else path


def _load_public_files(
    repo_full_name: str,
    default_branch: str,
    paths: list[str],
    root: str,
    max_chars_per_file: int,
) -> RepositoryContext:
    loaded_files: list[RepositoryFile] = []

    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for path in paths:
            url = (
                f"https://raw.githubusercontent.com/{repo_full_name}/"
                f"{default_branch}/{_repo_path(root, path)}"
            )
            try:
                response = client.get(url)
            except httpx.HTTPError:
                continue

            if response.status_code != 200:
                continue

            text = response.text
            loaded_files.append(
                RepositoryFile(
                    path=path,
                    content=text[:max_chars_per_file],
                    truncated=len(text) > max_chars_per_file,
                )
            )

    return RepositoryContext(
        repo_full_name=repo_full_name,
        default_branch=default_branch,
        summary=(
            f"Loaded {len(loaded_files)} public repository files from {repo_full_name} "
            f"on branch {default_branch} (no GitHub token)."
        ),
        files=loaded_files,
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)

    return result


def _normalize_repo_full_name(repo_full_name: str) -> str:
    cleaned = repo_full_name.strip()

    if cleaned.startswith("https://github.com/"):
        cleaned = cleaned.removeprefix("https://github.com/")

    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]

    return cleaned.strip("/")
