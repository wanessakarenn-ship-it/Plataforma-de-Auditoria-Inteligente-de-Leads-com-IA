import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from typing import Protocol, TypeVar


class SearchableKnowledge(Protocol):
    id: str
    title: str
    body: str


T = TypeVar("T", bound=SearchableKnowledge)


class KnowledgeIndexer(Protocol):
    def rank(
        self, query: str, documents: Sequence[T], limit: int
    ) -> list[tuple[float, T]]: ...


def _normalize_token(token: str) -> str:
    decomposed = unicodedata.normalize("NFKD", token.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def tokenize(text: str) -> Counter[str]:
    return Counter(
        _normalize_token(match)
        for match in re.findall(r"[^\W_]+", text, flags=re.UNICODE)
    )


def lexical_score(query: str, text: str) -> float:
    query_tokens = tokenize(query)
    if not query_tokens:
        return 0.0
    document_tokens = tokenize(text)
    matched = sum(min(count, document_tokens[token]) for token, count in query_tokens.items())
    score = matched / sum(query_tokens.values())
    if _normalize_token(query.strip()) and _normalize_token(query.strip()) in _normalize_token(text):
        score = min(1.0, score + 0.1)
    return round(score, 6)


def excerpt_for(query: str, text: str, max_chars: int = 480) -> str:
    query_tokens = set(tokenize(query))
    for match in re.finditer(r"[^\W_]+", text, flags=re.UNICODE):
        if _normalize_token(match.group()) in query_tokens:
            start = max(0, match.start() - max_chars // 4)
            end = min(len(text), start + max_chars)
            excerpt = text[start:end].strip()
            if start:
                excerpt = f"…{excerpt}"
            if end < len(text):
                excerpt = f"{excerpt}…"
            return excerpt
    return text[:max_chars].strip()


class LocalLexicalIndexer:
    def rank(
        self, query: str, documents: Sequence[T], limit: int
    ) -> list[tuple[float, T]]:
        ranked = sorted(
            (
                (lexical_score(query, document.title + "\n" + document.body), document)
                for document in documents
            ),
            key=lambda item: (-item[0], item[1].id),
        )
        return [(score, document) for score, document in ranked if score > 0][:limit]


local_lexical_indexer: KnowledgeIndexer = LocalLexicalIndexer()
