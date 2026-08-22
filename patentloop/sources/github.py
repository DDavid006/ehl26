"""GitHub repository search: evidence that an idea is already implemented."""

from __future__ import annotations

from ..http import HttpError, request
from ..schemas import Document
from .base import Source

API_URL = "https://api.github.com/search/repositories"


class GitHubSource(Source):
    name = "github"

    def search(self, query: str, limit: int, iteration: int | None = None) -> list[Document]:
        headers = {"Accept": "application/vnd.github+json"}
        if self.config.github_token:
            headers["Authorization"] = f"Bearer {self.config.github_token}"
        try:
            response = request(
                API_URL,
                params={"q": query, "per_page": limit, "sort": "stars"},
                headers=headers,
                timeout=self.config.request_timeout,
            )
            payload = response.json()
        except (HttpError, ValueError) as exc:
            self._error(query, exc, iteration)
            return []
        documents = []
        for repo in payload.get("items") or []:
            documents.append(
                Document(
                    source=self.name,
                    external_id=repo.get("full_name") or "",
                    title=repo.get("full_name") or "",
                    url=repo.get("html_url") or "",
                    abstract=(repo.get("description") or "")
                    + f" (stars: {repo.get('stargazers_count', 0)}, language: {repo.get('language')})",
                    year=int((repo.get("created_at") or "0000")[:4] or 0) or None,
                    venue="GitHub",
                    query=query,
                )
            )
        self._trace(query, response, len(documents), iteration)
        return documents
